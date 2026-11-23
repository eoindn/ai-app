"""Fault lifecycle (SPEC 2.3, 3.2). Pure functions."""

from __future__ import annotations

from app.domain.enums import FaultEvent as E
from app.domain.enums import FaultStatus as S
from app.domain.errors import IllegalTransition

FAULT_TRANSITIONS: dict[tuple[S, E], S] = {
    (S.OPEN, E.START): S.IN_PROGRESS,
    (S.IN_PROGRESS, E.RESOLVE): S.RESOLVED,
}

OUTSTANDING = frozenset({S.OPEN, S.IN_PROGRESS})


def next_fault_status(current: S, event: E) -> S:
    """REQ-FAULT-04: SPEC 3.2 transition table."""
    target = FAULT_TRANSITIONS.get((current, event))
    if target is None:
        raise IllegalTransition(f"Cannot '{event}' a fault that is {current}")
    return target
