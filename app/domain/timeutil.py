"""Calendar helpers. Pure functions: 'now' is always passed in (SPEC 1.2, OD-6)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

LAB_TZ = ZoneInfo("Europe/London")


def local_date(instant: datetime) -> date:
    """REQ-MAINT-08 / REQ-REP-03: calendar rules use the Europe/London local date."""
    if instant.tzinfo is None:
        raise ValueError("instant must be timezone-aware")
    return instant.astimezone(LAB_TZ).date()


def local_naive_to_utc(value: datetime) -> datetime:
    """Interpret a naive datetime as Europe/London wall time (first occurrence when ambiguous)."""
    if value.tzinfo is not None:
        raise ValueError("expected a naive datetime")
    return value.replace(tzinfo=LAB_TZ, fold=0).astimezone(UTC)
