"""Equipment inventory and status changes (REQ-INV-*, REQ-STAT-*)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.clock import Clock
from app.domain import status as status_rules
from app.domain.booking import Interval, is_active_at
from app.domain.enums import BookingStatus, CancelReason, EquipmentStatus, StatusEvent
from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.domain.permissions import Action, require
from app.logging import log_event
from app.repositories import bookings as bookings_repo
from app.repositories import equipment as equipment_repo
from app.repositories.models import Equipment, StatusChange
from app.services.context import Actor


def get_equipment(db: Session, actor: Actor, equipment_id: str) -> Equipment:
    """REQ-INV-04."""
    require(actor.role, Action.EQUIPMENT_VIEW)
    return load(db, equipment_id)


def load(db: Session, equipment_id: str) -> Equipment:
    equipment = equipment_repo.get_by_public_id(db, equipment_id)
    if equipment is None:
        raise NotFound(f"Equipment '{equipment_id}' not found")
    return equipment


def search(
    db: Session,
    actor: Actor,
    q: str | None = None,
    status: EquipmentStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Equipment]]:
    """REQ-INV-07, REQ-INV-08."""
    require(actor.role, Action.EQUIPMENT_VIEW)
    return equipment_repo.search(db, q or None, status, limit, offset)


def create(
    db: Session,
    clock: Clock,
    actor: Actor,
    equipment_id: str,
    name: str,
    location: str,
    description: str | None,
) -> Equipment:
    """REQ-INV-01, REQ-INV-02: new equipment starts AVAILABLE; duplicate ID -> 409."""
    require(actor.role, Action.EQUIPMENT_CREATE)
    if equipment_repo.get_by_public_id(db, equipment_id) is not None:
        raise Conflict(f"Equipment '{equipment_id}' already exists")
    now = clock.now()
    equipment = equipment_repo.add(
        db,
        Equipment(
            equipment_id=equipment_id,
            name=name,
            location=location,
            description=description or None,
            status=EquipmentStatus.AVAILABLE,
            created_at=now,
            updated_at=now,
        ),
    )
    db.commit()
    return equipment


def update(
    db: Session, clock: Clock, actor: Actor, equipment_id: str, changes: dict[str, str | None]
) -> Equipment:
    """REQ-INV-05: only name/location/description; omitted fields unchanged."""
    require(actor.role, Action.EQUIPMENT_UPDATE)
    equipment = load(db, equipment_id)
    if not changes:
        return equipment
    if "name" in changes and changes["name"] is not None:
        equipment.name = changes["name"]
    if "location" in changes and changes["location"] is not None:
        equipment.location = changes["location"]
    if "description" in changes:
        equipment.description = changes["description"] or None
    equipment.updated_at = clock.now()
    db.commit()
    return equipment


def delete(db: Session, actor: Actor, equipment_id: str) -> None:
    """REQ-INV-06: blocked (409) if any booking, fault or maintenance task references it."""
    require(actor.role, Action.EQUIPMENT_DELETE)
    equipment = load(db, equipment_id)
    if equipment_repo.has_references(db, equipment.id):
        raise Conflict(
            "Equipment has bookings, faults or maintenance records and cannot be deleted; "
            "take it out of service instead"
        )
    equipment_repo.delete_equipment(db, equipment)
    db.commit()


def history(db: Session, actor: Actor, equipment_id: str) -> list[StatusChange]:
    """REQ-STAT-07."""
    require(actor.role, Action.EQUIPMENT_VIEW_HISTORY)
    equipment = load(db, equipment_id)
    return equipment_repo.history(db, equipment.id)


def apply_transition(
    db: Session,
    clock: Clock,
    actor: Actor,
    equipment: Equipment,
    event: StatusEvent,
    reason: str | None = None,
) -> None:
    """REQ-STAT-02, REQ-STAT-03, REQ-STAT-07. Does NOT commit: callers own the transaction."""
    from_status = equipment.status
    to_status = status_rules.next_status(from_status, event, actor.role)
    now = clock.now()
    equipment.status = to_status
    equipment.updated_at = now
    equipment_repo.add_status_change(
        db,
        StatusChange(
            equipment_pk=equipment.id,
            from_status=from_status,
            to_status=to_status,
            event=event.value,
            user_id=actor.id,
            reason=reason,
            changed_at=now,
        ),
    )
    log_event(
        "status_transition",
        equipment_id=equipment.equipment_id,
        status_event=event.value,
        from_status=from_status.value,
        to_status=to_status.value,
    )


def change_status(
    db: Session,
    clock: Clock,
    actor: Actor,
    equipment_id: str,
    event: StatusEvent,
    booking_id: int | None = None,
    reason: str | None = None,
) -> Equipment:
    """REQ-STAT-04..06: manual status events."""
    require(actor.role, Action.EQUIPMENT_CHANGE_STATUS)
    if event in status_rules.MAINTENANCE_ONLY_EVENTS:
        raise ValidationFailed("event", f"'{event}' can only be triggered by a maintenance task")
    if actor.role not in status_rules.roles_for_event(event):
        raise Forbidden(f"Role '{actor.role}' may not trigger '{event}'")

    equipment = load(db, equipment_id)
    try:
        if event == StatusEvent.CHECK_OUT:
            # Check legality first so an illegal transition is reported as such.
            status_rules.next_status(equipment.status, event, actor.role)
            _require_active_booking(db, clock, equipment, booking_id)

        apply_transition(db, clock, actor, equipment, event, reason)

        if event == StatusEvent.TAKE_OUT_OF_SERVICE:
            now = clock.now()
            for booking in bookings_repo.confirmed_ending_after(db, equipment.id, now):
                booking.status = BookingStatus.CANCELLED
                booking.cancelled_at = now
                booking.cancelled_by = actor.id
                booking.cancel_reason = CancelReason.EQUIPMENT_OUT_OF_SERVICE
        db.commit()
    except Exception:
        db.rollback()
        raise
    return equipment


def _require_active_booking(db: Session, clock: Clock, equipment: Equipment, booking_id: int | None) -> None:
    """REQ-STAT-05."""
    if booking_id is None:
        raise ValidationFailed("booking_id", "booking_id is required for check_out")
    booking = bookings_repo.get(db, booking_id)
    if booking is None:
        raise NotFound(f"Booking {booking_id} not found")
    if booking.equipment_pk != equipment.id:
        raise Conflict("Booking is for different equipment")
    if booking.status != BookingStatus.CONFIRMED:
        raise Conflict("Booking is not confirmed")
    if not is_active_at(Interval(booking.start, booking.end), clock.now()):
        raise Conflict("Booking is not active at the current time")
