"""Fault data access."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import FaultSeverity, FaultStatus
from app.repositories.models import Fault


def get(db: Session, fault_id: int) -> Fault | None:
    return db.get(Fault, fault_id)


def add(db: Session, fault: Fault) -> Fault:
    db.add(fault)
    db.flush()
    return fault


def list_faults(
    db: Session,
    statuses: frozenset[FaultStatus] | None = None,
    severity: FaultSeverity | None = None,
    equipment_pk: int | None = None,
) -> list[Fault]:
    stmt = select(Fault).order_by(Fault.reported_at, Fault.id)
    if statuses is not None:
        stmt = stmt.where(Fault.status.in_(statuses))
    if severity is not None:
        stmt = stmt.where(Fault.severity == severity)
    if equipment_pk is not None:
        stmt = stmt.where(Fault.equipment_pk == equipment_pk)
    return list(db.scalars(stmt))
