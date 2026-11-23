"""Fault reporting (REQ-FAULT-*)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.clock import Clock
from app.domain.enums import FaultEvent, FaultSeverity, FaultStatus
from app.domain.errors import NotFound
from app.domain.faults import next_fault_status
from app.domain.permissions import Action, require
from app.repositories import faults as faults_repo
from app.repositories.models import Fault
from app.services import equipment as equipment_service
from app.services.context import Actor


def report(
    db: Session,
    clock: Clock,
    actor: Actor,
    equipment_id: str,
    title: str,
    description: str,
    severity: FaultSeverity,
) -> Fault:
    """REQ-FAULT-01, REQ-FAULT-02, REQ-FAULT-06 (no automatic status change)."""
    require(actor.role, Action.FAULT_REPORT)
    equipment = equipment_service.load(db, equipment_id)
    fault = faults_repo.add(
        db,
        Fault(
            equipment_pk=equipment.id,
            title=title,
            description=description,
            severity=severity,
            status=FaultStatus.OPEN,
            reported_by=actor.id,
            reported_at=clock.now(),
        ),
    )
    db.commit()
    return fault


def list_faults(
    db: Session,
    actor: Actor,
    status: FaultStatus | None = None,
    severity: FaultSeverity | None = None,
    equipment_id: str | None = None,
) -> list[Fault]:
    """REQ-FAULT-03."""
    require(actor.role, Action.FAULT_VIEW)
    equipment_pk = equipment_service.load(db, equipment_id).id if equipment_id else None
    statuses = frozenset({status}) if status else None
    return faults_repo.list_faults(db, statuses, severity, equipment_pk)


def get(db: Session, actor: Actor, fault_id: int) -> Fault:
    """REQ-FAULT-03."""
    require(actor.role, Action.FAULT_VIEW)
    fault = faults_repo.get(db, fault_id)
    if fault is None:
        raise NotFound(f"Fault {fault_id} not found")
    return fault


def start(db: Session, actor: Actor, fault_id: int) -> Fault:
    """REQ-FAULT-04: OPEN -> IN_PROGRESS."""
    require(actor.role, Action.FAULT_UPDATE)
    fault = get(db, actor, fault_id)
    fault.status = next_fault_status(fault.status, FaultEvent.START)
    db.commit()
    return fault


def resolve(db: Session, clock: Clock, actor: Actor, fault_id: int, resolution_notes: str) -> Fault:
    """REQ-FAULT-04, REQ-FAULT-05: IN_PROGRESS -> RESOLVED with notes."""
    require(actor.role, Action.FAULT_UPDATE)
    fault = get(db, actor, fault_id)
    fault.status = next_fault_status(fault.status, FaultEvent.RESOLVE)
    fault.resolution_notes = resolution_notes
    fault.resolved_by = actor.id
    fault.resolved_at = clock.now()
    db.commit()
    return fault
