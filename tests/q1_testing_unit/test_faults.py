"""Unit tests for app/domain/faults.py (REQ-FAULT-04, REQ-REP-02, SPEC 3.2)."""

from __future__ import annotations

import pytest

from app.domain.enums import FaultEvent as E
from app.domain.enums import FaultStatus as S
from app.domain.errors import IllegalTransition
from app.domain.faults import FAULT_TRANSITIONS, OUTSTANDING, next_fault_status

# Copied by hand from SPEC 3.2
LEGAL = {
    (S.OPEN, E.START): S.IN_PROGRESS,
    (S.IN_PROGRESS, E.RESOLVE): S.RESOLVED,
}
ILLEGAL = [(s, e) for s in S for e in E if (s, e) not in LEGAL]


class TestTransitionTable:
    def test_production_table_matches_spec_exactly(self) -> None:
        assert FAULT_TRANSITIONS == LEGAL

    def test_spec_has_two_legal_and_four_illegal_pairs(self) -> None:
        assert len(LEGAL) == 2
        assert len(ILLEGAL) == 4


class TestLegalTransitions:
    @pytest.mark.parametrize(("current", "event"), list(LEGAL))
    def test_legal_transitions(self, current: S, event: E) -> None:
        assert next_fault_status(current, event) == LEGAL[(current, event)]

    def test_full_lifecycle_open_to_resolved(self) -> None:
        in_progress = next_fault_status(S.OPEN, E.START)
        assert in_progress == S.IN_PROGRESS
        assert next_fault_status(in_progress, E.RESOLVE) == S.RESOLVED


class TestIllegalTransitions:
    """REQ-FAULT-04: every pair not in SPEC 3.2 raises IllegalTransition."""

    @pytest.mark.parametrize(("current", "event"), ILLEGAL)
    def test_every_unlisted_pair_is_illegal(self, current: S, event: E) -> None:
        with pytest.raises(IllegalTransition):
            next_fault_status(current, event)

    def test_open_cannot_be_resolved_directly(self) -> None:
        with pytest.raises(IllegalTransition):
            next_fault_status(S.OPEN, E.RESOLVE)

    @pytest.mark.parametrize("event", list(E))
    def test_nothing_leaves_resolved(self, event: E) -> None:
        with pytest.raises(IllegalTransition):
            next_fault_status(S.RESOLVED, event)

    def test_start_is_not_repeatable(self) -> None:
        with pytest.raises(IllegalTransition):
            next_fault_status(S.IN_PROGRESS, E.START)

    def test_error_message_names_event_and_status(self) -> None:
        with pytest.raises(IllegalTransition) as exc:
            next_fault_status(S.RESOLVED, E.START)
        assert "start" in exc.value.message
        assert "RESOLVED" in exc.value.message


class TestOutstanding:
    """REQ-REP-02, REQ-BOOK-09: outstanding means OPEN or IN_PROGRESS."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(S.OPEN, True), (S.IN_PROGRESS, True), (S.RESOLVED, False)],
    )
    def test_membership(self, status: S, expected: bool) -> None:
        assert (status in OUTSTANDING) is expected
