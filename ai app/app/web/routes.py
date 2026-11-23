"""Server-rendered HTML UI. Uses the same services and validation models as the JSON API."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from app.api.deps import SESSION_COOKIE, ClockDep, DbDep, OptionalActorDep
from app.api.errors import STATUS_FOR
from app.api.routes import set_session_cookie
from app.api.schemas import (
    EquipmentCreateIn,
    EquipmentUpdateIn,
    FaultCreateIn,
    FaultResolveIn,
    LoginIn,
    MaintenanceCreateIn,
    StatusChangeIn,
    UserCreateIn,
)
from app.domain import status as status_rules
from app.domain.enums import (
    EquipmentStatus,
    FaultSeverity,
    FaultStatus,
    Role,
    StatusEvent,
)
from app.domain.errors import DomainError, Forbidden, NotAuthenticated, ValidationFailed
from app.domain.maintenance import is_overdue
from app.domain.permissions import Action, can
from app.domain.timeutil import LAB_TZ, local_date, local_naive_to_utc
from app.logging import log_event
from app.services import auth as auth_service
from app.services import bookings as booking_service
from app.services import equipment as equipment_service
from app.services import faults as fault_service
from app.services import maintenance as maintenance_service
from app.services import reports as report_service
from app.services import users as user_service
from app.services.context import Actor

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Success messages are looked up by key so nothing user-supplied is reflected from the URL.
MESSAGES = {
    "equipment_created": "Equipment created.",
    "equipment_updated": "Equipment updated.",
    "equipment_deleted": "Equipment deleted.",
    "status_changed": "Equipment status updated.",
    "booking_created": "Booking confirmed.",
    "booking_cancelled": "Booking cancelled.",
    "fault_reported": "Fault reported.",
    "fault_updated": "Fault updated.",
    "maintenance_scheduled": "Maintenance task scheduled.",
    "maintenance_updated": "Maintenance task updated.",
    "user_created": "User created.",
}

EVENT_LABELS = {
    StatusEvent.CHECK_OUT: "Check out (active booking)",
    StatusEvent.RETURN: "Return",
    StatusEvent.TAKE_OUT_OF_SERVICE: "Take out of service",
    StatusEvent.RETURN_TO_SERVICE: "Return to service",
}


def fmt_dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(LAB_TZ).strftime("%d %b %Y %H:%M")


templates.env.filters["dt"] = fmt_dt


def render_error(request: Request, exc: DomainError, actor: Actor | None = None) -> HTMLResponse:
    """Used by the global handler for HTML routes (403/404/409 raised outside a form handler)."""
    return render(request, "error.html", actor, status_code=status_for(exc), errors=errors_from(exc))


def _require_login(actor: Actor | None) -> Actor:
    if actor is None:
        raise NotAuthenticated("Login required")
    return actor


def render(
    request: Request, name: str, actor: Actor | None, status_code: int = 200, **ctx: Any
) -> HTMLResponse:
    ok_key = request.query_params.get("ok")
    context: dict[str, Any] = {
        "actor": actor,
        "can": (lambda action: actor is not None and can(actor.role, Action(action))),
        "message": MESSAGES.get(ok_key or ""),
        "errors": [],
        "form": {},
        **ctx,
    }
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(url: str, ok: str | None = None) -> RedirectResponse:
    if ok:
        url = f"{url}{'&' if '?' in url else '?'}ok={ok}"
    return RedirectResponse(url, status_code=303)


def errors_from(exc: Exception) -> list[dict[str, str]]:
    if isinstance(exc, ValidationError):
        out = []
        for err in exc.errors():
            ctx = err.get("ctx") or {}
            field = (
                str(ctx["field"])
                if err.get("type") == "dependent_field" and "field" in ctx
                else ".".join(str(p) for p in err["loc"]) or "form"
            )
            out.append({"field": field, "message": err["msg"]})
        return out
    if isinstance(exc, ValidationFailed):
        return [{"field": exc.field, "message": exc.message}]
    if isinstance(exc, DomainError):
        if isinstance(exc, Forbidden):
            log_event("permission_denied", logging.WARNING, reason=exc.message)
        return [{"field": "form", "message": exc.message}]
    raise exc


def status_for(exc: Exception) -> int:
    if isinstance(exc, ValidationError):
        return 422
    return STATUS_FOR.get(type(exc), 400) if isinstance(exc, DomainError) else 400


def parse(model: type[BaseModel], data: dict[str, Any]) -> Any:
    """Blank optional form fields become None; validation identical to the API."""
    cleaned = {k: (v if v != "" else None) for k, v in data.items()}
    return model.model_validate({k: v for k, v in cleaned.items() if v is not None})


async def form_dict(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: str(v) for k, v in form.items()}


def parse_local(value: str, field: str) -> datetime:
    try:
        return local_naive_to_utc(datetime.fromisoformat(value))
    except (ValueError, TypeError) as exc:
        raise ValidationFailed(field, "Enter a valid date and time") from exc


# ---------------- auth ----------------


@router.get("/login")
def login_page(request: Request, actor: OptionalActorDep) -> Response:
    if actor is not None:
        return redirect("/")
    return render(request, "login.html", None)


@router.post("/login")
async def login_submit(request: Request, db: DbDep, clock: ClockDep) -> Response:
    data = await form_dict(request)
    try:
        body = LoginIn.model_validate(data)
        _, token = auth_service.login(
            db, clock, body.username, body.password, request.app.state.settings.session_hours
        )
    except (ValidationError, DomainError):
        return render(
            request,
            "login.html",
            None,
            status_code=401,
            errors=[{"field": "form", "message": "Invalid username or password"}],
            form={"username": data.get("username", "")},
        )
    response = redirect("/")
    set_session_cookie(request, response, token)
    return response


@router.post("/logout")
def logout_submit(request: Request, db: DbDep) -> Response:
    auth_service.logout(db, request.cookies.get(SESSION_COOKIE))
    response = redirect("/login")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# ---------------- dashboard ----------------


@router.get("/")
def dashboard(request: Request, actor: OptionalActorDep, db: DbDep, clock: ClockDep) -> Response:
    actor = _require_login(actor)
    ctx: dict[str, Any] = {}
    now = clock.now()
    if can(actor.role, Action.REPORT_VIEW):
        ctx["availability"] = report_service.availability(db, actor)
        ctx["faults"] = report_service.outstanding_faults(db, actor)
        ctx["maintenance"] = report_service.maintenance_summary(db, clock, actor)
    ctx["my_bookings"] = [
        b
        for b in booking_service.list_bookings(db, actor, "mine")
        if b.end > now and b.status.value == "CONFIRMED"
    ]
    return render(request, "dashboard.html", actor, **ctx)


# ---------------- equipment ----------------


@router.get("/equipment")
def equipment_list(
    request: Request,
    actor: OptionalActorDep,
    db: DbDep,
    q: str = "",
    status: str = "",
    page: int = 1,
) -> Response:
    actor = _require_login(actor)
    per_page = 20
    page = max(page, 1)
    errors: list[dict[str, str]] = []
    status_filter: EquipmentStatus | None = None
    if status:
        try:
            status_filter = EquipmentStatus(status)
        except ValueError:
            errors.append({"field": "status", "message": "Unknown status"})
    total, items = equipment_service.search(
        db, actor, q.strip()[:100] or None, status_filter, per_page, (page - 1) * per_page
    )
    return render(
        request,
        "equipment_list.html",
        actor,
        items=items,
        total=total,
        q=q,
        status=status,
        page=page,
        pages=max(1, -(-total // per_page)),
        statuses=list(EquipmentStatus),
        errors=errors,
    )


@router.get("/equipment/new")
def equipment_new(request: Request, actor: OptionalActorDep) -> Response:
    actor = _require_login(actor)
    if not can(actor.role, Action.EQUIPMENT_CREATE):
        raise Forbidden("Only admins can create equipment")
    return render(request, "equipment_form.html", actor, mode="create")


@router.post("/equipment/new")
async def equipment_create(request: Request, actor: OptionalActorDep, db: DbDep, clock: ClockDep) -> Response:
    actor = _require_login(actor)
    data = await form_dict(request)
    try:
        body = parse(EquipmentCreateIn, data)
        e = equipment_service.create(
            db, clock, actor, body.equipment_id, body.name, body.location, body.description
        )
    except (ValidationError, DomainError) as exc:
        return render(
            request,
            "equipment_form.html",
            actor,
            status_code=status_for(exc),
            mode="create",
            errors=errors_from(exc),
            form=data,
        )
    return redirect(f"/equipment/{e.equipment_id}", "equipment_created")


def _detail_context(db: Any, clock: Any, actor: Actor, equipment_id: str) -> dict[str, Any]:
    equipment = equipment_service.get_equipment(db, actor, equipment_id)
    schedule = booking_service.equipment_schedule(db, clock, actor, equipment_id)
    faults = fault_service.list_faults(db, actor, equipment_id=equipment_id)
    ctx: dict[str, Any] = {
        "e": equipment,
        "schedule": schedule,
        "faults": faults,
        "events": [
            (ev, EVENT_LABELS[ev])
            for ev in status_rules.allowed_events(equipment.status, actor.role)
            if ev not in status_rules.MAINTENANCE_ONLY_EVENTS
        ],
        "severities": list(FaultSeverity),
        "history": [],
        "tasks": [],
    }
    if can(actor.role, Action.EQUIPMENT_VIEW_HISTORY):
        ctx["history"] = equipment_service.history(db, actor, equipment_id)[:20]
    if can(actor.role, Action.MAINT_VIEW):
        ctx["tasks"] = maintenance_service.list_tasks(db, clock, actor, equipment_id=equipment_id)
    return ctx


@router.get("/equipment/{equipment_id}")
def equipment_detail(
    request: Request, equipment_id: str, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor = _require_login(actor)
    try:
        ctx = _detail_context(db, clock, actor, equipment_id)
    except DomainError as exc:
        return render(request, "error.html", actor, status_code=status_for(exc), errors=errors_from(exc))
    return render(request, "equipment_detail.html", actor, **ctx)


async def _detail_action(
    request: Request,
    actor: Actor,
    db: Any,
    clock: Any,
    equipment_id: str,
    action: Any,
    ok: str,
    form_name: str,
) -> Response:
    data = await form_dict(request)
    try:
        action(data)
    except (ValidationError, DomainError) as exc:
        try:
            ctx = _detail_context(db, clock, actor, equipment_id)
        except DomainError as inner:
            return render(
                request, "error.html", actor, status_code=status_for(inner), errors=errors_from(inner)
            )
        return render(
            request,
            "equipment_detail.html",
            actor,
            status_code=status_for(exc),
            errors=errors_from(exc),
            form=data,
            form_name=form_name,
            **ctx,
        )
    return redirect(f"/equipment/{equipment_id}", ok)


@router.post("/equipment/{equipment_id}/status")
async def equipment_status(
    request: Request, equipment_id: str, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor_ = _require_login(actor)

    def act(data: dict[str, str]) -> None:
        body = parse(StatusChangeIn, data)
        equipment_service.change_status(
            db, clock, actor_, equipment_id, body.event, body.booking_id, body.reason
        )

    return await _detail_action(request, actor_, db, clock, equipment_id, act, "status_changed", "status")


@router.post("/equipment/{equipment_id}/book")
async def equipment_book(
    request: Request, equipment_id: str, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor_ = _require_login(actor)

    def act(data: dict[str, str]) -> None:
        start = parse_local(data.get("start", ""), "start")
        end = parse_local(data.get("end", ""), "end")
        purpose = data.get("purpose", "").strip()
        if not 3 <= len(purpose) <= 200:
            raise ValidationFailed("purpose", "Purpose must be 3-200 characters")
        booking_service.create(db, clock, actor_, equipment_id, start, end, purpose)

    return await _detail_action(request, actor_, db, clock, equipment_id, act, "booking_created", "book")


@router.post("/equipment/{equipment_id}/fault")
async def equipment_fault(
    request: Request, equipment_id: str, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor_ = _require_login(actor)

    def act(data: dict[str, str]) -> None:
        body = parse(FaultCreateIn, {**data, "equipment_id": equipment_id})
        fault_service.report(db, clock, actor_, equipment_id, body.title, body.description, body.severity)

    return await _detail_action(request, actor_, db, clock, equipment_id, act, "fault_reported", "fault")


@router.get("/equipment/{equipment_id}/edit")
def equipment_edit(request: Request, equipment_id: str, actor: OptionalActorDep, db: DbDep) -> Response:
    actor = _require_login(actor)
    if not can(actor.role, Action.EQUIPMENT_UPDATE):
        raise Forbidden("Only admins can edit equipment")
    e = equipment_service.get_equipment(db, actor, equipment_id)
    form = {"name": e.name, "location": e.location, "description": e.description or ""}
    return render(request, "equipment_form.html", actor, mode="edit", e=e, form=form)


@router.post("/equipment/{equipment_id}/edit")
async def equipment_update(
    request: Request, equipment_id: str, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor = _require_login(actor)
    data = await form_dict(request)
    try:
        body = EquipmentUpdateIn.model_validate(
            {k: data.get(k, "") for k in ("name", "location", "description")}
        )
        equipment_service.update(db, clock, actor, equipment_id, body.model_dump(exclude_unset=True))
    except (ValidationError, DomainError) as exc:
        e = equipment_service.get_equipment(db, actor, equipment_id)
        return render(
            request,
            "equipment_form.html",
            actor,
            status_code=status_for(exc),
            mode="edit",
            e=e,
            errors=errors_from(exc),
            form=data,
        )
    return redirect(f"/equipment/{equipment_id}", "equipment_updated")


@router.post("/equipment/{equipment_id}/delete")
def equipment_delete(
    request: Request, equipment_id: str, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor = _require_login(actor)
    try:
        equipment_service.delete(db, actor, equipment_id)
    except DomainError as exc:
        ctx = _detail_context(db, clock, actor, equipment_id)
        return render(
            request,
            "equipment_detail.html",
            actor,
            status_code=status_for(exc),
            errors=errors_from(exc),
            **ctx,
        )
    return redirect("/equipment", "equipment_deleted")


# ---------------- bookings ----------------


@router.get("/bookings")
def bookings_page(
    request: Request, actor: OptionalActorDep, db: DbDep, clock: ClockDep, scope: str = "mine"
) -> Response:
    actor = _require_login(actor)
    if scope == "all" and not can(actor.role, Action.BOOKING_VIEW_ALL):
        scope = "mine"
    bookings = booking_service.list_bookings(db, actor, "all" if scope == "all" else "mine")
    return render(request, "bookings.html", actor, bookings=bookings, scope=scope, now=clock.now())


@router.post("/bookings/{booking_id}/cancel")
def booking_cancel(
    request: Request, booking_id: int, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor = _require_login(actor)
    scope = request.query_params.get("scope", "mine")
    try:
        booking_service.cancel(db, clock, actor, booking_id)
    except DomainError as exc:
        bookings = booking_service.list_bookings(
            db, actor, "all" if scope == "all" and can(actor.role, Action.BOOKING_VIEW_ALL) else "mine"
        )
        return render(
            request,
            "bookings.html",
            actor,
            status_code=status_for(exc),
            bookings=bookings,
            scope=scope,
            now=clock.now(),
            errors=errors_from(exc),
        )
    return redirect(f"/bookings?scope={'all' if scope == 'all' else 'mine'}", "booking_cancelled")


# ---------------- faults ----------------


@router.get("/faults")
def faults_page(request: Request, actor: OptionalActorDep, db: DbDep, status: str = "") -> Response:
    actor = _require_login(actor)
    status_filter = FaultStatus(status) if status in {s.value for s in FaultStatus} else None
    faults = fault_service.list_faults(db, actor, status=status_filter)
    return render(request, "faults.html", actor, faults=faults, status=status, statuses=list(FaultStatus))


@router.post("/faults/{fault_id}/start")
def fault_start(request: Request, fault_id: int, actor: OptionalActorDep, db: DbDep) -> Response:
    actor = _require_login(actor)
    try:
        fault_service.start(db, actor, fault_id)
    except DomainError as exc:
        faults = fault_service.list_faults(db, actor)
        return render(
            request,
            "faults.html",
            actor,
            status_code=status_for(exc),
            faults=faults,
            status="",
            statuses=list(FaultStatus),
            errors=errors_from(exc),
        )
    return redirect("/faults", "fault_updated")


@router.post("/faults/{fault_id}/resolve")
async def fault_resolve(
    request: Request, fault_id: int, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor = _require_login(actor)
    data = await form_dict(request)
    try:
        body = FaultResolveIn.model_validate(data)
        fault_service.resolve(db, clock, actor, fault_id, body.resolution_notes)
    except (ValidationError, DomainError) as exc:
        faults = fault_service.list_faults(db, actor)
        return render(
            request,
            "faults.html",
            actor,
            status_code=status_for(exc),
            faults=faults,
            status="",
            statuses=list(FaultStatus),
            errors=errors_from(exc),
            form=data,
            form_fault_id=fault_id,
        )
    return redirect("/faults", "fault_updated")


# ---------------- maintenance ----------------


def _maintenance_ctx(db: Any, clock: Any, actor: Actor, overdue_only: bool = False) -> dict[str, Any]:
    now = clock.now()
    tasks = maintenance_service.list_tasks(db, clock, actor, overdue=True if overdue_only else None)
    ctx: dict[str, Any] = {
        "tasks": [(t, is_overdue(t.status, t.due_date, now)) for t in tasks],
        "overdue_only": overdue_only,
        "today": local_date(now).isoformat(),
        "technicians": [],
        "equipment": [],
    }
    if can(actor.role, Action.MAINT_ASSIGN):
        ctx["technicians"] = user_service.list_technicians(db)
        ctx["equipment"] = equipment_service.search(db, actor, None, None, 100, 0)[1]
    return ctx


@router.get("/maintenance")
def maintenance_page(
    request: Request, actor: OptionalActorDep, db: DbDep, clock: ClockDep, overdue: str = ""
) -> Response:
    actor = _require_login(actor)
    if not can(actor.role, Action.MAINT_VIEW):
        raise Forbidden("Maintenance is visible to admins and technicians only")
    return render(request, "maintenance.html", actor, **_maintenance_ctx(db, clock, actor, overdue == "1"))


async def _maintenance_action(request: Request, actor: Actor, db: Any, clock: Any, action: Any) -> Response:
    data = await form_dict(request)
    try:
        action(data)
    except (ValidationError, DomainError) as exc:
        return render(
            request,
            "maintenance.html",
            actor,
            status_code=status_for(exc),
            errors=errors_from(exc),
            form=data,
            **_maintenance_ctx(db, clock, actor),
        )
    return redirect("/maintenance", "maintenance_updated")


@router.post("/maintenance/new")
async def maintenance_create(
    request: Request, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor_ = _require_login(actor)

    def act(data: dict[str, str]) -> None:
        body = parse(MaintenanceCreateIn, data)
        maintenance_service.schedule(
            db,
            clock,
            actor_,
            body.equipment_id,
            body.title,
            body.description,
            body.due_date,
            body.assigned_technician_id,
        )

    return await _maintenance_action(request, actor_, db, clock, act)


@router.post("/maintenance/{task_id}/{op}")
async def maintenance_op(
    request: Request, task_id: int, op: str, actor: OptionalActorDep, db: DbDep, clock: ClockDep
) -> Response:
    actor_ = _require_login(actor)

    def act(data: dict[str, str]) -> None:
        if op == "start":
            maintenance_service.start(db, clock, actor_, task_id)
        elif op == "complete":
            notes = data.get("completion_notes", "").strip()
            if len(notes) > 1000:
                raise ValidationFailed("completion_notes", "Notes must be at most 1000 characters")
            maintenance_service.complete(db, clock, actor_, task_id, notes or None)
        elif op == "cancel":
            maintenance_service.cancel(db, actor_, task_id)
        elif op == "assign":
            try:
                tech_id = int(data.get("assigned_technician_id", ""))
            except ValueError as exc:
                raise ValidationFailed("assigned_technician_id", "Choose a technician") from exc
            maintenance_service.assign(db, actor_, task_id, tech_id)
        else:
            raise ValidationFailed("op", "Unknown operation")

    return await _maintenance_action(request, actor_, db, clock, act)


# ---------------- users ----------------


@router.get("/users")
def users_page(request: Request, actor: OptionalActorDep, db: DbDep) -> Response:
    actor = _require_login(actor)
    return render(request, "users.html", actor, users=user_service.list_users(db, actor), roles=list(Role))


@router.post("/users")
async def users_create(request: Request, actor: OptionalActorDep, db: DbDep) -> Response:
    actor = _require_login(actor)
    data = await form_dict(request)
    try:
        body = UserCreateIn.model_validate(data)
        user_service.create_user(db, actor, body.username, body.display_name, body.role, body.password)
    except (ValidationError, DomainError) as exc:
        users = user_service.list_users(db, actor)
        safe_form = {k: v for k, v in data.items() if k != "password"}
        return render(
            request,
            "users.html",
            actor,
            status_code=status_for(exc),
            users=users,
            roles=list(Role),
            errors=errors_from(exc),
            form=safe_form,
        )
    return redirect("/users", "user_created")
