"""User and session data access."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.enums import Role
from app.repositories.models import User, UserSession


def get(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def list_users(db: Session, role: Role | None = None) -> list[User]:
    stmt = select(User).order_by(User.username)
    if role is not None:
        stmt = stmt.where(User.role == role)
    return list(db.scalars(stmt))


def add(db: Session, user: User) -> User:
    db.add(user)
    db.flush()
    return user


def add_session(db: Session, session: UserSession) -> None:
    db.add(session)
    db.flush()


def get_session(db: Session, token: str) -> UserSession | None:
    return db.get(UserSession, token)


def delete_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token == token))


def delete_expired_sessions(db: Session, now: datetime) -> None:
    db.execute(delete(UserSession).where(UserSession.expires_at <= now))
