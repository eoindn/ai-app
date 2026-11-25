"""Unit tests for app/domain/booking.py (REQ-BOOK-02..07, REQ-BOOK-09, REQ-STAT-05)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.booking import (
    Interval,
    fault_blocks_booking,
    find_conflicts,
    is_active_at,
    overlaps,
    validate_window,
)
from app.domain.enums import BookingStatus, FaultSeverity, FaultStatus
from app.domain.errors import ValidationFailed

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
START = NOW + timedelta(hours=1)  # 11:00, on a slot boundary


def window(duration: timedelta, start: datetime = START) -> tuple[datetime, datetime]:
    return start, start + duration


def failure(start: datetime, end: datetime, now: datetime = NOW) -> ValidationFailed:
    with pytest.raises(ValidationFailed) as exc:
        validate_window(start, end, now)
    return exc.value


class TestValidateWindowValid:
    def test_typical_one_hour_booking_is_accepted(self) -> None:
        validate_window(*window(timedelta(hours=1)), NOW)

    def test_non_utc_offset_is_accepted_when_it_falls_on_a_boundary(self) -> None:
        ist = timezone(timedelta(hours=5, minutes=30))
        start = datetime(2026, 3, 10, 16, 30, tzinfo=ist)  # 11:00 UTC
        validate_window(start, start + timedelta(hours=1), NOW)


class TestDuration:
    """REQ-BOOK-02/03: BVA around 0, 30 minutes and 8 hours."""

    @pytest.mark.parametrize("minutes", [30, 45, 60, 480])
    def test_accepted_durations_include_both_limits(self, minutes: int) -> None:
        validate_window(*window(timedelta(minutes=minutes)), NOW)

    def test_just_under_minimum_is_rejected(self) -> None:
        err = failure(*window(timedelta(minutes=15)))
        assert err.field == "end"
        assert "30 minutes" in err.message

    def test_just_over_maximum_is_rejected(self) -> None:
        err = failure(*window(timedelta(hours=8, minutes=15)))
        assert err.field == "end"
        assert "8 hours" in err.message

    def test_end_equal_to_start_is_rejected(self) -> None:
        err = failure(START, START)
        assert err.field == "end"
        assert "after start" in err.message

    def test_end_before_start_is_rejected(self) -> None:
        err = failure(START, START - timedelta(hours=1))
        assert err.field == "end"


class TestSlotBoundary:
    """REQ-BOOK-04: minutes in {0,15,30,45}, seconds and microseconds zero."""

    @pytest.mark.parametrize("minute", [0, 15, 30, 45])
    def test_valid_minutes_are_accepted(self, minute: int) -> None:
        start = NOW.replace(hour=12, minute=minute)
        validate_window(start, start + timedelta(hours=1), NOW)

    @pytest.mark.parametrize("minute", [1, 14, 16, 29, 31, 44, 46, 59])
    def test_off_boundary_start_minutes_are_rejected(self, minute: int) -> None:
        start = NOW.replace(hour=12, minute=minute)
        err = failure(start, start + timedelta(hours=1))
        assert err.field == "start"

    def test_off_boundary_end_is_rejected_on_the_end_field(self) -> None:
        err = failure(START, START + timedelta(hours=1, minutes=10))
        assert err.field == "end"

    def test_non_zero_seconds_are_rejected(self) -> None:
        start = START.replace(second=1)
        assert failure(start, start + timedelta(hours=1)).field == "start"

    def test_non_zero_microseconds_are_rejected(self) -> None:
        start = START.replace(microsecond=1)
        assert failure(start, start + timedelta(hours=1)).field == "start"


class TestNotInPast:
    """REQ-BOOK-05: start >= now (BVA: equal accepted, one slot earlier rejected)."""

    def test_start_equal_to_now_is_accepted(self) -> None:
        validate_window(NOW, NOW + timedelta(hours=1), NOW)

    def test_start_one_slot_before_now_is_rejected(self) -> None:
        start = NOW - timedelta(minutes=15)
        err = failure(start, start + timedelta(hours=1))
        assert err.field == "start"
        assert "past" in err.message


class TestMaxAdvance:
    """REQ-BOOK-06: start <= now + 30 days, inclusive."""

    def test_start_exactly_30_days_ahead_is_accepted(self) -> None:
        start = NOW + timedelta(days=30)
        validate_window(start, start + timedelta(hours=1), NOW)

    def test_start_one_slot_beyond_30_days_is_rejected(self) -> None:
        start = NOW + timedelta(days=30, minutes=15)
        err = failure(start, start + timedelta(hours=1))
        assert err.field == "start"
        assert "30 days" in err.message


class TestTimezoneAwareness:
    def test_naive_start_is_rejected(self) -> None:
        naive = datetime(2026, 3, 10, 11, 0)  # noqa: DTZ001
        assert failure(naive, START + timedelta(hours=1)).field == "start"

    def test_naive_end_is_rejected(self) -> None:
        naive = datetime(2026, 3, 10, 12, 0)  # noqa: DTZ001
        failure(START, naive)  # SPEC names no field for this case, so only the rejection is asserted


class TestOverlaps:
    """REQ-BOOK-07: half-open intervals, new.start < existing.end AND existing.start < new.end."""

    base = Interval(datetime(2026, 3, 10, 10, 0, tzinfo=UTC), datetime(2026, 3, 10, 12, 0, tzinfo=UTC))

    @staticmethod
    def at(hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 3, 10, hour, minute, tzinfo=UTC)

    @pytest.mark.parametrize(
        ("other", "expected"),
        [
            (Interval(at(8), at(10)), False),  # ends exactly when base starts
            (Interval(at(12), at(14)), False),  # starts exactly when base ends
            (Interval(at(8), at(9)), False),  # entirely before
            (Interval(at(13), at(14)), False),  # entirely after
            (Interval(at(9), at(10, 1)), True),  # overlaps by 1 minute at the start
            (Interval(at(11, 59), at(13)), True),  # overlaps by 1 minute at the end
            (Interval(at(10), at(12)), True),  # identical
            (Interval(at(10, 30), at(11, 30)), True),  # contained
            (Interval(at(9), at(13)), True),  # contains base
        ],
    )
    def test_overlap_equivalence_classes_and_boundaries(self, other: Interval, expected: bool) -> None:
        assert overlaps(self.base, other) is expected
        assert overlaps(other, self.base) is expected  # symmetric


class TestFindConflicts:
    """REQ-BOOK-07: CANCELLED bookings never conflict."""

    new = Interval(datetime(2026, 3, 10, 10, 0, tzinfo=UTC), datetime(2026, 3, 10, 11, 0, tzinfo=UTC))
    clash = Interval(datetime(2026, 3, 10, 10, 30, tzinfo=UTC), datetime(2026, 3, 10, 11, 30, tzinfo=UTC))
    clear = Interval(datetime(2026, 3, 10, 11, 0, tzinfo=UTC), datetime(2026, 3, 10, 12, 0, tzinfo=UTC))

    def test_no_existing_bookings_means_no_conflicts(self) -> None:
        assert find_conflicts(self.new, []) == []

    def test_confirmed_overlap_is_returned(self) -> None:
        assert find_conflicts(self.new, [(self.clash, BookingStatus.CONFIRMED)]) == [self.clash]

    def test_cancelled_overlap_is_ignored(self) -> None:
        assert find_conflicts(self.new, [(self.clash, BookingStatus.CANCELLED)]) == []

    def test_back_to_back_confirmed_booking_is_not_a_conflict(self) -> None:
        assert find_conflicts(self.new, [(self.clear, BookingStatus.CONFIRMED)]) == []

    def test_only_conflicting_bookings_are_returned_from_a_mixed_set(self) -> None:
        existing = [
            (self.clear, BookingStatus.CONFIRMED),
            (self.clash, BookingStatus.CONFIRMED),
            (self.clash, BookingStatus.CANCELLED),
        ]
        assert find_conflicts(self.new, existing) == [self.clash]


class TestFaultBlocksBooking:
    """REQ-BOOK-09: decision table, severity x status."""

    @pytest.mark.parametrize("severity", list(FaultSeverity))
    @pytest.mark.parametrize("status", list(FaultStatus))
    def test_decision_table(self, severity: FaultSeverity, status: FaultStatus) -> None:
        blocking_severity = severity in {FaultSeverity.HIGH, FaultSeverity.CRITICAL}
        outstanding = status in {FaultStatus.OPEN, FaultStatus.IN_PROGRESS}
        assert fault_blocks_booking(severity, status) is (blocking_severity and outstanding)

    def test_high_open_fault_blocks(self) -> None:
        assert fault_blocks_booking(FaultSeverity.HIGH, FaultStatus.OPEN) is True

    def test_medium_open_fault_does_not_block(self) -> None:
        assert fault_blocks_booking(FaultSeverity.MEDIUM, FaultStatus.OPEN) is False

    def test_resolved_critical_fault_does_not_block(self) -> None:
        assert fault_blocks_booking(FaultSeverity.CRITICAL, FaultStatus.RESOLVED) is False


class TestIsActiveAt:
    """REQ-STAT-05: start <= now < end."""

    interval = Interval(datetime(2026, 3, 10, 10, 0, tzinfo=UTC), datetime(2026, 3, 10, 11, 0, tzinfo=UTC))

    @pytest.mark.parametrize(
        ("now", "expected"),
        [
            (datetime(2026, 3, 10, 9, 59, 59, tzinfo=UTC), False),
            (datetime(2026, 3, 10, 10, 0, tzinfo=UTC), True),  # start is inclusive
            (datetime(2026, 3, 10, 10, 30, tzinfo=UTC), True),
            (datetime(2026, 3, 10, 10, 59, 59, tzinfo=UTC), True),
            (datetime(2026, 3, 10, 11, 0, tzinfo=UTC), False),  # end is exclusive
        ],
    )
    def test_boundaries(self, now: datetime, expected: bool) -> None:
        assert is_active_at(self.interval, now) is expected
