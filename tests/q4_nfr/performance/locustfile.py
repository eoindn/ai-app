"""P1 to P3 load profile. Issue #4. Run through run_perf.py, which seeds a fresh DB and starts the server."""

from __future__ import annotations

import itertools
import os
import random
from datetime import UTC, datetime, timedelta

from locust import HttpUser, between, constant, task

from tests.q4_nfr.performance.seed_perf import EQUIPMENT_COUNT, PASSWORD, username

_user_ids = itertools.count()
TIMEOUT = 40
_SEARCH_TERMS = ["lab", "microscope", "EQ-000", "printer", "bio", "chem"]


class LabUser(HttpUser):
    """Mix from docs/TEST-STRATEGY.md §5: browse 70 %, schedule 20 %, book 10 %."""

    # LEMMS_NO_THINK=1 removes the pause, so N users means N requests in flight (stress test).
    wait_time = constant(0) if os.environ.get("LEMMS_NO_THINK") else between(1, 3)

    def on_start(self) -> None:
        self.client.post(
            "/api/auth/login",
            json={"username": username(next(_user_ids)), "password": PASSWORD},
            timeout=TIMEOUT,
            name="login (setup)",
        )

    @task(7)
    def browse(self) -> None:
        self.client.get(
            "/api/equipment",
            params={"q": random.choice(_SEARCH_TERMS)},
            timeout=TIMEOUT,
            name="browse: search",
        )

    @task(2)
    def schedule(self) -> None:
        self.client.get(
            f"/api/equipment/{_random_equipment()}/bookings", timeout=TIMEOUT, name="schedule: view"
        )

    @task(1)
    def book(self) -> None:
        start = _random_slot()
        body = {
            "equipment_id": _random_equipment(),
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
            "purpose": "Load test booking",
        }
        with self.client.post(
            "/api/bookings", json=body, timeout=TIMEOUT, name="book: create", catch_response=True
        ) as r:
            if r.status_code in (201, 409):
                r.success()  # a clash is a correct answer, not a failure


def _random_equipment() -> str:
    return f"EQ-{random.randint(1, EQUIPMENT_COUNT):05d}"


def _random_slot() -> datetime:
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    return base + timedelta(minutes=15 * random.randint(0, 4 * 24 * 25))
