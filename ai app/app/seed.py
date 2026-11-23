"""Synthetic seed data (REQ-DATA-09). Usage: python -m app.seed [--reset]

Passwords are never committed: set LEMMS_SEED_PASSWORD, or a random one is generated and printed.
Historical rows (past bookings, overdue tasks) are inserted directly, bypassing "no past date" rules.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import datetime, time, timedelta

from sqlalchemy import select

from app.clock import SystemClock
from app.config import load_settings
from app.db import Base, make_engine, make_sessionmaker
from app.domain.enums import (
    BookingStatus,
    EquipmentStatus,
    FaultSeverity,
    FaultStatus,
    MaintenanceStatus,
    Role,
)
from app.domain.timeutil import LAB_TZ, local_date
from app.repositories.models import (
    Booking,
    Equipment,
    Fault,
    MaintenanceTask,
    StatusChange,
    User,
)
from app.services.auth import hash_password

USERS = [
    ("admin1", "Admin One", Role.ADMIN),
    ("tech1", "Technician Alpha", Role.TECHNICIAN),
    ("tech2", "Technician Beta", Role.TECHNICIAN),
    ("academic1", "Academic Gamma", Role.ACADEMIC),
    ("academic2", "Academic Delta", Role.ACADEMIC),
]

EQUIPMENT = [
    ("EQ-00001", "Optical Microscope", "Bio Lab 1", "Compound microscope, 40x–1000x"),
    ("EQ-00002", "Centrifuge", "Bio Lab 1", "Benchtop centrifuge, max 15,000 rpm"),
    ("EQ-00003", "Spectrophotometer", "Chem Lab 2", "UV-Vis, 190–1100 nm"),
    ("EQ-00004", "Fume Hood", "Chem Lab 2", None),
    ("EQ-00005", "Oscilloscope", "Electronics Lab", "4-channel, 200 MHz"),
    ("EQ-00006", "Signal Generator", "Electronics Lab", None),
    ("EQ-00007", "3D Printer", "Maker Space", "FDM, 250 mm build volume"),
    ("EQ-00008", "Laser Cutter", "Maker Space", "CO2 laser, 40 W"),
    ("EQ-00009", "PCR Thermocycler", "Bio Lab 2", "96-well"),
    ("EQ-00010", "Autoclave", "Bio Lab 2", None),
    ("EQ-00011", "pH Meter", "Chem Lab 1", "Benchtop, ±0.01 pH"),
    ("EQ-00012", "Analytical Balance", "Chem Lab 1", "0.1 mg readability"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed LEMMS with synthetic data")
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    args = parser.parse_args()

    settings = load_settings()
    engine = make_engine(settings.database_url)
    if args.reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    sm = make_sessionmaker(engine)
    now = SystemClock().now()
    today = local_date(now)

    with sm() as db:
        if db.scalar(select(User).limit(1)) is not None:
            print("Database already has data. Use --reset to wipe and reseed.", file=sys.stderr)
            return 1

        password = os.environ.get("LEMMS_SEED_PASSWORD") or secrets.token_urlsafe(9)
        pw_hash = hash_password(password)
        users = {
            u: User(username=u, display_name=d, role=r, password_hash=pw_hash, is_active=True)
            for u, d, r in USERS
        }
        db.add_all(users.values())
        db.flush()

        equipment = {
            eid: Equipment(
                equipment_id=eid,
                name=n,
                location=loc,
                description=desc,
                status=EquipmentStatus.AVAILABLE,
                created_at=now,
                updated_at=now,
            )
            for eid, n, loc, desc in EQUIPMENT
        }
        db.add_all(equipment.values())
        db.flush()

        def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
            local = datetime.combine(today + timedelta(days=day_offset), time(hour, minute), LAB_TZ)
            return local.astimezone(now.tzinfo)

        def book(eid: str, user: str, day: int, h1: int, h2: int, purpose: str) -> None:
            db.add(
                Booking(
                    equipment_pk=equipment[eid].id,
                    user_id=users[user].id,
                    start=at(day, h1),
                    end=at(day, h2),
                    purpose=purpose,
                    status=BookingStatus.CONFIRMED,
                    created_at=now,
                )
            )

        book("EQ-00001", "academic1", 1, 9, 11, "Cell biology practical")
        book("EQ-00001", "academic2", 1, 11, 13, "Final-year project imaging")
        book("EQ-00003", "academic1", 2, 14, 16, "Absorbance calibration")
        book("EQ-00005", "academic2", 3, 10, 12, "Circuits teaching lab")
        book("EQ-00007", "tech1", 5, 9, 17, "Printing replacement parts")
        book("EQ-00002", "academic1", -2, 10, 11, "Past booking (history)")

        # Out-of-service item with history.
        oos = equipment["EQ-00008"]
        oos.status = EquipmentStatus.OUT_OF_SERVICE
        db.add(
            StatusChange(
                equipment_pk=oos.id,
                from_status=EquipmentStatus.AVAILABLE,
                to_status=EquipmentStatus.OUT_OF_SERVICE,
                event="take_out_of_service",
                user_id=users["tech1"].id,
                reason="Laser tube failure",
                changed_at=now,
            )
        )

        # Under maintenance with an in-progress task.
        um = equipment["EQ-00010"]
        um.status = EquipmentStatus.UNDER_MAINTENANCE
        db.add(
            StatusChange(
                equipment_pk=um.id,
                from_status=EquipmentStatus.AVAILABLE,
                to_status=EquipmentStatus.UNDER_MAINTENANCE,
                event="start_maintenance",
                user_id=users["tech2"].id,
                reason=None,
                changed_at=now,
            )
        )

        def task(eid: str, title: str, due_offset: int, tech: str, status: MaintenanceStatus) -> None:
            db.add(
                MaintenanceTask(
                    equipment_pk=equipment[eid].id,
                    title=title,
                    description=None,
                    due_date=today + timedelta(days=due_offset),
                    assigned_technician_id=users[tech].id,
                    status=status,
                    created_by=users["admin1"].id,
                    created_at=now - timedelta(days=30),
                    started_at=now if status == MaintenanceStatus.IN_PROGRESS else None,
                    completed_at=now - timedelta(days=3) if status == MaintenanceStatus.COMPLETED else None,
                    completed_by=users[tech].id if status == MaintenanceStatus.COMPLETED else None,
                )
            )

        task("EQ-00002", "Annual rotor inspection", -5, "tech1", MaintenanceStatus.SCHEDULED)  # overdue
        task(
            "EQ-00009", "Block temperature calibration", 0, "tech2", MaintenanceStatus.SCHEDULED
        )  # due today
        task("EQ-00003", "Lamp replacement", 4, "tech1", MaintenanceStatus.SCHEDULED)
        task("EQ-00010", "Pressure valve service", 1, "tech2", MaintenanceStatus.IN_PROGRESS)
        task("EQ-00012", "Calibration check", -10, "tech1", MaintenanceStatus.COMPLETED)

        def fault(
            eid: str, title: str, desc: str, sev: FaultSeverity, st: FaultStatus, by: str, days_ago: int
        ) -> None:
            db.add(
                Fault(
                    equipment_pk=equipment[eid].id,
                    title=title,
                    description=desc,
                    severity=sev,
                    status=st,
                    reported_by=users[by].id,
                    reported_at=now - timedelta(days=days_ago),
                    resolution_notes="Replaced fuse" if st == FaultStatus.RESOLVED else None,
                    resolved_by=users["tech1"].id if st == FaultStatus.RESOLVED else None,
                    resolved_at=now if st == FaultStatus.RESOLVED else None,
                )
            )

        fault(
            "EQ-00004",
            "Airflow alarm",
            "Low airflow alarm sounds intermittently.",
            FaultSeverity.HIGH,
            FaultStatus.OPEN,
            "academic1",
            2,
        )
        fault(
            "EQ-00006",
            "Loose output knob",
            "Amplitude knob slips when turned.",
            FaultSeverity.LOW,
            FaultStatus.IN_PROGRESS,
            "academic2",
            4,
        )
        fault(
            "EQ-00011",
            "Display flicker",
            "LCD display flickers on start-up.",
            FaultSeverity.MEDIUM,
            FaultStatus.RESOLVED,
            "academic1",
            9,
        )

        db.commit()

    print("Seeded synthetic data.")
    print("Users: " + ", ".join(u for u, _, _ in USERS))
    if "LEMMS_SEED_PASSWORD" not in os.environ:
        print(f"Generated password for all seed users: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
