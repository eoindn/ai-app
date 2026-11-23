"""Enumerations shared across layers (SPEC sections 1.1, 2.2-2.5)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    TECHNICIAN = "technician"
    ACADEMIC = "academic"


class EquipmentStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    BOOKED = "BOOKED"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class StatusEvent(StrEnum):
    CHECK_OUT = "check_out"
    RETURN = "return"
    START_MAINTENANCE = "start_maintenance"
    COMPLETE_MAINTENANCE = "complete_maintenance"
    TAKE_OUT_OF_SERVICE = "take_out_of_service"
    RETURN_TO_SERVICE = "return_to_service"


class BookingStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class CancelReason(StrEnum):
    USER_CANCELLED = "USER_CANCELLED"
    EQUIPMENT_OUT_OF_SERVICE = "EQUIPMENT_OUT_OF_SERVICE"


class FaultSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FaultStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


class FaultEvent(StrEnum):
    START = "start"
    RESOLVE = "resolve"


class MaintenanceStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MaintenanceEvent(StrEnum):
    START = "start"
    COMPLETE = "complete"
    CANCEL = "cancel"
