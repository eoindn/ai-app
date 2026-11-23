"""Role -> action permission matrix (SPEC section 4). Ownership rules are enforced in services."""

from __future__ import annotations

from enum import StrEnum

from app.domain.enums import Role
from app.domain.errors import Forbidden


class Action(StrEnum):
    EQUIPMENT_VIEW = "equipment.view"
    EQUIPMENT_CREATE = "equipment.create"
    EQUIPMENT_UPDATE = "equipment.update"
    EQUIPMENT_DELETE = "equipment.delete"
    EQUIPMENT_CHANGE_STATUS = "equipment.change_status"
    EQUIPMENT_VIEW_HISTORY = "equipment.view_history"
    BOOKING_CREATE = "booking.create"
    BOOKING_VIEW_OWN = "booking.view_own"
    BOOKING_VIEW_ALL = "booking.view_all"
    BOOKING_CANCEL_OWN = "booking.cancel_own"
    BOOKING_CANCEL_ANY = "booking.cancel_any"
    BOOKING_VIEW_OTHERS_IDENTITY = "booking.view_others_identity"
    FAULT_REPORT = "fault.report"
    FAULT_VIEW = "fault.view"
    FAULT_UPDATE = "fault.update"
    MAINT_VIEW = "maintenance.view"
    MAINT_SCHEDULE = "maintenance.schedule"
    MAINT_ASSIGN = "maintenance.assign"
    MAINT_WORK_OWN = "maintenance.work_own"
    MAINT_WORK_ANY = "maintenance.work_any"
    MAINT_CANCEL = "maintenance.cancel"
    REPORT_VIEW = "report.view"
    USER_MANAGE = "user.manage"


A, T, C = Role.ADMIN, Role.TECHNICIAN, Role.ACADEMIC

PERMISSIONS: dict[Action, frozenset[Role]] = {
    Action.EQUIPMENT_VIEW: frozenset({A, T, C}),
    Action.EQUIPMENT_CREATE: frozenset({A}),
    Action.EQUIPMENT_UPDATE: frozenset({A}),
    Action.EQUIPMENT_DELETE: frozenset({A}),
    Action.EQUIPMENT_CHANGE_STATUS: frozenset({A, T}),
    Action.EQUIPMENT_VIEW_HISTORY: frozenset({A, T}),
    Action.BOOKING_CREATE: frozenset({A, T, C}),
    Action.BOOKING_VIEW_OWN: frozenset({A, T, C}),
    Action.BOOKING_VIEW_ALL: frozenset({A, T}),
    Action.BOOKING_CANCEL_OWN: frozenset({A, T, C}),
    Action.BOOKING_CANCEL_ANY: frozenset({A}),
    Action.BOOKING_VIEW_OTHERS_IDENTITY: frozenset({A, T}),
    Action.FAULT_REPORT: frozenset({A, T, C}),
    Action.FAULT_VIEW: frozenset({A, T, C}),
    Action.FAULT_UPDATE: frozenset({A, T}),
    Action.MAINT_VIEW: frozenset({A, T}),
    Action.MAINT_SCHEDULE: frozenset({A}),
    Action.MAINT_ASSIGN: frozenset({A}),
    Action.MAINT_WORK_OWN: frozenset({A, T}),
    Action.MAINT_WORK_ANY: frozenset({A}),
    Action.MAINT_CANCEL: frozenset({A}),
    Action.REPORT_VIEW: frozenset({A, T}),
    Action.USER_MANAGE: frozenset({A}),
}


def can(role: Role, action: Action) -> bool:
    """REQ-ROLE-05: unknown actions are denied."""
    return role in PERMISSIONS.get(action, frozenset())


def require(role: Role, action: Action) -> None:
    """REQ-ROLE-05: raise Forbidden unless the matrix allows `action` for `role`."""
    if not can(role, action):
        raise Forbidden(f"Role '{role}' is not permitted to perform '{action}'")
