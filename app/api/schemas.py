"""Request/response models. Request models forbid unknown fields and strip strings (SPEC 1.2, 6)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.domain.enums import (
    BookingStatus,
    CancelReason,
    EquipmentStatus,
    FaultSeverity,
    FaultStatus,
    MaintenanceStatus,
    Role,
    StatusEvent,
)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _s(min_len: int, max_len: int, pattern: str | None = None) -> StringConstraints:
    return StringConstraints(strip_whitespace=True, min_length=min_len, max_length=max_len, pattern=pattern)


# Field types (SPEC section 6). Lengths are counted after stripping whitespace.
EquipmentIdStr = Annotated[str, _s(8, 8, r"^EQ-[0-9]{5}$")]
RefIdStr = Annotated[str, _s(1, 20)]
Text3to100 = Annotated[str, _s(3, 100)]
Location = Annotated[str, _s(2, 50)]
Optional500 = Annotated[str, _s(0, 500)]
Optional1000 = Annotated[str, _s(0, 1000)]
Purpose = Annotated[str, _s(3, 200)]
FaultDescription = Annotated[str, _s(10, 1000)]
Notes5to1000 = Annotated[str, _s(5, 1000)]
Username = Annotated[str, _s(3, 30, r"^[a-z0-9_]+$")]
LoginUsername = Annotated[str, _s(1, 30)]
DisplayName = Annotated[str, _s(2, 60)]
# Passwords are not stripped: whitespace is significant.
NewPassword = Annotated[str, StringConstraints(min_length=8, max_length=64)]
LoginPassword = Annotated[str, StringConstraints(min_length=1, max_length=128)]


# ---------- auth / users ----------


class LoginIn(RequestModel):
    username: LoginUsername
    password: LoginPassword


class UserCreateIn(RequestModel):
    username: Username
    display_name: DisplayName
    role: Role
    password: NewPassword


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: Role


# ---------- equipment ----------


class EquipmentCreateIn(RequestModel):
    equipment_id: EquipmentIdStr
    name: Text3to100
    location: Location
    description: Optional500 | None = None


class EquipmentUpdateIn(RequestModel):
    name: Text3to100 | None = None
    location: Location | None = None
    description: Optional500 | None = None

    @model_validator(mode="after")
    def _no_null_required(self) -> Self:
        for name in ("name", "location"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise PydanticCustomError("dependent_field", "{field} cannot be null", {"field": name})
        return self


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    equipment_id: str
    name: str
    description: str | None
    location: str
    status: EquipmentStatus
    created_at: datetime
    updated_at: datetime


class EquipmentPage(BaseModel):
    total: int
    items: list[EquipmentOut]


class StatusChangeIn(RequestModel):
    event: StatusEvent
    booking_id: int | None = None
    reason: Optional500 | None = None

    @model_validator(mode="after")
    def _event_requirements(self) -> Self:
        """REQ-STAT-05, REQ-STAT-06: fields required by specific events."""
        if self.event == StatusEvent.CHECK_OUT and self.booking_id is None:
            raise PydanticCustomError(
                "dependent_field", "booking_id is required for check_out", {"field": "booking_id"}
            )
        if self.event == StatusEvent.TAKE_OUT_OF_SERVICE and (self.reason is None or len(self.reason) < 5):
            raise PydanticCustomError(
                "dependent_field",
                "reason (5-500 characters) is required for take_out_of_service",
                {"field": "reason"},
            )
        return self


class StatusChangeOut(BaseModel):
    from_status: EquipmentStatus
    to_status: EquipmentStatus
    event: str
    user_id: int
    reason: str | None
    changed_at: datetime


# ---------- bookings ----------


class BookingCreateIn(RequestModel):
    equipment_id: RefIdStr
    start: AwareDatetime
    end: AwareDatetime
    purpose: Purpose


class BookingOut(BaseModel):
    id: int
    equipment_id: str
    user_id: int | None
    start: datetime
    end: datetime
    purpose: str | None
    status: BookingStatus
    created_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancelled_by: int | None = None
    cancel_reason: CancelReason | None = None


# ---------- faults ----------


class FaultCreateIn(RequestModel):
    equipment_id: RefIdStr
    title: Text3to100
    description: FaultDescription
    severity: FaultSeverity


class FaultResolveIn(RequestModel):
    resolution_notes: Notes5to1000


class FaultOut(BaseModel):
    id: int
    equipment_id: str
    title: str
    description: str
    severity: FaultSeverity
    status: FaultStatus
    reported_by: int
    reported_at: datetime
    resolution_notes: str | None
    resolved_by: int | None
    resolved_at: datetime | None


# ---------- maintenance ----------


class MaintenanceCreateIn(RequestModel):
    equipment_id: RefIdStr
    title: Text3to100
    description: Optional1000 | None = None
    due_date: date
    assigned_technician_id: int


class MaintenanceAssignIn(RequestModel):
    assigned_technician_id: int


class MaintenanceCompleteIn(RequestModel):
    completion_notes: Optional1000 | None = None


class MaintenanceOut(BaseModel):
    id: int
    equipment_id: str
    title: str
    description: str | None
    due_date: date
    assigned_technician_id: int
    status: MaintenanceStatus
    is_overdue: bool
    created_by: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    completed_by: int | None
    completion_notes: str | None


# ---------- reports ----------


class AvailabilityOut(BaseModel):
    total: int
    by_status: dict[str, int]


class FaultReportOut(BaseModel):
    total_outstanding: int
    by_severity: dict[str, int]
    faults: list[FaultOut]


class MaintenanceReportOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    overdue: list[MaintenanceOut]
    upcoming: list[MaintenanceOut]
    completed_count: int
