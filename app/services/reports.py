"""Summary reports (REQ-REP-*)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.clock import Clock
from app.domain import maintenance as maint_rules
from app.domain.enums import EquipmentStatus, FaultSeverity, MaintenanceStatus
from app.domain.errors import ValidationFailed
from app.domain.faults import OUTSTANDING
from app.domain.permissions import Action, require
from app.domain.timeutil import local_date
from app.repositories import equipment as equipment_repo
from app.repositories import faults as faults_repo
from app.repositories import maintenance as maintenance_repo
from app.repositories.models import Fault, MaintenanceTask
from app.services.context import Actor

DEFAULT_RANGE_DAYS = 30


@dataclass
class AvailabilityReport:
    total: int
    by_status: dict[str, int]


@dataclass
class FaultReport:
    total_outstanding: int
    by_severity: dict[str, int]
    faults: list[Fault]


@dataclass
class MaintenanceReport:
    from_date: date
    to_date: date
    overdue: list[MaintenanceTask]
    upcoming: list[MaintenanceTask]
    completed_count: int


def availability(db: Session, actor: Actor) -> AvailabilityReport:
    """REQ-REP-01: every status key present; counts sum to total."""
    require(actor.role, Action.REPORT_VIEW)
    counts = equipment_repo.count_by_status(db)
    by_status = {s.value: counts.get(s, 0) for s in EquipmentStatus}
    return AvailabilityReport(total=sum(by_status.values()), by_status=by_status)


def outstanding_faults(db: Session, actor: Actor) -> FaultReport:
    """REQ-REP-02."""
    require(actor.role, Action.REPORT_VIEW)
    faults = faults_repo.list_faults(db, statuses=OUTSTANDING)
    by_severity = {s.value: 0 for s in FaultSeverity}
    for f in faults:
        by_severity[f.severity.value] += 1
    return FaultReport(total_outstanding=len(faults), by_severity=by_severity, faults=faults)


def maintenance_summary(
    db: Session,
    clock: Clock,
    actor: Actor,
    from_date: date | None = None,
    to_date: date | None = None,
) -> MaintenanceReport:
    """REQ-REP-03."""
    require(actor.role, Action.REPORT_VIEW)
    now = clock.now()
    to_date = to_date or local_date(now)
    from_date = from_date or to_date - timedelta(days=DEFAULT_RANGE_DAYS)
    if from_date > to_date:
        raise ValidationFailed("from", "'from' must be on or before 'to'")
    tasks = maintenance_repo.list_tasks(db)
    overdue = [t for t in tasks if maint_rules.is_overdue(t.status, t.due_date, now)]
    upcoming = [t for t in tasks if maint_rules.is_upcoming(t.status, t.due_date, now)]
    completed = sum(
        1
        for t in tasks
        if t.status == MaintenanceStatus.COMPLETED
        and t.completed_at is not None
        and from_date <= local_date(t.completed_at) <= to_date
    )
    return MaintenanceReport(from_date, to_date, overdue, upcoming, completed)
