"""ORM -> response model conversion."""

from __future__ import annotations

from datetime import datetime

from app.api.schemas import BookingOut, FaultOut, MaintenanceOut, StatusChangeOut
from app.domain.maintenance import is_overdue
from app.repositories.models import Booking, Fault, MaintenanceTask, StatusChange


def booking_out(b: Booking, show_identity: bool = True) -> BookingOut:
    """REQ-BOOK-15: identity and purpose masked when show_identity is False."""
    return BookingOut(
        id=b.id,
        equipment_id=b.equipment.equipment_id,
        user_id=b.user_id if show_identity else None,
        start=b.start,
        end=b.end,
        purpose=b.purpose if show_identity else None,
        status=b.status,
        created_at=b.created_at if show_identity else None,
        cancelled_at=b.cancelled_at if show_identity else None,
        cancelled_by=b.cancelled_by if show_identity else None,
        cancel_reason=b.cancel_reason if show_identity else None,
    )


def fault_out(f: Fault) -> FaultOut:
    return FaultOut(
        id=f.id,
        equipment_id=f.equipment.equipment_id,
        title=f.title,
        description=f.description,
        severity=f.severity,
        status=f.status,
        reported_by=f.reported_by,
        reported_at=f.reported_at,
        resolution_notes=f.resolution_notes,
        resolved_by=f.resolved_by,
        resolved_at=f.resolved_at,
    )


def maintenance_out(t: MaintenanceTask, now: datetime) -> MaintenanceOut:
    """REQ-MAINT-08: is_overdue computed against the injected clock."""
    return MaintenanceOut(
        id=t.id,
        equipment_id=t.equipment.equipment_id,
        title=t.title,
        description=t.description,
        due_date=t.due_date,
        assigned_technician_id=t.assigned_technician_id,
        status=t.status,
        is_overdue=is_overdue(t.status, t.due_date, now),
        created_by=t.created_by,
        created_at=t.created_at,
        started_at=t.started_at,
        completed_at=t.completed_at,
        completed_by=t.completed_by,
        completion_notes=t.completion_notes,
    )


def status_change_out(c: StatusChange) -> StatusChangeOut:
    return StatusChangeOut(
        from_status=c.from_status,
        to_status=c.to_status,
        event=c.event,
        user_id=c.user_id,
        reason=c.reason,
        changed_at=c.changed_at,
    )
