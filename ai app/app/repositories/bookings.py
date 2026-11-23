"""Booking data access."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import BookingStatus
from app.repositories.models import Booking


def get(db: Session, booking_id: int) -> Booking | None:
    return db.get(Booking, booking_id)


def add(db: Session, booking: Booking) -> Booking:
    db.add(booking)
    db.flush()
    return booking


def confirmed_overlapping(db: Session, equipment_pk: int, start: datetime, end: datetime) -> list[Booking]:
    """Candidate rows for the conflict check; the rule itself lives in domain/booking.py."""
    stmt = select(Booking).where(
        Booking.equipment_pk == equipment_pk,
        Booking.status == BookingStatus.CONFIRMED,
        Booking.start < end,
        Booking.end > start,
    )
    return list(db.scalars(stmt))


def list_bookings(db: Session, user_id: int | None) -> list[Booking]:
    stmt = select(Booking).order_by(Booking.start, Booking.id)
    if user_id is not None:
        stmt = stmt.where(Booking.user_id == user_id)
    return list(db.scalars(stmt))


def confirmed_ending_after(db: Session, equipment_pk: int, now: datetime) -> list[Booking]:
    stmt = (
        select(Booking)
        .where(
            Booking.equipment_pk == equipment_pk,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.end > now,
        )
        .order_by(Booking.start, Booking.id)
    )
    return list(db.scalars(stmt))
