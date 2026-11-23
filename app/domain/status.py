"""Equipment status state machine (SPEC section 3.1). The table is the single source of truth."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import EquipmentStatus as S
from app.domain.enums import Role
from app.domain.enums import StatusEvent as E
from app.domain.errors import Forbidden, IllegalTransition

STAFF = frozenset({Role.ADMIN, Role.TECHNICIAN})
ADMIN_ONLY = frozenset({Role.ADMIN})


@dataclass(frozen=True)
class Transition:
    to: S
    roles: frozenset[Role]


# (from_status, event) -> Transition.  Any pair not present is illegal (REQ-STAT-02).
TRANSITIONS: dict[tuple[S, E], Transition] = {
    (S.AVAILABLE, E.CHECK_OUT): Transition(S.BOOKED, STAFF),  # T1
    (S.BOOKED, E.RETURN): Transition(S.AVAILABLE, STAFF),  # T2
    (S.AVAILABLE, E.START_MAINTENANCE): Transition(S.UNDER_MAINTENANCE, STAFF),  # T3
    (S.UNDER_MAINTENANCE, E.COMPLETE_MAINTENANCE): Transition(S.AVAILABLE, STAFF),  # T4
    (S.AVAILABLE, E.TAKE_OUT_OF_SERVICE): Transition(S.OUT_OF_SERVICE, STAFF),  # T5
    (S.BOOKED, E.TAKE_OUT_OF_SERVICE): Transition(S.OUT_OF_SERVICE, STAFF),  # T6
    (S.UNDER_MAINTENANCE, E.TAKE_OUT_OF_SERVICE): Transition(S.OUT_OF_SERVICE, STAFF),  # T7
    (S.OUT_OF_SERVICE, E.RETURN_TO_SERVICE): Transition(S.AVAILABLE, ADMIN_ONLY),  # T8
}

# Events that may only be fired by the maintenance workflow (REQ-STAT-04).
MAINTENANCE_ONLY_EVENTS = frozenset({E.START_MAINTENANCE, E.COMPLETE_MAINTENANCE})


def roles_for_event(event: E) -> frozenset[Role]:
    """All roles that may trigger `event` from at least one state."""
    roles: set[Role] = set()
    for (_, ev), t in TRANSITIONS.items():
        if ev == event:
            roles |= t.roles
    return frozenset(roles)


def next_status(current: S, event: E, role: Role) -> S:
    """REQ-STAT-02, REQ-STAT-03: role is checked before state; returns the target status."""
    if role not in roles_for_event(event):
        raise Forbidden(f"Role '{role}' may not trigger '{event}'")
    transition = TRANSITIONS.get((current, event))
    if transition is None:
        raise IllegalTransition(f"Cannot '{event}' equipment that is {current}")
    if role not in transition.roles:
        raise Forbidden(f"Role '{role}' may not trigger '{event}' from {current}")
    return transition.to


def allowed_events(current: S, role: Role) -> list[E]:
    """Events this role may trigger from `current` (used by the UI only)."""
    return [ev for (st, ev), t in TRANSITIONS.items() if st == current and role in t.roles]
