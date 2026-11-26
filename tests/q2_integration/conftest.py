"""Shared fixtures for Q2 integration tests.

Each test gets a brand-new app with its own in-memory SQLite database and a FixedClock,
so tests are isolated and time-dependent rules (REQ-BOOK-05/06/14) are deterministic.
Requests go through the real HTTP stack: routes -> services -> repositories -> database.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.domain.enums import Role
from app.main import create_app
from app.repositories.models import User
from app.services.auth import hash_password

# 1 Dec 2026 is in GMT, so UTC == Europe/London local time and times read naturally.
NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)

# Synthetic test-only credential (REQ-DATA-09). Hashed once because bcrypt is slow.
TEST_PASSWORD = "integration-test-pw"
_PASSWORD_HASH = hash_password(TEST_PASSWORD)

USERS = [
    ("admin1", "Admin One", Role.ADMIN),
    ("tech1", "Technician Alpha", Role.TECHNICIAN),
    ("tech2", "Technician Beta", Role.TECHNICIAN),
    ("academic1", "Academic Gamma", Role.ACADEMIC),
    ("academic2", "Academic Delta", Role.ACADEMIC),
]


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def app(clock: FixedClock) -> FastAPI:
    application = create_app(
        settings=Settings(database_url="sqlite://", secure_cookies=False, session_hours=8),
        clock=clock,
    )
    with application.state.sessionmaker() as db:
        db.add_all(
            User(username=u, display_name=d, role=r, password_hash=_PASSWORD_HASH, is_active=True)
            for u, d, r in USERS
        )
        db.commit()
    return application


@pytest.fixture
def login(app: FastAPI) -> Iterator[Callable[[str], TestClient]]:
    """Returns a function that gives you a TestClient logged in as the named user."""
    clients: list[TestClient] = []

    def _login(username: str) -> TestClient:
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
        assert response.status_code == 200, response.text
        clients.append(client)
        return client

    yield _login
    for client in clients:
        client.close()


@pytest.fixture
def admin(login: Callable[[str], TestClient]) -> TestClient:
    return login("admin1")


@pytest.fixture
def tech(login: Callable[[str], TestClient]) -> TestClient:
    return login("tech1")


@pytest.fixture
def academic(login: Callable[[str], TestClient]) -> TestClient:
    return login("academic1")


@pytest.fixture
def other_academic(login: Callable[[str], TestClient]) -> TestClient:
    return login("academic2")


@pytest.fixture
def make_equipment(admin: TestClient) -> Callable[[str], str]:
    """Creates equipment through the API as admin and returns its equipment_id."""

    def _make(equipment_id: str = "EQ-00001") -> str:
        response = admin.post(
            "/api/equipment",
            json={"equipment_id": equipment_id, "name": "Optical Microscope", "location": "Bio Lab 1"},
        )
        assert response.status_code == 201, response.text
        return equipment_id

    return _make
