"""Equipment and status-history data access."""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.domain.enums import EquipmentStatus
from app.repositories.models import Booking, Equipment, Fault, MaintenanceTask, StatusChange


def get_by_public_id(db: Session, equipment_id: str) -> Equipment | None:
    return db.scalar(select(Equipment).where(Equipment.equipment_id == equipment_id))


def get(db: Session, pk: int) -> Equipment | None:
    return db.get(Equipment, pk)


def add(db: Session, equipment: Equipment) -> Equipment:
    db.add(equipment)
    db.flush()
    return equipment


def search(
    db: Session, q: str | None, status: EquipmentStatus | None, limit: int, offset: int
) -> tuple[int, list[Equipment]]:
    stmt = select(Equipment)
    if q:
        # Escape LIKE wildcards so '%' and '_' in q are matched literally.
        escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                func.lower(Equipment.equipment_id).like(pattern, escape="\\"),
                func.lower(Equipment.name).like(pattern, escape="\\"),
                func.lower(Equipment.location).like(pattern, escape="\\"),
            )
        )
    if status is not None:
        stmt = stmt.where(Equipment.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Equipment.equipment_id).limit(limit).offset(offset))
    return total, list(items)


def has_references(db: Session, pk: int) -> bool:
    for model in (Booking, Fault, MaintenanceTask):
        if db.scalar(select(func.count()).select_from(model).where(model.equipment_pk == pk)):
            return True
    return False


def delete_equipment(db: Session, equipment: Equipment) -> None:
    db.execute(delete(StatusChange).where(StatusChange.equipment_pk == equipment.id))
    db.delete(equipment)
    db.flush()


def add_status_change(db: Session, change: StatusChange) -> None:
    db.add(change)
    db.flush()


def history(db: Session, pk: int) -> list[StatusChange]:
    stmt = (
        select(StatusChange)
        .where(StatusChange.equipment_pk == pk)
        .order_by(StatusChange.changed_at.desc(), StatusChange.id.desc())
    )
    return list(db.scalars(stmt))


def count_by_status(db: Session) -> dict[EquipmentStatus, int]:
    rows = db.execute(select(Equipment.status, func.count()).group_by(Equipment.status)).all()
    return {status: count for status, count in rows}
