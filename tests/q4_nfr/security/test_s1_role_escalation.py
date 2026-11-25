"""S1 – Role escalation / broken access control (OWASP A01). Risk: Critical. Issue #2.

Technique: decision table testing. Each row of SPEC §4 (permission matrix) is one rule; each
column is an actor. Every cell becomes one test case, so the full table is covered, including
the "own" (ownership) cells, which use a second user of the same role.

Oracle:
- ❌ cell → 403 with error code FORBIDDEN, and the database is byte-for-byte unchanged
  (a denied request must not have side effects: REQ-ROLE-05, REQ-STAT-03 "status is unchanged").
- ✅ cell → 2xx. This checks the matrix is not over-restrictive, so a blanket 403 cannot pass.

Requests carry valid bodies, so that 422 (checked before 403, SPEC §1.3) cannot mask the result.

REQ IDs: REQ-ROLE-05, REQ-ROLE-06, REQ-INV-01, REQ-INV-04..07, REQ-INV-09, REQ-STAT-03,
REQ-STAT-07, REQ-BOOK-01, REQ-BOOK-11..13, REQ-FAULT-01, REQ-FAULT-03, REQ-FAULT-04,
REQ-MAINT-01, REQ-MAINT-04, REQ-MAINT-05, REQ-MAINT-06, REQ-MAINT-07, REQ-MAINT-09, REQ-REP-01..03.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base
from app.domain.enums import (
    BookingStatus,
    EquipmentStatus,
    FaultSeverity,
    FaultStatus,
    MaintenanceStatus,
)
from app.repositories.models import Booking, Equipment, Fault, MaintenanceTask, User
from tests.conftest import ACTORS, NOW

pytestmark = pytest.mark.security

ALL = frozenset(ACTORS)
ADMIN = frozenset({"admin"})
STAFF = frozenset({"admin", "technician", "technician_other"})


# ---------------------------------------------------------------- arrange


@dataclass
class Seed:
    booking_of: dict[str, int] = field(default_factory=dict)  # actor key -> id of a booking they own
    open_fault: int = 0
    in_progress_fault: int = 0
    scheduled_task: int = 0  # assigned to "technician", equipment AVAILABLE
    in_progress_task: int = 0  # assigned to "technician", equipment UNDER_MAINTENANCE
    tech_other_id: int = 0


@pytest.fixture
def seed(db: Session, users: dict[str, User]) -> Seed:
    def eq(code: str, status: EquipmentStatus) -> Equipment:
        e = Equipment(
            equipment_id=code,
            name=f"Test item {code}",
            location="Test Lab",
            status=status,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(e)
        return e

    eq1 = eq("EQ-00001", EquipmentStatus.AVAILABLE)  # bookings + faults
    eq("EQ-00002", EquipmentStatus.AVAILABLE)  # status-change target, unreferenced
    eq("EQ-00003", EquipmentStatus.AVAILABLE)  # delete target, unreferenced
    eq("EQ-00004", EquipmentStatus.OUT_OF_SERVICE)  # return_to_service target
    eq5 = eq("EQ-00005", EquipmentStatus.AVAILABLE)  # scheduled maintenance
    eq6 = eq("EQ-00006", EquipmentStatus.UNDER_MAINTENANCE)  # in-progress maintenance
    db.flush()

    s = Seed(tech_other_id=users["technician_other"].id)
    # One future booking per actor, at non-overlapping times on EQ-00001.
    for i, (key, user) in enumerate(users.items()):
        start = NOW + timedelta(days=1, hours=i)
        b = Booking(
            equipment_pk=eq1.id,
            user_id=user.id,
            start=start,
            end=start + timedelta(hours=1),
            purpose="Seeded booking",
            status=BookingStatus.CONFIRMED,
            created_at=NOW,
        )
        db.add(b)
        db.flush()
        s.booking_of[key] = b.id

    def fault(status: FaultStatus) -> int:
        f = Fault(
            equipment_pk=eq1.id,
            title="Seeded fault",
            description="Seeded fault description",
            severity=FaultSeverity.LOW,
            status=status,
            reported_by=users["academic"].id,
            reported_at=NOW,
        )
        db.add(f)
        db.flush()
        return f.id

    s.open_fault = fault(FaultStatus.OPEN)
    s.in_progress_fault = fault(FaultStatus.IN_PROGRESS)

    def task(equipment: Equipment, status: MaintenanceStatus) -> int:
        t = MaintenanceTask(
            equipment_pk=equipment.id,
            title="Seeded task",
            due_date=NOW.date(),
            assigned_technician_id=users["technician"].id,
            status=status,
            created_by=users["admin"].id,
            created_at=NOW,
        )
        db.add(t)
        db.flush()
        return t.id

    s.scheduled_task = task(eq5, MaintenanceStatus.SCHEDULED)
    s.in_progress_task = task(eq6, MaintenanceStatus.IN_PROGRESS)
    db.commit()
    return s


# ---------------------------------------------------------------- decision table (SPEC §4)


@dataclass(frozen=True)
class Rule:
    action: str
    req: str
    method: str
    path: Callable[[Seed, str], str]
    allowed: frozenset[str]
    body: Callable[[Seed], dict[str, Any]] | None = None
    actors: frozenset[str] = ALL  # columns this rule applies to


def const(p: str) -> Callable[[Seed, str], str]:
    return lambda _s, _a: p


FUTURE = NOW + timedelta(days=3)

RULES: list[Rule] = [
    # Equipment
    Rule("View equipment", "REQ-INV-04", "GET", const("/api/equipment/EQ-00001"), ALL),
    Rule("Search equipment", "REQ-INV-07", "GET", const("/api/equipment?q=test"), ALL),
    Rule(
        "Create equipment",
        "REQ-INV-01/09",
        "POST",
        const("/api/equipment"),
        ADMIN,
        body=lambda s: {"equipment_id": "EQ-00099", "name": "New item", "location": "Test Lab"},
    ),
    Rule(
        "Update equipment",
        "REQ-INV-05/09",
        "PATCH",
        const("/api/equipment/EQ-00001"),
        ADMIN,
        body=lambda s: {"name": "Renamed item"},
    ),
    Rule("Delete equipment", "REQ-INV-06/09", "DELETE", const("/api/equipment/EQ-00003"), ADMIN),
    Rule(
        "Change status (take_out_of_service)",
        "REQ-STAT-03",
        "POST",
        const("/api/equipment/EQ-00002/status"),
        STAFF,
        body=lambda s: {"event": "take_out_of_service", "reason": "Security test reason"},
    ),
    Rule(
        "Return to service",
        "REQ-STAT-03",
        "POST",
        const("/api/equipment/EQ-00004/status"),
        ADMIN,
        body=lambda s: {"event": "return_to_service"},
    ),
    Rule("View status history", "REQ-STAT-07", "GET", const("/api/equipment/EQ-00001/history"), STAFF),
    # Bookings
    Rule(
        "Create booking (self)",
        "REQ-BOOK-01",
        "POST",
        const("/api/bookings"),
        ALL,
        body=lambda s: {
            "equipment_id": "EQ-00001",
            "start": FUTURE.isoformat(),
            "end": (FUTURE + timedelta(hours=1)).isoformat(),
            "purpose": "Security test",
        },
    ),
    Rule("View own bookings", "REQ-BOOK-11", "GET", const("/api/bookings?scope=mine"), ALL),
    Rule("View all bookings", "REQ-BOOK-11", "GET", const("/api/bookings?scope=all"), STAFF),
    Rule(
        "View another user's booking",
        "REQ-BOOK-12",
        "GET",
        lambda s, a: f"/api/bookings/{s.booking_of['academic']}",
        STAFF,
        actors=ALL - {"academic"},
    ),
    Rule(
        "Cancel own booking",
        "REQ-BOOK-13",
        "POST",
        lambda s, a: f"/api/bookings/{s.booking_of[a]}/cancel",
        ALL,
    ),
    Rule(
        "Cancel another user's booking",
        "REQ-BOOK-13",
        "POST",
        lambda s, a: f"/api/bookings/{s.booking_of['academic']}/cancel",
        ADMIN,
        actors=ALL - {"academic"},
    ),
    # Faults
    Rule(
        "Report fault",
        "REQ-FAULT-01",
        "POST",
        const("/api/faults"),
        ALL,
        body=lambda s: {
            "equipment_id": "EQ-00001",
            "title": "New fault",
            "description": "Reported by security test",
            "severity": "LOW",
        },
    ),
    Rule("View faults", "REQ-FAULT-03", "GET", const("/api/faults"), ALL),
    Rule("Start fault", "REQ-FAULT-04", "POST", lambda s, a: f"/api/faults/{s.open_fault}/start", STAFF),
    Rule(
        "Resolve fault",
        "REQ-FAULT-04",
        "POST",
        lambda s, a: f"/api/faults/{s.in_progress_fault}/resolve",
        STAFF,
        body=lambda s: {"resolution_notes": "Fixed during security test"},
    ),
    # Maintenance
    Rule("View maintenance tasks", "REQ-MAINT-09", "GET", const("/api/maintenance"), STAFF),
    Rule(
        "Schedule maintenance",
        "REQ-MAINT-01",
        "POST",
        const("/api/maintenance"),
        ADMIN,
        body=lambda s: {
            "equipment_id": "EQ-00001",
            "title": "New task",
            "due_date": (NOW.date() + timedelta(days=7)).isoformat(),
            "assigned_technician_id": s.tech_other_id,
        },
    ),
    Rule(
        "Assign technician",
        "REQ-MAINT-04",
        "POST",
        lambda s, a: f"/api/maintenance/{s.scheduled_task}/assign",
        ADMIN,
        body=lambda s: {"assigned_technician_id": s.tech_other_id},
    ),
    Rule(
        "Start maintenance task (own)",
        "REQ-MAINT-05",
        "POST",
        lambda s, a: f"/api/maintenance/{s.scheduled_task}/start",
        frozenset({"admin", "technician"}),
    ),
    Rule(
        "Complete maintenance task (own)",
        "REQ-MAINT-06",
        "POST",
        lambda s, a: f"/api/maintenance/{s.in_progress_task}/complete",
        frozenset({"admin", "technician"}),
    ),
    Rule(
        "Cancel maintenance task",
        "REQ-MAINT-07",
        "POST",
        lambda s, a: f"/api/maintenance/{s.scheduled_task}/cancel",
        ADMIN,
    ),
    # Reports
    Rule("Availability report", "REQ-REP-01", "GET", const("/api/reports/availability"), STAFF),
    Rule("Fault report", "REQ-REP-02", "GET", const("/api/reports/faults"), STAFF),
    Rule("Maintenance report", "REQ-REP-03", "GET", const("/api/reports/maintenance"), STAFF),
    # Users
    Rule("List users", "REQ-ROLE-06", "GET", const("/api/users"), ADMIN),
    Rule(
        "Create user",
        "REQ-ROLE-06",
        "POST",
        const("/api/users"),
        ADMIN,
        body=lambda s: {
            "username": "new_user",
            "display_name": "New User",
            "role": "academic",
            "password": "another-synthetic-pass",
        },
    ),
]

CASES = [
    pytest.param(rule, actor, id=f"{rule.action} | {actor} | {'allow' if actor in rule.allowed else 'deny'}")
    for rule in RULES
    for actor in ACTORS
    if actor in rule.actors
]


def snapshot(app: FastAPI) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every business table (sessions excluded: logging in legitimately writes them)."""
    with app.state.engine.connect() as conn:
        return {
            t.name: sorted(tuple(r) for r in conn.execute(t.select()))
            for t in Base.metadata.sorted_tables
            if t.name != "user_sessions"
        }


# ---------------------------------------------------------------- act + assert


@pytest.mark.parametrize(("rule", "actor"), CASES)
def test_permission_matrix(
    rule: Rule, actor: str, seed: Seed, client_as: Callable[[str], TestClient], app: FastAPI
) -> None:
    client = client_as(actor)
    before = snapshot(app)

    body = rule.body(seed) if rule.body else None
    resp = client.request(rule.method, rule.path(seed, actor), json=body)

    if actor in rule.allowed:
        assert 200 <= resp.status_code < 300, (
            f"[{rule.req}] {actor} should be ALLOWED to '{rule.action}', got {resp.status_code}: {resp.text}"
        )
    else:
        assert resp.status_code == 403, (
            f"[{rule.req}] {actor} should be DENIED '{rule.action}', got {resp.status_code}: {resp.text}"
        )
        assert resp.json()["error"]["code"] == "FORBIDDEN"
        assert snapshot(app) == before, f"[{rule.req}] denied request changed data"
