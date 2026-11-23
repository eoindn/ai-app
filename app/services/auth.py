"""Authentication: password hashing and server-side sessions (REQ-ROLE-01..04)."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

import bcrypt
from sqlalchemy.orm import Session

from app.clock import Clock
from app.domain.errors import NotAuthenticated
from app.logging import log_event
from app.repositories import users as users_repo
from app.repositories.models import User, UserSession

BCRYPT_MAX_BYTES = 72
# Verified against when the username is unknown, so both failure paths cost the same.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    """REQ-ROLE-04: bcrypt only."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(raw, password_hash.encode())


def login(db: Session, clock: Clock, username: str, password: str, session_hours: int) -> tuple[User, str]:
    """REQ-ROLE-02: same error for unknown user, wrong password and inactive user."""
    user = users_repo.get_by_username(db, username)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        ok = False
    else:
        ok = verify_password(password, user.password_hash) and user.is_active
    if user is None or not ok:
        log_event("auth_failure", logging.WARNING, username=username)
        raise NotAuthenticated("Invalid username or password")

    now = clock.now()
    users_repo.delete_expired_sessions(db, now)
    token = secrets.token_urlsafe(32)
    users_repo.add_session(
        db,
        UserSession(
            token=token,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(hours=session_hours),
        ),
    )
    db.commit()
    log_event("login", user_id=user.id)
    return user, token


def logout(db: Session, token: str | None) -> None:
    """REQ-ROLE-03: the server-side session is deleted, so an old cookie stops working."""
    if token:
        users_repo.delete_session(db, token)
        db.commit()


def user_for_token(db: Session, clock: Clock, token: str | None) -> User | None:
    if not token:
        return None
    session = users_repo.get_session(db, token)
    if session is None or session.expires_at <= clock.now():
        return None
    user = users_repo.get(db, session.user_id)
    if user is None or not user.is_active:
        return None
    return user
