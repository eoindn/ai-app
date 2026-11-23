"""Booking rules: window validation and conflict detection (SPEC 2.2). Pure functions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.enums import BookingStatus, FaultSeverity, FaultStatus
from app.domain.errors import ValidationFailed

MIN_DURATION = timedelta(minutes=30)
MAX_DURATION = timedelta(hours=8)
MAX_ADVANCE = timedelta(days=30)
SLOT_MINUTES = 15

BLOCKING_FAULT_SEVERITIES = frozenset({FaultSeverity.HIGH, FaultSeverity.CRITICAL})
OUTSTANDING_FAULT_STATUSES = frozenset({FaultStatus.OPEN, FaultStatus.IN_PROGRESS})


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


def _on_slot_boundary(value: datetime) -> bool:
    return value.minute % SLOT_MINUTES == 0 and value.second == 0 and value.microsecond == 0


def validate_window(start: datetime, end: datetime, now: datetime) -> None:
    """REQ-BOOK-02..06. Raises ValidationFailed on the first rule broken."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValidationFailed("start", "Datetimes must include a UTC offset")
    if not _on_slot_boundary(start):
        raise ValidationFailed("start", "Start must be on a 15-minute boundary (:00, :15, :30, :45)")
    if not _on_slot_boundary(end):
        raise ValidationFailed("end", "End must be on a 15-minute boundary (:00, :15, :30, :45)")
    if end <= start:
        raise ValidationFailed("end", "End must be after start")
    duration = end - start
    if duration < MIN_DURATION:
        raise ValidationFailed("end", "Booking must be at least 30 minutes long")
    if duration > MAX_DURATION:
        raise ValidationFailed("end", "Booking must be at most 8 hours long")
    if start < now:
        raise ValidationFailed("start", "Start must not be in the past")
    if start > now + MAX_ADVANCE:
        raise ValidationFailed("start", "Start must be no more than 30 days ahead")


def overlaps(a: Interval, b: Interval) -> bool:
    """REQ-BOOK-07: half-open intervals [start, end) — touching end/start is not an overlap."""
    return a.start < b.end and b.start < a.end


def find_conflicts(new: Interval, existing: Iterable[tuple[Interval, BookingStatus]]) -> list[Interval]:
    """REQ-BOOK-07: only CONFIRMED bookings can conflict."""
    return [iv for iv, status in existing if status == BookingStatus.CONFIRMED and overlaps(new, iv)]


def fault_blocks_booking(severity: FaultSeverity, status: FaultStatus) -> bool:
    """REQ-BOOK-09: outstanding HIGH/CRITICAL faults block new bookings."""
    return severity in BLOCKING_FAULT_SEVERITIES and status in OUTSTANDING_FAULT_STATUSES


def is_active_at(interval: Interval, now: datetime) -> bool:
    """REQ-STAT-05: a booking is active when start <= now < end."""
    return interval.start <= now < interval.end
