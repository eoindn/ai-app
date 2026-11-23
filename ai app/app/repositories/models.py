"""SQLAlchemy ORM models (SPEC section 5)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.domain.enums import (
    BookingStatus,
    CancelReason,
    EquipmentStatus,
    FaultSeverity,
    FaultStatus,
    MaintenanceStatus,
    Role,
)


def _enum(cls: type) -> Enum:
    return Enum(cls, native_enum=False, values_callable=lambda e: [m.value for m in e], length=32)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[Role] = mapped_column(_enum(Role), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_id: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[EquipmentStatus] = mapped_column(_enum(EquipmentStatus), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_pk: Mapped[int] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    purpose: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(_enum(BookingStatus), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancel_reason: Mapped[CancelReason | None] = mapped_column(_enum(CancelReason))

    equipment: Mapped[Equipment] = relationship(lazy="joined")
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")


class Fault(Base):
    __tablename__ = "faults"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_pk: Mapped[int] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[FaultSeverity] = mapped_column(_enum(FaultSeverity), nullable=False)
    status: Mapped[FaultStatus] = mapped_column(_enum(FaultStatus), nullable=False)
    reported_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    equipment: Mapped[Equipment] = relationship(lazy="joined")
    reporter: Mapped[User] = relationship(foreign_keys=[reported_by], lazy="joined")


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_pk: Mapped[int] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    assigned_technician_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[MaintenanceStatus] = mapped_column(_enum(MaintenanceStatus), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    completion_notes: Mapped[str | None] = mapped_column(Text)

    equipment: Mapped[Equipment] = relationship(lazy="joined")
    assignee: Mapped[User] = relationship(foreign_keys=[assigned_technician_id], lazy="joined")


class StatusChange(Base):
    __tablename__ = "status_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_pk: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[EquipmentStatus] = mapped_column(_enum(EquipmentStatus), nullable=False)
    to_status: Mapped[EquipmentStatus] = mapped_column(_enum(EquipmentStatus), nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    user: Mapped[User] = relationship(lazy="joined")
