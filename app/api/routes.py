"""JSON REST API under /api. Thin: parse input, call a service, map output."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api import mappers
from app.api.deps import SESSION_COOKIE, ActorDep, ClockDep, DbDep
from app.api.schemas import (
    AvailabilityOut,
    BookingCreateIn,
    BookingOut,
    EquipmentCreateIn,
    EquipmentOut,
    EquipmentPage,
    EquipmentUpdateIn,
    FaultCreateIn,
    FaultOut,
    FaultReportOut,
    FaultResolveIn,
    LoginIn,
    MaintenanceAssignIn,
    MaintenanceCompleteIn,
    MaintenanceCreateIn,
    MaintenanceOut,
    MaintenanceReportOut,
    StatusChangeIn,
    StatusChangeOut,
    UserCreateIn,
    UserOut,
)
from app.domain.enums import EquipmentStatus, FaultSeverity, FaultStatus, MaintenanceStatus, Role
from app.services import auth as auth_service
from app.services import bookings as booking_service
from app.services import equipment as equipment_service
from app.services import faults as fault_service
from app.services import maintenance as maintenance_service
from app.services import reports as report_service
from app.services import users as user_service

router = APIRouter(prefix="/api")


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    """REQ-ROLE-07."""
    settings = request.app.state.settings
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )


# ---------------- auth ----------------


@router.post("/auth/login", response_model=UserOut)
def login(body: LoginIn, request: Request, db: DbDep, clock: ClockDep) -> Response:
    """REQ-ROLE-02."""
    user, token = auth_service.login(
        db, clock, body.username, body.password, request.app.state.settings.session_hours
    )
    response = JSONResponse(UserOut.model_validate(user).model_dump(mode="json"))
    set_session_cookie(request, response, token)
    return response


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: DbDep) -> Response:
    """REQ-ROLE-03."""
    auth_service.logout(db, request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/auth/me", response_model=UserOut)
def me(actor: ActorDep) -> UserOut:
    """REQ-ROLE-03."""
    return UserOut(id=actor.id, username=actor.username, display_name=actor.display_name, role=actor.role)


# ---------------- users ----------------


@router.get("/users", response_model=list[UserOut])
def list_users(actor: ActorDep, db: DbDep, role: Role | None = None) -> list[UserOut]:
    """REQ-ROLE-06."""
    return [UserOut.model_validate(u) for u in user_service.list_users(db, actor, role)]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreateIn, actor: ActorDep, db: DbDep) -> UserOut:
    """REQ-ROLE-06."""
    user = user_service.create_user(db, actor, body.username, body.display_name, body.role, body.password)
    return UserOut.model_validate(user)


# ---------------- equipment ----------------


@router.get("/equipment", response_model=EquipmentPage)
def search_equipment(
    actor: ActorDep,
    db: DbDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: EquipmentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EquipmentPage:
    """REQ-INV-07, REQ-INV-08."""
    total, items = equipment_service.search(db, actor, q.strip() if q else None, status, limit, offset)
    return EquipmentPage(total=total, items=[EquipmentOut.model_validate(e) for e in items])


@router.post("/equipment", response_model=EquipmentOut, status_code=201)
def create_equipment(body: EquipmentCreateIn, actor: ActorDep, db: DbDep, clock: ClockDep) -> EquipmentOut:
    """REQ-INV-01..03."""
    equipment = equipment_service.create(
        db, clock, actor, body.equipment_id, body.name, body.location, body.description
    )
    return EquipmentOut.model_validate(equipment)


@router.get("/equipment/{equipment_id}", response_model=EquipmentOut)
def get_equipment(equipment_id: str, actor: ActorDep, db: DbDep) -> EquipmentOut:
    """REQ-INV-04."""
    return EquipmentOut.model_validate(equipment_service.get_equipment(db, actor, equipment_id))


@router.patch("/equipment/{equipment_id}", response_model=EquipmentOut)
def update_equipment(
    equipment_id: str, body: EquipmentUpdateIn, actor: ActorDep, db: DbDep, clock: ClockDep
) -> EquipmentOut:
    """REQ-INV-05."""
    changes = body.model_dump(exclude_unset=True)
    return EquipmentOut.model_validate(equipment_service.update(db, clock, actor, equipment_id, changes))


@router.delete("/equipment/{equipment_id}", status_code=204)
def delete_equipment(equipment_id: str, actor: ActorDep, db: DbDep) -> Response:
    """REQ-INV-06."""
    equipment_service.delete(db, actor, equipment_id)
    return Response(status_code=204)


@router.post("/equipment/{equipment_id}/status", response_model=EquipmentOut)
def change_status(
    equipment_id: str, body: StatusChangeIn, actor: ActorDep, db: DbDep, clock: ClockDep
) -> EquipmentOut:
    """REQ-STAT-04..06."""
    equipment = equipment_service.change_status(
        db, clock, actor, equipment_id, body.event, body.booking_id, body.reason
    )
    return EquipmentOut.model_validate(equipment)


@router.get("/equipment/{equipment_id}/history", response_model=list[StatusChangeOut])
def equipment_history(equipment_id: str, actor: ActorDep, db: DbDep) -> list[StatusChangeOut]:
    """REQ-STAT-07."""
    return [mappers.status_change_out(c) for c in equipment_service.history(db, actor, equipment_id)]


@router.get("/equipment/{equipment_id}/bookings", response_model=list[BookingOut])
def equipment_schedule(equipment_id: str, actor: ActorDep, db: DbDep, clock: ClockDep) -> list[BookingOut]:
    """REQ-BOOK-15."""
    rows = booking_service.equipment_schedule(db, clock, actor, equipment_id)
    return [mappers.booking_out(b, show) for b, show in rows]


# ---------------- bookings ----------------


@router.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking(body: BookingCreateIn, actor: ActorDep, db: DbDep, clock: ClockDep) -> BookingOut:
    """REQ-BOOK-01..10."""
    booking = booking_service.create(db, clock, actor, body.equipment_id, body.start, body.end, body.purpose)
    return mappers.booking_out(booking)


@router.get("/bookings", response_model=list[BookingOut])
def list_bookings(actor: ActorDep, db: DbDep, scope: Literal["mine", "all"] = "mine") -> list[BookingOut]:
    """REQ-BOOK-11."""
    return [mappers.booking_out(b) for b in booking_service.list_bookings(db, actor, scope)]


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, actor: ActorDep, db: DbDep) -> BookingOut:
    """REQ-BOOK-12."""
    return mappers.booking_out(booking_service.get(db, actor, booking_id))


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: int, actor: ActorDep, db: DbDep, clock: ClockDep) -> BookingOut:
    """REQ-BOOK-13, REQ-BOOK-14."""
    return mappers.booking_out(booking_service.cancel(db, clock, actor, booking_id))


# ---------------- faults ----------------


@router.post("/faults", response_model=FaultOut, status_code=201)
def report_fault(body: FaultCreateIn, actor: ActorDep, db: DbDep, clock: ClockDep) -> FaultOut:
    """REQ-FAULT-01, REQ-FAULT-02."""
    fault = fault_service.report(
        db, clock, actor, body.equipment_id, body.title, body.description, body.severity
    )
    return mappers.fault_out(fault)


@router.get("/faults", response_model=list[FaultOut])
def list_faults(
    actor: ActorDep,
    db: DbDep,
    status: FaultStatus | None = None,
    severity: FaultSeverity | None = None,
    equipment_id: str | None = None,
) -> list[FaultOut]:
    """REQ-FAULT-03."""
    return [
        mappers.fault_out(f) for f in fault_service.list_faults(db, actor, status, severity, equipment_id)
    ]


@router.get("/faults/{fault_id}", response_model=FaultOut)
def get_fault(fault_id: int, actor: ActorDep, db: DbDep) -> FaultOut:
    """REQ-FAULT-03."""
    return mappers.fault_out(fault_service.get(db, actor, fault_id))


@router.post("/faults/{fault_id}/start", response_model=FaultOut)
def start_fault(fault_id: int, actor: ActorDep, db: DbDep) -> FaultOut:
    """REQ-FAULT-04."""
    return mappers.fault_out(fault_service.start(db, actor, fault_id))


@router.post("/faults/{fault_id}/resolve", response_model=FaultOut)
def resolve_fault(
    fault_id: int, body: FaultResolveIn, actor: ActorDep, db: DbDep, clock: ClockDep
) -> FaultOut:
    """REQ-FAULT-04, REQ-FAULT-05."""
    return mappers.fault_out(fault_service.resolve(db, clock, actor, fault_id, body.resolution_notes))


# ---------------- maintenance ----------------


@router.post("/maintenance", response_model=MaintenanceOut, status_code=201)
def schedule_maintenance(
    body: MaintenanceCreateIn, actor: ActorDep, db: DbDep, clock: ClockDep
) -> MaintenanceOut:
    """REQ-MAINT-01..03."""
    task = maintenance_service.schedule(
        db,
        clock,
        actor,
        body.equipment_id,
        body.title,
        body.description,
        body.due_date,
        body.assigned_technician_id,
    )
    return mappers.maintenance_out(task, clock.now())


@router.get("/maintenance", response_model=list[MaintenanceOut])
def list_maintenance(
    actor: ActorDep,
    db: DbDep,
    clock: ClockDep,
    status: MaintenanceStatus | None = None,
    equipment_id: str | None = None,
    assigned_technician_id: int | None = None,
    overdue: bool | None = None,
) -> list[MaintenanceOut]:
    """REQ-MAINT-09."""
    tasks = maintenance_service.list_tasks(
        db, clock, actor, status, equipment_id, assigned_technician_id, overdue
    )
    now = clock.now()
    return [mappers.maintenance_out(t, now) for t in tasks]


@router.get("/maintenance/{task_id}", response_model=MaintenanceOut)
def get_maintenance(task_id: int, actor: ActorDep, db: DbDep, clock: ClockDep) -> MaintenanceOut:
    return mappers.maintenance_out(maintenance_service.get(db, actor, task_id), clock.now())


@router.post("/maintenance/{task_id}/assign", response_model=MaintenanceOut)
def assign_maintenance(
    task_id: int, body: MaintenanceAssignIn, actor: ActorDep, db: DbDep, clock: ClockDep
) -> MaintenanceOut:
    """REQ-MAINT-04."""
    task = maintenance_service.assign(db, actor, task_id, body.assigned_technician_id)
    return mappers.maintenance_out(task, clock.now())


@router.post("/maintenance/{task_id}/start", response_model=MaintenanceOut)
def start_maintenance(task_id: int, actor: ActorDep, db: DbDep, clock: ClockDep) -> MaintenanceOut:
    """REQ-MAINT-05."""
    return mappers.maintenance_out(maintenance_service.start(db, clock, actor, task_id), clock.now())


@router.post("/maintenance/{task_id}/complete", response_model=MaintenanceOut)
def complete_maintenance(
    task_id: int, actor: ActorDep, db: DbDep, clock: ClockDep, body: MaintenanceCompleteIn | None = None
) -> MaintenanceOut:
    """REQ-MAINT-06."""
    notes = body.completion_notes if body else None
    task = maintenance_service.complete(db, clock, actor, task_id, notes)
    return mappers.maintenance_out(task, clock.now())


@router.post("/maintenance/{task_id}/cancel", response_model=MaintenanceOut)
def cancel_maintenance(task_id: int, actor: ActorDep, db: DbDep, clock: ClockDep) -> MaintenanceOut:
    """REQ-MAINT-07."""
    return mappers.maintenance_out(maintenance_service.cancel(db, actor, task_id), clock.now())


# ---------------- reports ----------------


@router.get("/reports/availability", response_model=AvailabilityOut)
def availability_report(actor: ActorDep, db: DbDep) -> AvailabilityOut:
    """REQ-REP-01."""
    r = report_service.availability(db, actor)
    return AvailabilityOut(total=r.total, by_status=r.by_status)


@router.get("/reports/faults", response_model=FaultReportOut)
def fault_report(actor: ActorDep, db: DbDep) -> FaultReportOut:
    """REQ-REP-02."""
    r = report_service.outstanding_faults(db, actor)
    return FaultReportOut(
        total_outstanding=r.total_outstanding,
        by_severity=r.by_severity,
        faults=[mappers.fault_out(f) for f in r.faults],
    )


@router.get("/reports/maintenance")
def maintenance_report(
    actor: ActorDep,
    db: DbDep,
    clock: ClockDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> Response:
    """REQ-REP-03."""
    r = report_service.maintenance_summary(db, clock, actor, from_, to)
    now = clock.now()
    out = MaintenanceReportOut(
        from_date=r.from_date,
        to_date=r.to_date,
        overdue=[mappers.maintenance_out(t, now) for t in r.overdue],
        upcoming=[mappers.maintenance_out(t, now) for t in r.upcoming],
        completed_count=r.completed_count,
    )
    return JSONResponse(out.model_dump(mode="json", by_alias=True))
