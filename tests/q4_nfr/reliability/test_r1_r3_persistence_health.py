"""R1: data survives restart and crash (REQ-DATA-01). R3: /health detects a lost DB (REQ-DATA-08)."""

from __future__ import annotations

import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Base, make_engine, make_sessionmaker
from app.domain.enums import Role
from app.repositories.models import User
from tests.conftest import _TEST_HASH, TEST_PASSWORD
from tests.q4_nfr.live_server import free_port, live_server

pytestmark = pytest.mark.reliability


def db_rows(db_url: str) -> dict[str, list[tuple[Any, ...]]]:
    engine = make_engine(db_url)
    with engine.connect() as conn:
        rows = {
            t.name: sorted(tuple(r) for r in conn.execute(t.select())) for t in Base.metadata.sorted_tables
        }
    engine.dispose()
    return rows


def login(base: str, username: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=10)
    assert (
        c.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200
    )
    return c


@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGKILL], ids=["graceful stop", "crash"])
def test_data_survives_restart(stop: signal.Signals, tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'r1.db'}"
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    with make_sessionmaker(engine)() as s:
        s.add_all(
            [
                User(username="r1_admin", display_name="R1 admin", role=Role.ADMIN, password_hash=_TEST_HASH),
                User(
                    username="r1_academic",
                    display_name="R1 academic",
                    role=Role.ACADEMIC,
                    password_hash=_TEST_HASH,
                ),
            ]
        )
        s.commit()
    engine.dispose()
    start = (datetime.now(UTC) + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    port = free_port()

    with live_server(db_url, port) as (base, proc):
        admin, academic = login(base, "r1_admin"), login(base, "r1_academic")
        for code in ("EQ-00010", "EQ-00011"):
            r = admin.post(
                "/api/equipment", json={"equipment_id": code, "name": "Restart item", "location": "Lab"}
            )
            assert r.status_code == 201
        assert (
            academic.post(
                "/api/bookings",
                json={
                    "equipment_id": "EQ-00010",
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=1)).isoformat(),
                    "purpose": "Survive restart",
                },
            ).status_code
            == 201
        )
        assert (
            academic.post(
                "/api/faults",
                json={
                    "equipment_id": "EQ-00010",
                    "title": "Loose knob",
                    "description": "Focus knob is loose",
                    "severity": "LOW",
                },
            ).status_code
            == 201
        )
        assert (
            admin.post(
                "/api/equipment/EQ-00011/status",
                json={"event": "take_out_of_service", "reason": "Restart test"},
            ).status_code
            == 200
        )
        cookie = academic.cookies["lemms_session"]
        proc.send_signal(stop)
        proc.wait(timeout=10)

    before = db_rows(db_url)

    with live_server(db_url, port) as (base, _):
        assert db_rows(db_url) == before, "database changed across restart"
        returning = httpx.Client(base_url=base, cookies={"lemms_session": cookie}, timeout=10)
        mine = returning.get("/api/bookings")
        assert mine.status_code == 200, "server side session lost on restart"
        assert [b["purpose"] for b in mine.json()] == ["Survive restart"]
        assert returning.get("/api/equipment/EQ-00011").json()["status"] == "OUT_OF_SERVICE"

    assert len(before["equipment"]) == 2 and len(before["bookings"]) == 1
    assert len(before["faults"]) == 1 and len(before["status_changes"]) == 1


def test_health_reports_lost_database(app: FastAPI, anon_client: TestClient, tmp_path: Path) -> None:
    assert anon_client.get("/health").json() == {"status": "ok"}

    working = app.state.engine
    app.state.engine = make_engine(f"sqlite:///{tmp_path / 'missing_dir' / 'gone.db'}")
    down = anon_client.get("/health")
    app.state.engine = working

    assert down.status_code == 503
    assert down.json() == {"status": "unavailable"}
    assert anon_client.get("/health").status_code == 200, "health did not recover"
