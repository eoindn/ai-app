"""Unit tests for app/domain/status.py (REQ-STAT-02, REQ-STAT-03, REQ-STAT-04, SPEC 3.1).

SPEC_TABLE is copied by hand from SPEC 3.1, not read from TRANSITIONS, so a wrong edit
to the production table is caught.
"""

from __future__ import annotations

import pytest

from app.domain.enums import EquipmentStatus as S
from app.domain.enums import Role
from app.domain.enums import StatusEvent as E
from app.domain.errors import Forbidden, IllegalTransition
from app.domain.status import (
    MAINTENANCE_ONLY_EVENTS,
    TRANSITIONS,
    allowed_events,
    next_status,
    roles_for_event,
)

STAFF = {Role.ADMIN, Role.TECHNICIAN}
ADMIN = {Role.ADMIN}

# (from, event) -> (to, roles allowed)
SPEC_TABLE: dict[tuple[S, E], tuple[S, set[Role]]] = {
    (S.AVAILABLE, E.CHECK_OUT): (S.BOOKED, STAFF),  # T1
    (S.BOOKED, E.RETURN): (S.AVAILABLE, STAFF),  # T2
    (S.AVAILABLE, E.START_MAINTENANCE): (S.UNDER_MAINTENANCE, STAFF),  # T3
    (S.UNDER_MAINTENANCE, E.COMPLETE_MAINTENANCE): (S.AVAILABLE, STAFF),  # T4
    (S.AVAILABLE, E.TAKE_OUT_OF_SERVICE): (S.OUT_OF_SERVICE, STAFF),  # T5
    (S.BOOKED, E.TAKE_OUT_OF_SERVICE): (S.OUT_OF_SERVICE, STAFF),  # T6
    (S.UNDER_MAINTENANCE, E.TAKE_OUT_OF_SERVICE): (S.OUT_OF_SERVICE, STAFF),  # T7
    (S.OUT_OF_SERVICE, E.RETURN_TO_SERVICE): (S.AVAILABLE, ADMIN),  # T8
}

ALL_PAIRS = [(s, e) for s in S for e in E]
LEGAL_PAIRS = list(SPEC_TABLE)
ILLEGAL_PAIRS = [p for p in ALL_PAIRS if p not in SPEC_TABLE]


class TestTransitionTable:
    def test_production_table_matches_spec_exactly(self) -> None:
        assert {k: (t.to, set(t.roles)) for k, t in TRANSITIONS.items()} == SPEC_TABLE

    def test_spec_has_eight_legal_and_sixteen_illegal_pairs(self) -> None:
        assert len(LEGAL_PAIRS) == 8
        assert len(ILLEGAL_PAIRS) == 16


class TestLegalTransitions:
    """REQ-STAT-02: T1-T8 reach their target state for every permitted role."""

    @pytest.mark.parametrize(("current", "event"), LEGAL_PAIRS)
    def test_every_permitted_role_reaches_the_target_state(self, current: S, event: E) -> None:
        target, roles = SPEC_TABLE[(current, event)]
        for role in roles:
            assert next_status(current, event, role) == target

    def test_check_out_then_return_round_trip(self) -> None:
        booked = next_status(S.AVAILABLE, E.CHECK_OUT, Role.TECHNICIAN)
        assert booked == S.BOOKED
        assert next_status(booked, E.RETURN, Role.TECHNICIAN) == S.AVAILABLE

    def test_out_of_service_then_return_to_service_round_trip(self) -> None:
        oos = next_status(S.BOOKED, E.TAKE_OUT_OF_SERVICE, Role.TECHNICIAN)
        assert oos == S.OUT_OF_SERVICE
        assert next_status(oos, E.RETURN_TO_SERVICE, Role.ADMIN) == S.AVAILABLE


