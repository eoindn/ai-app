"""Small helpers shared by the Q2 integration tests (no fixtures here; those live in conftest.py).

All times are on the fixed test clock's timeline (see conftest.NOW = 1 Dec 2026 09:00 UTC).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

DAY = date(2026, 12, 1)


def at(hour: int, minute: int = 0, day_offset: int = 0) -> str:
    """ISO-8601 instant with an explicit UTC offset (SPEC 1.2), `day_offset` days after 1 Dec 2026."""
    moment = datetime(2026, 12, 1, hour, minute, tzinfo=UTC) + timedelta(days=day_offset)
    return moment.isoformat()


def booking_body(
    equipment_id: str, start: str, end: str, purpose: str = "Integration test booking"
) -> dict[str, Any]:
    return {"equipment_id": equipment_id, "start": start, "end": end, "purpose": purpose}


def book(client: TestClient, equipment_id: str, start: str, end: str) -> dict[str, Any]:
    """Create a booking that is expected to succeed and return it."""
    response = client.post("/api/bookings", json=booking_body(equipment_id, start, end))
    assert response.status_code == 201, response.text
    booking: dict[str, Any] = response.json()
    return booking


def user_id(client: TestClient) -> int:
    """The id of the user logged in on this client."""
    uid: int = client.get("/api/auth/me").json()["id"]
    return uid


def change_status(client: TestClient, equipment_id: str, event: str, **extra: Any) -> Any:
    """POST a manual status event (REQ-STAT-04) and return the raw response."""
    return client.post(f"/api/equipment/{equipment_id}/status", json={"event": event, **extra})


def equipment_status(client: TestClient, equipment_id: str) -> str:
    status: str = client.get(f"/api/equipment/{equipment_id}").json()["status"]
    return status


def report_fault(client: TestClient, equipment_id: str, severity: str) -> dict[str, Any]:
    response = client.post(
        "/api/faults",
        json={
            "equipment_id": equipment_id,
            "title": f"{severity} test fault",
            "description": "Synthetic fault raised by an integration test.",
            "severity": severity,
        },
    )
    assert response.status_code == 201, response.text
    fault: dict[str, Any] = response.json()
    return fault


def schedule_task(admin: TestClient, equipment_id: str, technician_id: int) -> dict[str, Any]:
    response = admin.post(
        "/api/maintenance",
        json={
            "equipment_id": equipment_id,
            "title": "Routine calibration",
            "due_date": DAY.isoformat(),
            "assigned_technician_id": technician_id,
        },
    )
    assert response.status_code == 201, response.text
    task: dict[str, Any] = response.json()
    return task
