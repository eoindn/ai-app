"""D2, D3: atomicity under a failure partway through. D4: audit trail. Issue #3."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

import app.repositories.bookings as bookings_repo
from app.clock import FixedClock
from app.db import Base
from app.domain.enums import BookingStatus, EquipmentStatus, MaintenanceStatus
from app.repositories.models import Booking, Equipment, MaintenanceTask, User
from tests.conftest import ACTORS, NOW, TEST_PASSWORD

pytestmark = pytest.mark.integrity


def snapshot(app: FastAPI) -> dict[str, list[tuple[Any, ...]]]:
    with app.state.engine.connect() as conn:
        return {
            t.name: sorted(tuple(r) for r in conn.execute(t.select()))
            for t in Base.metadata.sorted_tables
            if t.name != "user_sessions"
        }


def add_equipment(db: Session, code: str, status: EquipmentStatus) -> Equipment:
    e = Equipment(
        equipment_id=code,
        name=f"Item {code}",
        location="Test Lab",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(e)
    db.flush()
    return e


def add_booking(db: Session, eq: Equipment, user: User, start_in: timedelta) -> Booking:
    b = Booking(
        equipment_pk=eq.id,
        user_id=user.id,
        start=NOW + start_in,
        end=NOW + start_in + timedelta(hours=1),
        purpose="Seeded booking",
        status=BookingStatus.CONFIRMED,
        created_at=NOW,
    )
    db.add(b)
    db.flush()
    return b


def add_task(
    db: Session, eq: Equipment, users: dict[str, User], status: MaintenanceStatus
) -> MaintenanceTask:
    t = MaintenanceTask(
        equipment_pk=eq.id,
        title="Seeded task",
        due_date=NOW.date(),
        assigned_technician_id=users["technician"].id,
        status=status,
        created_by=users["admin"].id,
        created_at=NOW,
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def tech(app: FastAPI, users: dict[str, User]) -> Iterator[TestClient]:
    """Technician client that returns 500 responses instead of raising."""
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/auth/login", json={"username": ACTORS["technician"][0], "password": TEST_PASSWORD})
        assert r.status_code == 200
        yield c


class InjectedFailure(RuntimeError):
    pass


# D2: REQ-DATA-05, REQ-STAT-06


def test_out_of_service_is_all_or_nothing(
    app: FastAPI, db: Session, users: dict[str, User], tech: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    eq = add_equipment(db, "EQ-00001", EquipmentStatus.AVAILABLE)
    for hours in (24, 48, 72):
        add_booking(db, eq, users["academic"], timedelta(hours=hours))
    db.commit()
    before = snapshot(app)

    real = bookings_repo.confirmed_ending_after

    def fail_after_first(*args: Any, **kwargs: Any) -> Iterator[Booking]:
        rows = real(*args, **kwargs)
        yield rows[0]
        raise InjectedFailure("crash after cancelling the first booking")

    monkeypatch.setattr(bookings_repo, "confirmed_ending_after", fail_after_first)
    resp = tech.post(
        "/api/equipment/EQ-00001/status",
        json={"event": "take_out_of_service", "reason": "Injected failure test"},
    )

    assert resp.status_code == 500
    assert snapshot(app) == before, "partial out of service change was saved"


def test_out_of_service_control_run_saves_everything(
    app: FastAPI, db: Session, users: dict[str, User], tech: TestClient
) -> None:
    """Without the injected failure the same request commits every change, so D2 is a fair test."""
    eq = add_equipment(db, "EQ-00001", EquipmentStatus.AVAILABLE)
    for hours in (24, 48, 72):
        add_booking(db, eq, users["academic"], timedelta(hours=hours))
    db.commit()

    resp = tech.post(
        "/api/equipment/EQ-00001/status", json={"event": "take_out_of_service", "reason": "Control run"}
    )

    assert resp.status_code == 200
    after = snapshot(app)
    assert len(after["status_changes"]) == 1
    assert all(row[6] == BookingStatus.CANCELLED.value for row in after["bookings"])


# D3: REQ-DATA-05, REQ-MAINT-05, REQ-MAINT-06


@pytest.mark.parametrize(
    ("op", "equipment_status", "task_status"),
    [
        ("start", EquipmentStatus.AVAILABLE, MaintenanceStatus.SCHEDULED),
        ("complete", EquipmentStatus.UNDER_MAINTENANCE, MaintenanceStatus.IN_PROGRESS),
    ],
)
def test_maintenance_change_is_all_or_nothing(
    op: str,
    equipment_status: EquipmentStatus,
    task_status: MaintenanceStatus,
    app: FastAPI,
    db: Session,
    users: dict[str, User],
    tech: TestClient,
) -> None:
    task = add_task(db, add_equipment(db, "EQ-00001", equipment_status), users, task_status)
    db.commit()
    before = snapshot(app)

    def fail_on_task_update(*args: Any) -> None:
        raise InjectedFailure("crash after equipment status changed, before task update")

    sa_event.listen(MaintenanceTask.status, "set", fail_on_task_update)
    try:
        resp = tech.post(f"/api/maintenance/{task.id}/{op}")
    finally:
        sa_event.remove(MaintenanceTask.status, "set", fail_on_task_update)

    assert resp.status_code == 500
    assert snapshot(app) == before, f"partial maintenance {op} was saved"


# D4: REQ-STAT-07, REQ-DATA-07


def test_every_transition_is_recorded_once(
    app: FastAPI,
    db: Session,
    users: dict[str, User],
    clock: FixedClock,
    client_as: Callable[[str], TestClient],
    log_lines: list[dict[str, object]],
) -> None:
    eq = add_equipment(db, "EQ-00001", EquipmentStatus.AVAILABLE)
    booking = add_booking(db, eq, users["academic"], timedelta(0))
    task = add_task(db, eq, users, MaintenanceStatus.SCHEDULED)
    db.commit()
    tech, admin = client_as("technician"), client_as("admin")

    steps = [
        (
            tech,
            "/api/equipment/EQ-00001/status",
            {"event": "check_out", "booking_id": booking.id},
            "check_out",
            "AVAILABLE",
            "BOOKED",
        ),
        (tech, "/api/equipment/EQ-00001/status", {"event": "return"}, "return", "BOOKED", "AVAILABLE"),
        (
            tech,
            f"/api/maintenance/{task.id}/start",
            None,
            "start_maintenance",
            "AVAILABLE",
            "UNDER_MAINTENANCE",
        ),
        (
            tech,
            f"/api/maintenance/{task.id}/complete",
            None,
            "complete_maintenance",
            "UNDER_MAINTENANCE",
            "AVAILABLE",
        ),
        (
            tech,
            "/api/equipment/EQ-00001/status",
            {"event": "take_out_of_service", "reason": "Audit test"},
            "take_out_of_service",
            "AVAILABLE",
            "OUT_OF_SERVICE",
        ),
        (
            admin,
            "/api/equipment/EQ-00001/status",
            {"event": "return_to_service"},
            "return_to_service",
            "OUT_OF_SERVICE",
            "AVAILABLE",
        ),
    ]
    for client, path, body, *_ in steps:
        clock.advance(timedelta(minutes=1))
        assert client.post(path, json=body).status_code == 200, path

    history = admin.get("/api/equipment/EQ-00001/history").json()
    assert [(h["event"], h["from_status"], h["to_status"]) for h in history] == [
        (event, frm, to) for *_, event, frm, to in reversed(steps)
    ], "history must list every transition once, newest first"
    assert history[0]["user_id"] == users["admin"].id
    assert history[-1]["user_id"] == users["technician"].id

    logged = [
        (line["status_event"], line["from_status"], line["to_status"])
        for line in log_lines
        if line["event"] == "status_transition"
    ]
    assert logged == [(event, frm, to) for *_, event, frm, to in steps]
    assert all(
        line["equipment_id"] == "EQ-00001" for line in log_lines if line["event"] == "status_transition"
    )


def test_rejected_changes_leave_no_history_but_are_logged(
    app: FastAPI,
    db: Session,
    users: dict[str, User],
    client_as: Callable[[str], TestClient],
    log_lines: list[dict[str, object]],
) -> None:
    eq = add_equipment(db, "EQ-00001", EquipmentStatus.AVAILABLE)
    add_booking(db, eq, users["academic"], timedelta(days=1))
    db.commit()
    tech, academic = client_as("technician"), client_as("academic")

    denied = academic.post(
        "/api/equipment/EQ-00001/status", json={"event": "take_out_of_service", "reason": "Not allowed"}
    )
    illegal = tech.post("/api/equipment/EQ-00001/status", json={"event": "return"})
    clash = academic.post(
        "/api/bookings",
        json={
            "equipment_id": "EQ-00001",
            "start": (NOW + timedelta(days=1)).isoformat(),
            "end": (NOW + timedelta(days=1, hours=1)).isoformat(),
            "purpose": "Clashing booking",
        },
    )

    assert (denied.status_code, illegal.status_code, clash.status_code) == (403, 409, 409)
    assert snapshot(app)["status_changes"] == []
    events = [line["event"] for line in log_lines]
    assert "permission_denied" in events
    assert "booking_conflict" in events
    assert "status_transition" not in events
