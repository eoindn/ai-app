"""Synthetic data for the load tests (REQ-DATA-09). Test only password, low bcrypt cost."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt

from app.db import Base, make_engine, make_sessionmaker
from app.domain.enums import BookingStatus, EquipmentStatus, Role
from app.repositories.models import Booking, Equipment, User

USER_COUNT = 200
EQUIPMENT_COUNT = 50
PASSWORD = "synthetic-perf-pass-1"


def username(i: int) -> str:
    return f"perf_user_{i}"


def seed(db_url: str, extra_bookings: int = 0) -> None:
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    with make_sessionmaker(engine)() as s:
        users = [
            User(
                username=username(i), display_name=f"Perf user {i}", role=Role.ACADEMIC, password_hash=pw_hash
            )
            for i in range(USER_COUNT)
        ]
        equipment = [
            Equipment(
                equipment_id=f"EQ-{i:05d}",
                name=f"Lab microscope {i}",
                location="Bio Lab",
                status=EquipmentStatus.AVAILABLE,
                created_at=now,
                updated_at=now,
            )
            for i in range(1, EQUIPMENT_COUNT + 1)
        ]
        s.add_all(users + equipment)
        s.flush()
        # P3 volume: past bookings fill the table without blocking future slots.
        for i in range(extra_bookings):
            start = now - timedelta(days=1 + i // EQUIPMENT_COUNT)
            s.add(
                Booking(
                    equipment_pk=equipment[i % EQUIPMENT_COUNT].id,
                    user_id=users[i % USER_COUNT].id,
                    start=start,
                    end=start + timedelta(hours=1),
                    purpose="Volume seed",
                    status=BookingStatus.CONFIRMED,
                    created_at=start,
                )
            )
        s.commit()
    engine.dispose()
