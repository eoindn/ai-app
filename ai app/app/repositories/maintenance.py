"""Maintenance task data access."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import MaintenanceStatus
from app.repositories.models import MaintenanceTask


def get(db: Session, task_id: int) -> MaintenanceTask | None:
    return db.get(MaintenanceTask, task_id)


def add(db: Session, task: MaintenanceTask) -> MaintenanceTask:
    db.add(task)
    db.flush()
    return task


def list_tasks(
    db: Session,
    status: MaintenanceStatus | None = None,
    equipment_pk: int | None = None,
    assigned_technician_id: int | None = None,
) -> list[MaintenanceTask]:
    stmt = select(MaintenanceTask).order_by(MaintenanceTask.due_date, MaintenanceTask.id)
    if status is not None:
        stmt = stmt.where(MaintenanceTask.status == status)
    if equipment_pk is not None:
        stmt = stmt.where(MaintenanceTask.equipment_pk == equipment_pk)
    if assigned_technician_id is not None:
        stmt = stmt.where(MaintenanceTask.assigned_technician_id == assigned_technician_id)
    return list(db.scalars(stmt))
