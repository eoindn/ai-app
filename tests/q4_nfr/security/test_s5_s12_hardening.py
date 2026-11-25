"""S5, S6, S7, S10, S11, S12 from docs/TEST-STRATEGY.md. Issue #2."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.enums import BookingStatus, EquipmentStatus
from app.repositories.models import Booking, Equipment, User
from tests.conftest import ACTORS, NOW, TEST_PASSWORD

pytestmark = pytest.mark.security


def add_equipment(db: Session, code: str, name: str, location: str = "Test Lab") -> Equipment:
    e = Equipment(
        equipment_id=code,
        name=name,
        location=location,
        status=EquipmentStatus.AVAILABLE,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(e)
    db.commit()
    return e


# S5: REQ-ROLE-02, OWASP A07


def test_login_failures_are_indistinguishable(
    anon_client: TestClient, db: Session, users: dict[str, User]
) -> None:
    users["academic_other"].is_active = False
    db.commit()
    attempts = {
        "wrong password": (ACTORS["academic"][0], "not-the-password"),
        "unknown user": ("no_such_user", TEST_PASSWORD),
        "inactive user": (ACTORS["academic_other"][0], TEST_PASSWORD),
    }
    responses = {
        name: anon_client.post("/api/auth/login", json={"username": u, "password": p})
        for name, (u, p) in attempts.items()
    }

    for name, resp in responses.items():
        assert resp.status_code == 401, name
        assert "set-cookie" not in resp.headers, name
    bodies = {name: resp.json() for name, resp in responses.items()}
    assert len({json.dumps(b, sort_keys=True) for b in bodies.values()}) == 1, bodies


# S6: REQ-DATA-04, OWASP A05

LEAKY_MESSAGE = "boom at /Users/someone/app/services/equipment.py SELECT * FROM users"


@pytest.fixture
def server_error(app: FastAPI, users: dict[str, User], monkeypatch: pytest.MonkeyPatch) -> Response:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(LEAKY_MESSAGE)

    monkeypatch.setattr("app.services.equipment.search", boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/auth/login", json={"username": ACTORS["academic"][0], "password": TEST_PASSWORD})
        return client.get("/api/equipment", headers={"X-Request-ID": "trace-123"})


def test_500_hides_internal_details(server_error: Response) -> None:
    assert server_error.status_code == 500
    error = server_error.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["request_id"] == "trace-123"
    for leak in ("Traceback", "RuntimeError", "SELECT", "/Users", ".py", "boom"):
        assert leak not in server_error.text, f"500 body leaks {leak!r}"


def test_500_carries_request_id_header(server_error: Response) -> None:
    """REQ-DATA-06: every response carries X-Request-ID, including errors."""
    assert server_error.headers.get("x-request-id") == "trace-123"


# S7: REQ-BOOK-15, OWASP A01 (privacy)


@pytest.fixture
def two_bookings(db: Session, users: dict[str, User]) -> None:
    eq = add_equipment(db, "EQ-00001", "Test microscope")
    for i, owner in enumerate(("academic", "academic_other")):
        start = NOW + timedelta(days=1, hours=i)
        db.add(
            Booking(
                equipment_pk=eq.id,
                user_id=users[owner].id,
                start=start,
                end=start + timedelta(hours=1),
                purpose=f"Purpose of {owner}",
                status=BookingStatus.CONFIRMED,
                created_at=NOW,
            )
        )
    db.commit()


@pytest.mark.usefixtures("two_bookings")
def test_academic_sees_others_bookings_masked(
    client_as: Callable[[str], TestClient], users: dict[str, User]
) -> None:
    rows = client_as("academic").get("/api/equipment/EQ-00001/bookings").json()
    assert len(rows) == 2
    own = [r for r in rows if r["user_id"] == users["academic"].id]
    masked = [r for r in rows if r["user_id"] is None]
    assert len(own) == 1 and own[0]["purpose"] == "Purpose of academic"
    assert len(masked) == 1 and masked[0]["purpose"] is None
    assert "academic_other" not in json.dumps(rows)


@pytest.mark.usefixtures("two_bookings")
@pytest.mark.parametrize("actor", ["admin", "technician"])
def test_staff_see_all_booking_identities(actor: str, client_as: Callable[[str], TestClient]) -> None:
    rows = client_as(actor).get("/api/equipment/EQ-00001/bookings").json()
    assert all(r["user_id"] is not None and r["purpose"] for r in rows)


# S10: REQ-ROLE-07, OWASP A05/A07


def _cookie_attributes(app: FastAPI) -> list[str]:
    with TestClient(app) as client:
        resp = client.post(
            "/api/auth/login", json={"username": ACTORS["academic"][0], "password": TEST_PASSWORD}
        )
    assert resp.status_code == 200
    return [part.strip().lower() for part in resp.headers["set-cookie"].split(";")]


@pytest.mark.usefixtures("users")
def test_session_cookie_flags(app: FastAPI) -> None:
    attrs = _cookie_attributes(app)
    assert attrs[0].startswith("lemms_session=")
    assert "httponly" in attrs
    assert "samesite=lax" in attrs
    assert "path=/" in attrs


@pytest.mark.usefixtures("users")
def test_secure_flag_follows_setting(app: FastAPI, settings: Settings) -> None:
    assert "secure" not in _cookie_attributes(app)
    app.state.settings = replace(settings, secure_cookies=True)
    assert "secure" in _cookie_attributes(app)


# S11: REQ-ROLE-04, OWASP A02

NEW_PASSWORD = "another-synthetic-pass"


def test_passwords_stored_as_bcrypt_and_never_exposed(
    client_as: Callable[[str], TestClient],
    anon_client: TestClient,
    db: Session,
    log_lines: list[dict[str, object]],
) -> None:
    admin = client_as("admin")
    created = admin.post(
        "/api/users",
        json={
            "username": "new_user",
            "display_name": "New User",
            "role": "academic",
            "password": NEW_PASSWORD,
        },
    )
    assert created.status_code == 201
    anon_client.post("/api/auth/login", json={"username": "new_user", "password": "wrong-guess-123"})
    login = anon_client.post("/api/auth/login", json={"username": "new_user", "password": NEW_PASSWORD})
    listing = admin.get("/api/users")

    stored = db.scalar(select(User.password_hash).where(User.username == "new_user"))
    assert stored is not None and stored.startswith("$2b$")
    assert bcrypt.checkpw(NEW_PASSWORD.encode(), stored.encode())

    responses = created.text + login.text + listing.text
    logs = json.dumps(log_lines)
    for secret in (NEW_PASSWORD, "wrong-guess-123", stored, "password"):
        assert secret not in responses, f"response contains {secret!r}"
        assert secret not in logs, f"log contains {secret!r}"
    assert any(line["event"] == "auth_failure" for line in log_lines)


# S12: REQ-INV-07, REQ-DATA-02, OWASP A03

SEEDED = [
    ("EQ-00001", "Optical microscope", "Bio Lab"),
    ("EQ-00002", "Centrifuge 50%", "Chem_Lab"),
    ("EQ-00003", "Équipement de test", "Salle É"),
]

PAYLOADS = [
    "' OR 1=1--",
    '" OR ""="',
    "'; DROP TABLE equipment;--",
    "%",
    "_",
    "50%",
    "chem_",
    "\\",
    "Équipement",
    "équipement",
    "ÉQUIPEMENT",
]


@pytest.mark.parametrize("q", PAYLOADS)
def test_search_treats_input_as_literal_text(
    q: str, db: Session, client_as: Callable[[str], TestClient], app: FastAPI
) -> None:
    for row in SEEDED:
        add_equipment(db, *row)
    expected = sorted(
        code for code, name, loc in SEEDED if any(q.lower() in f.lower() for f in (code, name, loc))
    )

    resp = client_as("academic").get("/api/equipment", params={"q": q})

    assert resp.status_code == 200, resp.text
    assert sorted(i["equipment_id"] for i in resp.json()["items"]) == expected
    with app.state.engine.connect() as conn:
        assert conn.execute(select(Equipment.id)).all(), "equipment table damaged"
