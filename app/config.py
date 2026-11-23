"""Configuration from environment variables. See .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    secure_cookies: bool
    session_hours: int


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("LEMMS_DATABASE_URL", "sqlite:///./lemms.db"),
        secure_cookies=os.environ.get("LEMMS_SECURE_COOKIES", "false").lower() == "true",
        session_hours=int(os.environ.get("LEMMS_SESSION_HOURS", "8")),
    )
