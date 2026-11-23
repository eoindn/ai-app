"""Bookings (REQ-BOOK-*)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlalchemy.orm import Session

from app.clock import Clock
from app.domain import booking as rules
from app.domain.enums import BookingStatus, CancelReason, EquipmentStatus
from app.domain.errors import Conflict, Forbidden, NotFound
from app.domain.permissions import Action, can, require
from app.logging import log_event
from app.repositories import bookings as bookings_repo
from app.repositories import faults as faults_repo
from app.repositories.models import Booking
from app.services import equipment as equipment_service
from app.services.context import Actor

# REQ-BOOK-16: serialises check-then-insert within this (single) process.
_booking_lock = threading.Lock()


def create(
    db: Session,
    clock: Clock,
    actor: Actor,
    equipment_id: str,
    start: datetime,
    end: datetime,
    purpose: str,
) -> Booking:
    """REQ-BOOK-01..10, REQ-BOOK-16."""
    require(actor.role, Action.BOOKING_CREATE)
    with _booking_lock:
        try:
            equipment = equipment_service.load(db, equipment_id)
            now = clock.now()
            rules.validate_window(start, end, now)

            if equipment.status == EquipmentStatus.OUT_OF_SERVICE:
                raise Conflict("Equipment is out of service and cannot be booked")

            outstanding = faults_repo.list_faults(
                db, statuses=rules.OUTSTANDING_FAULT_STATUSES, equipment_pk=equipment.id
            )
            if any(rules.fault_blocks_booking(f.severity, f.status) for f in outstanding):
                raise Conflict("Equipment has an outstanding HIGH or CRITICAL fault")

            new = rules.Interval(start, end)
            candidates = bookings_repo.confirmed_overlapping(db, equipment.id, start, end)
            conflicts = rules.find_conflicts(
                new, [(rules.Interval(b.start, b.end), b.status) for b in candidates]
            )
            if conflicts:
                log_event(
                    "booking_conflict",
                    logging.INFO,
                    equipment_id=equipment_id,
                    start=start.isoformat(),
                    end=end.isoformat(),
                )
                raise Conflict("Equipment is already booked for part of that time")

            booking = bookings_repo.add(
                db,
                Booking(
                    equipment_pk=equipment.id,
                    user_id=actor.id,
                    start=start,
                    end=end,
                    purpose=purpose,
                    status=BookingStatus.CONFIRMED,
                    created_at=now,
                ),
            )
            db.commit()
            return booking
        except Exception:
            db.rollback()
            raise


def list_bookings(db: Session, actor: Actor, scope: str = "mine") -> list[Booking]:
    """REQ-BOOK-11."""
    if scope == "all":
        require(actor.role, Action.BOOKING_VIEW_ALL)
        return bookings_repo.list_bookings(db, None)
    require(actor.role, Action.BOOKING_VIEW_OWN)
    return bookings_repo.list_bookings(db, actor.id)


def get(db: Session, actor: Actor, booking_id: int) -> Booking:
    """REQ-BOOK-12."""
    require(actor.role, Action.BOOKING_VIEW_OWN)
    booking = bookings_repo.get(db, booking_id)
    if booking is None:
        raise NotFound(f"Booking {booking_id} not found")
    if booking.user_id != actor.id and not can(actor.role, Action.BOOKING_VIEW_ALL):
        raise Forbidden("You may only view your own bookings")
    return booking


def cancel(db: Session, clock: Clock, actor: Actor, booking_id: int) -> Booking:
    """REQ-BOOK-13, REQ-BOOK-14."""
    require(actor.role, Action.BOOKING_CANCEL_OWN)
    booking = bookings_repo.get(db, booking_id)
    if booking is None:
        raise NotFound(f"Booking {booking_id} not found")
    if booking.user_id != actor.id and not can(actor.role, Action.BOOKING_CANCEL_ANY):
        raise Forbidden("You may only cancel your own bookings")
    if booking.status != BookingStatus.CONFIRMED:
        raise Conflict("Booking is already cancelled")
    now = clock.now()
    if now >= booking.start:
        raise Conflict("Booking has already started and cannot be cancelled")
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now
    booking.cancelled_by = actor.id
    booking.cancel_reason = CancelReason.USER_CANCELLED
    db.commit()
    return booking


def equipment_schedule(
    db: Session, clock: Clock, actor: Actor, equipment_id: str
) -> list[tuple[Booking, bool]]:
    """REQ-BOOK-15: returns (booking, show_identity) pairs."""
    require(actor.role, Action.EQUIPMENT_VIEW)
    equipment = equipment_service.load(db, equipment_id)
    see_all = can(actor.role, Action.BOOKING_VIEW_OTHERS_IDENTITY)
    rows = bookings_repo.confirmed_ending_after(db, equipment.id, clock.now())
    return [(b, see_all or b.user_id == actor.id) for b in rows]
