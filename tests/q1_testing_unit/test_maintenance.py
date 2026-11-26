"""Unit tests for app/domain/maintenance.py (REQ-MAINT-03..08, REQ-REP-03, SPEC 3.3)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.enums import MaintenanceEvent as E
from app.domain.enums import MaintenanceStatus as S
from app.domain.errors import IllegalTransition, ValidationFailed
from app.domain.maintenance import can_reassign, is_overdue, is_upcoming, next_task_status, validate_due_date

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)  # winter: London == UTC
TODAY = date(2026, 3, 10)
OPEN = [S.SCHEDULED, S.IN_PROGRESS]
CLOSED = [S.COMPLETED, S.CANCELLED]

# Copied by hand from SPEC 3.3
LEGAL = {
    (S.SCHEDULED, E.START): S.IN_PROGRESS,
    (S.IN_PROGRESS, E.COMPLETE): S.COMPLETED,
    (S.SCHEDULED, E.CANCEL): S.CANCELLED,
}
ILLEGAL = [(s, e) for s in S for e in E if (s, e) not in LEGAL]


class TestTaskTransitions:
    """REQ-MAINT-05/06/07: state-transition testing over all 4 statuses x 3 events."""

    @pytest.mark.parametrize(("current", "event"), list(LEGAL))
    def test_legal_transitions(self, current: S, event: E) -> None:
        assert next_task_status(current, event) == LEGAL[(current, event)]

    @pytest.mark.parametrize(("current", "event"), ILLEGAL)
    def test_every_other_pair_is_illegal(self, current: S, event: E) -> None:
        with pytest.raises(IllegalTransition):
            next_task_status(current, event)

    def test_spec_has_three_legal_and_nine_illegal_pairs(self) -> None:
        assert len(LEGAL) == 3
        assert len(ILLEGAL) == 9

    def test_in_progress_task_cannot_be_cancelled(self) -> None:
        """REQ-MAINT-07, named explicitly in SPEC 3.3."""
        with pytest.raises(IllegalTransition):
            next_task_status(S.IN_PROGRESS, E.CANCEL)

    def test_scheduled_task_cannot_jump_to_completed(self) -> None:
        with pytest.raises(IllegalTransition):
            next_task_status(S.SCHEDULED, E.COMPLETE)

    @pytest.mark.parametrize("status", CLOSED)
    @pytest.mark.parametrize("event", list(E))
    def test_closed_tasks_are_terminal(self, status: S, event: E) -> None:
        with pytest.raises(IllegalTransition):
            next_task_status(status, event)

    def test_full_lifecycle_scheduled_to_completed(self) -> None:
        assert next_task_status(next_task_status(S.SCHEDULED, E.START), E.COMPLETE) == S.COMPLETED


class TestIsOverdue:
    """REQ-MAINT-08: open AND London today strictly after due_date. BVA on due = today -1 / 0 / +1."""

    @pytest.mark.parametrize("status", OPEN)
    def test_open_task_due_yesterday_is_overdue(self, status: S) -> None:
        assert is_overdue(status, TODAY - timedelta(days=1), NOW) is True

    @pytest.mark.parametrize("status", OPEN)
    def test_open_task_due_today_is_not_overdue(self, status: S) -> None:
        assert is_overdue(status, TODAY, NOW) is False

    @pytest.mark.parametrize("status", OPEN)
    def test_open_task_due_tomorrow_is_not_overdue(self, status: S) -> None:
        assert is_overdue(status, TODAY + timedelta(days=1), NOW) is False

    @pytest.mark.parametrize("status", CLOSED)
    @pytest.mark.parametrize("offset", [-365, -1, 0, 1])
    def test_closed_tasks_are_never_overdue(self, status: S, offset: int) -> None:
        assert is_overdue(status, TODAY + timedelta(days=offset), NOW) is False

    def test_uses_london_date_not_utc_date_during_bst(self) -> None:
        # 23:30 UTC on 15 Jun is 00:30 on 16 Jun in London (BST), so a task due 15 Jun is overdue.
        late = datetime(2026, 6, 15, 23, 30, tzinfo=UTC)
        assert is_overdue(S.SCHEDULED, date(2026, 6, 15), late) is True

    def test_not_overdue_one_minute_before_london_midnight(self) -> None:
        before_midnight = datetime(2026, 6, 15, 22, 59, tzinfo=UTC)  # 23:59 BST
        assert is_overdue(S.SCHEDULED, date(2026, 6, 15), before_midnight) is False

    def test_overdue_exactly_at_london_midnight(self) -> None:
        midnight = datetime(2026, 6, 15, 23, 0, tzinfo=UTC)  # 00:00 BST on 16 Jun
        assert is_overdue(S.SCHEDULED, date(2026, 6, 15), midnight) is True

    def test_utc_and_london_dates_agree_in_winter(self) -> None:
        late = datetime(2026, 1, 15, 23, 30, tzinfo=UTC)
        assert is_overdue(S.SCHEDULED, date(2026, 1, 15), late) is False


class TestIsUpcoming:
    """REQ-REP-03: open AND today <= due <= today + 7 days, both ends inclusive."""

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [(-1, False), (0, True), (1, True), (6, True), (7, True), (8, False)],
    )
    def test_window_boundaries(self, offset: int, expected: bool) -> None:
        assert is_upcoming(S.SCHEDULED, TODAY + timedelta(days=offset), NOW) is expected

    def test_in_progress_task_counts(self) -> None:
        assert is_upcoming(S.IN_PROGRESS, TODAY + timedelta(days=3), NOW) is True

    @pytest.mark.parametrize("status", CLOSED)
    def test_closed_tasks_never_count(self, status: S) -> None:
        assert is_upcoming(status, TODAY + timedelta(days=3), NOW) is False

    def test_uses_london_date_during_bst(self) -> None:
        late = datetime(2026, 6, 15, 23, 30, tzinfo=UTC)  # already 16 Jun in London
        assert is_upcoming(S.SCHEDULED, date(2026, 6, 15), late) is False
        assert is_upcoming(S.SCHEDULED, date(2026, 6, 23), late) is True  # 16 Jun + 7

    @pytest.mark.parametrize("offset", range(-3, 10))
    def test_overdue_and_upcoming_never_both_true(self, offset: int) -> None:
        due = TODAY + timedelta(days=offset)
        assert not (is_overdue(S.SCHEDULED, due, NOW) and is_upcoming(S.SCHEDULED, due, NOW))


class TestValidateDueDate:
    """REQ-MAINT-03: due_date >= London today at creation."""

    def test_today_is_accepted(self) -> None:
        validate_due_date(TODAY, NOW)

    def test_tomorrow_is_accepted(self) -> None:
        validate_due_date(TODAY + timedelta(days=1), NOW)

    def test_far_future_is_accepted(self) -> None:
        validate_due_date(TODAY + timedelta(days=365), NOW)

    def test_yesterday_is_rejected_on_due_date_field(self) -> None:
        with pytest.raises(ValidationFailed) as exc:
            validate_due_date(TODAY - timedelta(days=1), NOW)
        assert exc.value.field == "due_date"
        assert "today or later" in exc.value.message

    def test_london_date_is_used_during_bst(self) -> None:
        late = datetime(2026, 6, 15, 23, 30, tzinfo=UTC)  # already 16 Jun in London
        with pytest.raises(ValidationFailed):
            validate_due_date(date(2026, 6, 15), late)
        validate_due_date(date(2026, 6, 16), late)


class TestCanReassign:
    """REQ-MAINT-04: only SCHEDULED or IN_PROGRESS tasks can be reassigned."""

    @pytest.mark.parametrize("status", OPEN)
    def test_open_tasks_can_be_reassigned(self, status: S) -> None:
        assert can_reassign(status) is True

    @pytest.mark.parametrize("status", CLOSED)
    def test_closed_tasks_cannot_be_reassigned(self, status: S) -> None:
        assert can_reassign(status) is False
