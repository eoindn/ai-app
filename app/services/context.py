"""Who is acting, passed explicitly into every service call."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import Role


@dataclass(frozen=True)
class Actor:
    id: int
    username: str
    display_name: str
    role: Role
