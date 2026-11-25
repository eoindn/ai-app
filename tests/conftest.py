"""Shared pytest fixtures for every LEMMS test suite (Q1–Q4).

Design choices (all test-only, none change application behaviour):
- In-memory SQLite (`sqlite://`) per test → every test starts from an empty, isolated database.
- `FixedClock` → time-dependent rules (session expiry, booking windows, overdue) are deterministic.
- Users are inserted directly and log in through the real `POST /api/auth/login`, so every
  authenticated request goes through the production session mechanism.
- Test password hashes use bcrypt cost 4 (production uses the default 12). bcrypt verifies at the
  cost stored in the hash, so login stays real but takes ~1 ms instead of ~250 ms per test.
- All data is synthetic (REQ-DATA-09). The password below exists only in this test file.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.clock import FixedClock
from app.config import Settings
from app.domain.enums import Role
from app.logging import JsonFormatter
from app.main import create_app
from app.repositories.models import User

# Tuesday 1 Dec 2026, 09:00 UTC (= 09:00 Europe/London, GMT). Far from any DST change.
NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
TEST_PASSWORD = "synthetic-test-pass-1"
_TEST_HASH = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()

# Actor keys used across suites. Two users per non-admin role so ownership rules can be tested.
ACTORS: dict[str, tuple[str, Role]] = {
    "admin": ("test_admin", Role.ADMIN),
    "technician": ("test_tech", Role.TECHNICIAN),
    "technician_other": ("test_tech_other", Role.TECHNICIAN),
    "academic": ("test_academic", Role.ACADEMIC),
    "academic_other": ("test_academic_other", Role.ACADEMIC),
}


def pytest_configure(config: pytest.Config) -> None:
    for name, desc in {
        "unit": "Q1 unit/component tests",
        "functional": "Q2 functional/integration tests",
        "security": "Q4 security tests",
        "integrity": "Q4 data integrity tests",
        "reliability": "Q4 reliability tests",
        "compatibility": "Q4 compatibility tests",
    }.items():
        config.addinivalue_line("markers", f"{name}: {desc}")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="sqlite://", secure_cookies=False, session_hours=8)


@pytest.fixture
def app(settings: Settings, clock: FixedClock) -> FastAPI:
    return create_app(settings=settings, clock=clock)


@pytest.fixture
def db(app: FastAPI) -> Iterator[Session]:
    """A session on the same in-memory DB the app uses, for arranging and asserting on data."""
    session: Session = app.state.sessionmaker()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def users(db: Session) -> dict[str, User]:
    """One active user per actor key, keyed as in ACTORS."""
    created = {
        key: User(
            username=username, display_name=f"Test {key}", role=role, password_hash=_TEST_HASH, is_active=True
        )
        for key, (username, role) in ACTORS.items()
    }
    db.add_all(created.values())
    db.commit()
    return created


@pytest.fixture
def anon_client(app: FastAPI) -> Iterator[TestClient]:
    """A client with no session cookie."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_as(app: FastAPI, users: dict[str, User]) -> Iterator[Callable[[str], TestClient]]:
    """Factory: client_as("academic") returns a TestClient logged in as that actor.

    Each call returns a separate client with its own cookie jar.
    """
    opened: list[TestClient] = []

    def _login(actor: str) -> TestClient:
        client = TestClient(app)
        opened.append(client)
        username = ACTORS[actor][0]
        resp = client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
        assert resp.status_code == 200, f"fixture login failed for {actor}: {resp.text}"
        return client

    yield _login
    for client in opened:
        client.close()


class _JsonCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def log_lines(app: FastAPI) -> Iterator[list[dict[str, object]]]:
    """Parsed JSON log lines from the app. The lemms logger does not propagate, so caplog misses it."""
    handler = _JsonCapture()
    logger = logging.getLogger("lemms")
    logger.addHandler(handler)
    yield handler.lines
    logger.removeHandler(handler)
