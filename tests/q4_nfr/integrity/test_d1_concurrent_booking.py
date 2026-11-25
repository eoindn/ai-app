"""D1: concurrent double booking. REQ-BOOK-16, REQ-BOOK-07. Risk: Critical. Issue #3.

Runs against a real uvicorn process with a file database, because TestClient can
serialise requests and hide a race.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.db import Base, make_engine, make_sessionmaker
from app.domain.enums import BookingStatus, EquipmentStatus, Role
from app.repositories.models import Booking, Equipment, User
from tests.conftest import _TEST_HASH, TEST_PASSWORD

pytestmark = pytest.mark.integrity

ROOT = Path(__file__).resolve().parents[3]
MAX_USERS = 50
ROUNDS = 20
SIZES = (10, 15, 20, 50)
TIMEOUT = 45


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, str]]:
    db_url = f"sqlite:///{tmp_path_factory.mktemp('d1') / 'd1.db'}"
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with make_sessionmaker(engine)() as s:
        s.add_all(
            User(
                username=f"d1_user_{i}",
                display_name=f"D1 user {i}",
                role=Role.ACADEMIC,
                password_hash=_TEST_HASH,
            )
            for i in range(MAX_USERS)
        )
        s.add(
            Equipment(
                equipment_id="EQ-00001",
                name="Shared microscope",
                location="Test Lab",
                status=EquipmentStatus.AVAILABLE,
                created_at=now,
                updated_at=now,
            )
        )
        s.commit()
    engine.dispose()

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env={**os.environ, "LEMMS_DATABASE_URL": db_url},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{base}/health").status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            pytest.fail("server did not start")
        yield base, db_url
    finally:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def clients(server: tuple[str, str]) -> Iterator[list[httpx.Client]]:
    base, _ = server
    logged_in = []
    for i in range(MAX_USERS):
        c = httpx.Client(base_url=base, timeout=TIMEOUT)
        r = c.post("/api/auth/login", json={"username": f"d1_user_{i}", "password": TEST_PASSWORD})
        assert r.status_code == 200
        logged_in.append(c)
    yield logged_in
    for c in logged_in:
        c.close()


def _first_slot() -> datetime:
    return (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)


FIRST_SLOT = _first_slot()


def _race(n: int, start: datetime, clients: list[httpx.Client]) -> Counter[int | str]:
    # Half ask for the exact slot, half for one overlapping by 30 min, so any two requests clash.
    bodies = [
        {
            "equipment_id": "EQ-00001",
            "start": (start + timedelta(minutes=30 * (i % 2))).isoformat(),
            "end": (start + timedelta(minutes=60 + 30 * (i % 2))).isoformat(),
            "purpose": "Race test",
        }
        for i in range(n)
    ]
    barrier = threading.Barrier(n)

    def fire(i: int) -> int | str:
        barrier.wait()
        try:
            return clients[i].post("/api/bookings", json=bodies[i]).status_code
        except httpx.TimeoutException:
            return "timeout"

    with ThreadPoolExecutor(max_workers=n) as pool:
        return Counter(pool.map(fire, range(n)))


def _confirmed_in(db_url: str, start: datetime) -> int:
    engine = make_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            select(Booking.id).where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.start < start + timedelta(minutes=90),
                Booking.end > start,
            )
        ).all()
    engine.dispose()
    return len(rows)


@pytest.mark.parametrize("n", SIZES, ids=[f"N={n}" for n in SIZES])
def test_exactly_one_booking_wins(n: int, server: tuple[str, str], clients: list[httpx.Client]) -> None:
    """Each round: n parallel requests for clashing slots. Expect one 201 and n-1 409s, every round."""
    results = []
    for round_no in range(ROUNDS):
        start = FIRST_SLOT + timedelta(hours=2 * (SIZES.index(n) * ROUNDS + round_no))
        statuses = _race(n, start, clients)
        results.append((dict(statuses), _confirmed_in(server[1], start)))
        if statuses != Counter({201: 1, 409: n - 1}) or results[-1][1] != 1:
            pytest.fail(
                f"N={n} round {round_no + 1}: responses {dict(statuses)}, "
                f"{results[-1][1]} confirmed bookings in DB"
            )
    print(f"N={n}: {ROUNDS}/{ROUNDS} rounds had exactly one winner")
