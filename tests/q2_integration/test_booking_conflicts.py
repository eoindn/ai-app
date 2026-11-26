"""Q2 integration tests: booking conflicts through the API (REQ-BOOK-07, REQ-BOOK-01).

Technique: equivalence partitioning + boundary value analysis on time intervals.
Partitions: "overlaps" (409) and "does not overlap" (201). Boundaries: touching intervals
(end == start, allowed under the half-open rule [start, end)) versus the smallest possible
overlap (one 15-minute slot, rejected).

Fixture: an existing CONFIRMED booking by academic1 on EQ-00001, 10:00-12:00 on 1 Dec 2026.
The clock is fixed at 09:00 the same day. A different user (academic2) makes the new booking,
so the tests prove conflicts are per-equipment, not per-user.

Unit tests in tests/q1_testing_unit already check overlaps() in isolation. These tests check the
rule is actually enforced end to end: request validation, the service, the SQL pre-filter in
repositories/bookings.py and the database all have to agree.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient


def at(hour: int, minute: int = 0) -> str:
    """ISO-8601 time on 1 Dec 2026 with an explicit UTC offset (SPEC 1.2)."""
    return datetime(2026, 12, 1, hour, minute, tzinfo=UTC).isoformat()


def booking_body(equipment_id: str, start: str, end: str) -> dict[str, Any]:
    return {"equipment_id": equipment_id, "start": start, "end": end, "purpose": "Integration test booking"}


@pytest.fixture
def existing_booking(academic: TestClient, make_equipment: Callable[[str], str]) -> dict[str, Any]:
    equipment_id = make_equipment("EQ-00001")
    response = academic.post("/api/bookings", json=booking_body(equipment_id, at(10), at(12)))
    assert response.status_code == 201, response.text
    booking: dict[str, Any] = response.json()
    return booking


# (test id, new start, new end, expected HTTP status)
OVERLAP_CASES = [
    ("IT-BK-01 identical interval", at(10), at(12), 409),
    ("IT-BK-02 overlaps start by one slot", at(9, 15), at(10, 15), 409),
    ("IT-BK-03 overlaps end by one slot", at(11, 45), at(12, 45), 409),
    ("IT-BK-04 inside existing", at(10, 30), at(11, 30), 409),
    ("IT-BK-05 covers existing", at(9, 30), at(12, 30), 409),
    ("IT-BK-06 ends exactly at existing start", at(9, 15), at(10), 201),
    ("IT-BK-07 starts exactly at existing end", at(12), at(13), 201),
]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [case[1:] for case in OVERLAP_CASES],
    ids=[case[0] for case in OVERLAP_CASES],
)
def test_overlap_boundaries(
    existing_booking: dict[str, Any],
    other_academic: TestClient,
    start: str,
    end: str,
    expected: int,
) -> None:
    """REQ-BOOK-07: overlap iff new.start < existing.end AND existing.start < new.end.

    REQ-BOOK-01: an allowed booking is CONFIRMED and owned by the caller.
    """
    response = other_academic.post(
        "/api/bookings", json=booking_body(existing_booking["equipment_id"], start, end)
    )

    assert response.status_code == expected, response.text
    if expected == 409:
        assert response.json()["error"]["code"] == "CONFLICT"
    else:
        caller_id = other_academic.get("/api/auth/me").json()["id"]
        assert response.json()["status"] == "CONFIRMED"
        assert response.json()["user_id"] == caller_id


def test_it_bk_08_same_slot_on_different_equipment_is_allowed(
    existing_booking: dict[str, Any],
    other_academic: TestClient,
    make_equipment: Callable[[str], str],
) -> None:
    """REQ-BOOK-07: conflicts are per piece of equipment."""
    second = make_equipment("EQ-00002")

    response = other_academic.post("/api/bookings", json=booking_body(second, at(10), at(12)))

    assert response.status_code == 201, response.text


def test_it_bk_09_cancelled_booking_no_longer_blocks_the_slot(
    existing_booking: dict[str, Any],
    academic: TestClient,
    other_academic: TestClient,
) -> None:
    """REQ-BOOK-07: CANCELLED bookings never conflict."""
    cancel = academic.post(f"/api/bookings/{existing_booking['id']}/cancel")
    assert cancel.status_code == 200, cancel.text

    response = other_academic.post(
        "/api/bookings", json=booking_body(existing_booking["equipment_id"], at(10), at(12))
    )

    assert response.status_code == 201, response.text


def test_it_bk_10_rejected_booking_is_not_saved(
    existing_booking: dict[str, Any],
    other_academic: TestClient,
    admin: TestClient,
) -> None:
    """REQ-BOOK-07: a conflicting booking is rejected with 409 and not saved."""
    rejected = other_academic.post(
        "/api/bookings", json=booking_body(existing_booking["equipment_id"], at(10, 30), at(11, 30))
    )
    assert rejected.status_code == 409

    all_bookings = admin.get("/api/bookings", params={"scope": "all"}).json()
    assert [b["id"] for b in all_bookings] == [existing_booking["id"]]
    assert other_academic.get("/api/bookings").json() == []


def test_it_bk_11_same_user_cannot_double_book_either(
    existing_booking: dict[str, Any],
    academic: TestClient,
) -> None:
    """REQ-BOOK-07 applies regardless of who owns the existing booking."""
    response = academic.post(
        "/api/bookings", json=booking_body(existing_booking["equipment_id"], at(11), at(13))
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
