"""Maintenance scheduling and work (REQ-MAINT-*)."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.clock import Clock
from app.domain import maintenance as rules
from app.domain.enums import (
    EquipmentStatus,
    MaintenanceEvent,
    MaintenanceStatus,
    Role,
    StatusEvent,
)
from app.domain.errors import Forbidden, IllegalTransition, NotFound, ValidationFailed
from app.domain.permissions import Action, can, require
from app.repositories import maintenance as maintenance_repo
from app.repositories import users as users_repo
from app.repositories.models import MaintenanceTask
from app.services import equipment as equipment_service
from app.services.context import Actor


def _require_technician(db: Session, user_id: int) -> None:
    """REQ-MAINT-02."""
    user = users_repo.get(db, user_id)
    if user is None or user.role != Role.TECHNICIAN or not user.is_active:
        raise ValidationFailed(
            "assigned_technician_id", "Assignee must be an active user with the technician role"
        )


def schedule(
    db: Session,
    clock: Clock,
    actor: Actor,
    equipment_id: str,
    title: str,
    description: str | None,
    due_date: date,
    assigned_technician_id: int,
) -> MaintenanceTask:
    """REQ-MAINT-01..03."""
    require(actor.role, Action.MAINT_SCHEDULE)
    equipment = equipment_service.load(db, equipment_id)
    _require_technician(db, assigned_technician_id)
    now = clock.now()
    rules.validate_due_date(due_date, now)
    task = maintenance_repo.add(
        db,
        MaintenanceTask(
            equipment_pk=equipment.id,
            title=title,
            description=description or None,
            due_date=due_date,
            assigned_technician_id=assigned_technician_id,
            status=MaintenanceStatus.SCHEDULED,
            created_by=actor.id,
            created_at=now,
        ),
    )
    db.commit()
    return task


def list_tasks(
    db: Session,
    clock: Clock,
    actor: Actor,
    status: MaintenanceStatus | None = None,
    equipment_id: str | None = None,
    assigned_technician_id: int | None = None,
    overdue: bool | None = None,
) -> list[MaintenanceTask]:
    """REQ-MAINT-09."""
    require(actor.role, Action.MAINT_VIEW)
    equipment_pk = equipment_service.load(db, equipment_id).id if equipment_id else None
    tasks = maintenance_repo.list_tasks(db, status, equipment_pk, assigned_technician_id)
    if overdue is not None:
        now = clock.now()
        tasks = [t for t in tasks if rules.is_overdue(t.status, t.due_date, now) == overdue]
    return tasks


def get(db: Session, actor: Actor, task_id: int) -> MaintenanceTask:
    require(actor.role, Action.MAINT_VIEW)
    task = maintenance_repo.get(db, task_id)
    if task is None:
        raise NotFound(f"Maintenance task {task_id} not found")
    return task


def assign(db: Session, actor: Actor, task_id: int, technician_id: int) -> MaintenanceTask:
    """REQ-MAINT-04."""
    require(actor.role, Action.MAINT_ASSIGN)
    task = get(db, actor, task_id)
    _require_technician(db, technician_id)
    if not rules.can_reassign(task.status):
        raise IllegalTransition(f"Cannot reassign a task that is {task.status}")
    task.assigned_technician_id = technician_id
    db.commit()
    db.refresh(task)
    return task


def _require_worker(actor: Actor, task: MaintenanceTask) -> None:
    """REQ-MAINT-05/06: assigned technician or any admin."""
    require(actor.role, Action.MAINT_WORK_OWN)
    if task.assigned_technician_id != actor.id and not can(actor.role, Action.MAINT_WORK_ANY):
        raise Forbidden("Only the assigned technician or an admin may work on this task")


def start(db: Session, clock: Clock, actor: Actor, task_id: int) -> MaintenanceTask:
    """REQ-MAINT-05: task -> IN_PROGRESS and equipment -> UNDER_MAINTENANCE, atomically."""
    task = get(db, actor, task_id)
    _require_worker(actor, task)
    target = rules.next_task_status(task.status, MaintenanceEvent.START)
    try:
        equipment_service.apply_transition(db, clock, actor, task.equipment, StatusEvent.START_MAINTENANCE)
        task.status = target
        task.started_at = clock.now()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return task


def complete(
    db: Session, clock: Clock, actor: Actor, task_id: int, completion_notes: str | None
) -> MaintenanceTask:
    """REQ-MAINT-06: equipment returns to AVAILABLE unless it is OUT_OF_SERVICE."""
    task = get(db, actor, task_id)
    _require_worker(actor, task)
    target = rules.next_task_status(task.status, MaintenanceEvent.COMPLETE)
    try:
        if task.equipment.status == EquipmentStatus.UNDER_MAINTENANCE:
            equipment_service.apply_transition(
                db, clock, actor, task.equipment, StatusEvent.COMPLETE_MAINTENANCE
            )
        task.status = target
        task.completed_at = clock.now()
        task.completed_by = actor.id
        task.completion_notes = completion_notes or None
        db.commit()
    except Exception:
        db.rollback()
        raise
    return task


def cancel(db: Session, actor: Actor, task_id: int) -> MaintenanceTask:
    """REQ-MAINT-07: SCHEDULED -> CANCELLED, admin only."""
    require(actor.role, Action.MAINT_CANCEL)
    task = get(db, actor, task_id)
    task.status = rules.next_task_status(task.status, MaintenanceEvent.CANCEL)
    db.commit()
    return task