class TestIllegalTransitions:
    """REQ-STAT-02: every unlisted (state, event) pair -> IllegalTransition."""

    @pytest.mark.parametrize(("current", "event"), ILLEGAL_PAIRS)
    def test_admin_gets_illegal_transition_for_every_unlisted_pair(self, current: S, event: E) -> None:
        # admin may trigger every event from some state, so the role gate passes and the state gate fires
        with pytest.raises(IllegalTransition):
            next_status(current, event, Role.ADMIN)

    @pytest.mark.parametrize(
        ("current", "event"),
        [
            (S.BOOKED, E.START_MAINTENANCE),  # must be returned first
            (S.OUT_OF_SERVICE, E.CHECK_OUT),
            (S.OUT_OF_SERVICE, E.START_MAINTENANCE),
            (S.OUT_OF_SERVICE, E.TAKE_OUT_OF_SERVICE),  # self-transition
        ],
    )
    def test_notable_illegal_cases_named_in_spec(self, current: S, event: E) -> None:
        with pytest.raises(IllegalTransition):
            next_status(current, event, Role.TECHNICIAN)

    @pytest.mark.parametrize(
        ("current", "event"), [p for p in ILLEGAL_PAIRS if p[1] != E.RETURN_TO_SERVICE]
    )
    def test_technician_with_wrong_state_gets_illegal_not_forbidden(self, current: S, event: E) -> None:
        with pytest.raises(IllegalTransition):
            next_status(current, event, Role.TECHNICIAN)


class TestRoleChecks:
    """REQ-STAT-03: a role not listed -> Forbidden, and the role check comes before the state check."""

    @pytest.mark.parametrize(("current", "event"), ALL_PAIRS)
    def test_academic_is_forbidden_for_every_pair_legal_or_not(self, current: S, event: E) -> None:
        with pytest.raises(Forbidden):
            next_status(current, event, Role.ACADEMIC)

    def test_technician_cannot_return_equipment_to_service(self) -> None:
        with pytest.raises(Forbidden):
            next_status(S.OUT_OF_SERVICE, E.RETURN_TO_SERVICE, Role.TECHNICIAN)

    @pytest.mark.parametrize("current", [S.AVAILABLE, S.BOOKED, S.UNDER_MAINTENANCE])
    def test_technician_return_to_service_is_forbidden_even_from_illegal_states(self, current: S) -> None:
        with pytest.raises(Forbidden):
            next_status(current, E.RETURN_TO_SERVICE, Role.TECHNICIAN)

    def test_admin_can_return_equipment_to_service(self) -> None:
        assert next_status(S.OUT_OF_SERVICE, E.RETURN_TO_SERVICE, Role.ADMIN) == S.AVAILABLE


class TestRolesForEvent:
    @pytest.mark.parametrize("event", list(E))
    def test_matches_union_of_spec_roles(self, event: E) -> None:
        expected: set[Role] = set()
        for (_, ev), (_, roles) in SPEC_TABLE.items():
            if ev == event:
                expected |= roles
        assert set(roles_for_event(event)) == expected

    def test_academic_is_never_listed(self) -> None:
        assert all(Role.ACADEMIC not in roles_for_event(e) for e in E)


class TestAllowedEvents:
    @pytest.mark.parametrize("role", list(Role))
    @pytest.mark.parametrize("current", list(S))
    def test_matches_spec_table(self, current: S, role: Role) -> None:
        expected = {ev for (st, ev), (_, roles) in SPEC_TABLE.items() if st == current and role in roles}
        assert set(allowed_events(current, role)) == expected

    def test_academic_has_no_events_in_any_state(self) -> None:
        assert all(allowed_events(s, Role.ACADEMIC) == [] for s in S)

    def test_out_of_service_only_offers_return_to_service_and_only_to_admin(self) -> None:
        assert allowed_events(S.OUT_OF_SERVICE, Role.ADMIN) == [E.RETURN_TO_SERVICE]
        assert allowed_events(S.OUT_OF_SERVICE, Role.TECHNICIAN) == []


def test_maintenance_only_events_are_exactly_start_and_complete() -> None:
    """REQ-STAT-04."""
    assert set(MAINTENANCE_ONLY_EVENTS) == {E.START_MAINTENANCE, E.COMPLETE_MAINTENANCE}
