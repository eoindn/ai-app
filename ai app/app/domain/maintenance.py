"""Maintenance rules: task lifecycle and overdue calculation (SPEC 2.4, 3.3). Pure functions."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.domain.enums import MaintenanceEvent as E
from app.domain.enums import MaintenanceStatus as S
from app.domain.errors import IllegalTransition, ValidationFailed
from app.domain.timeutil import local_date

OPEN_STATUSES = frozenset({S.SCHEDULED, S.IN_PROGRESS})
UPCOMING_WINDOW_DAYS = 7

# (from_status, event) -> to_status.  Role rules live in the permission matrix + services.
TASK_TRANSITIONS: dict[tuple[S, E], S] = {
    (S.SCHEDULED, E.START): S.IN_PROGRESS,
    (S.IN_PROGRESS, E.COMPLETE): S.COMPLETED,
    (S.SCHEDULED, E.CANCEL): S.CANCELLED,
}


def next_task_status(current: S, event: E) -> S:
    """REQ-MAINT-05..07: SPEC 3.3 transition table."""
    target = TASK_TRANSITIONS.get((current, event))
    if target is None:
        raise IllegalTransition(f"Cannot '{event}' a maintenance task that is {current}")
    return target


def is_overdue(status: S, due_date: date, now: datetime) -> bool:
    """REQ-MAINT-08: open task and local today strictly after due_date (not overdue ON the date)."""
    return status in OPEN_STATUSES and local_date(now) > due_date


def is_upcoming(status: S, due_date: date, now: datetime) -> bool:
    """REQ-REP-03: open task due between today and today + 7 days inclusive."""
    today = local_date(now)
    return status in OPEN_STATUSES and today <= due_date <= today + timedelta(days=UPCOMING_WINDOW_DAYS)


def validate_due_date(due_date: date, now: datetime) -> None:
    """REQ-MAINT-03: due date must be today or later at creation."""
    if due_date < local_date(now):
        raise ValidationFailed("due_date", "Due date must be today or later")


def can_reassign(status: S) -> bool:
    """REQ-MAINT-04: only open tasks may be reassigned."""
    return status in OPEN_STATUSES
