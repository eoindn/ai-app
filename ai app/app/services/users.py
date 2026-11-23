"""User management (REQ-ROLE-06)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.enums import Role
from app.domain.errors import Conflict
from app.domain.permissions import Action, require
from app.repositories import users as users_repo
from app.repositories.models import User
from app.services.auth import hash_password
from app.services.context import Actor


def list_users(db: Session, actor: Actor, role: Role | None = None) -> list[User]:
    """REQ-ROLE-06."""
    require(actor.role, Action.USER_MANAGE)
    return users_repo.list_users(db, role)


def list_technicians(db: Session) -> list[User]:
    """Internal helper for assignment drop-downs; callers enforce MAINT_ASSIGN."""
    return [u for u in users_repo.list_users(db, Role.TECHNICIAN) if u.is_active]


def create_user(
    db: Session, actor: Actor, username: str, display_name: str, role: Role, password: str
) -> User:
    """REQ-ROLE-06: duplicate username -> 409."""
    require(actor.role, Action.USER_MANAGE)
    if users_repo.get_by_username(db, username) is not None:
        raise Conflict(f"Username '{username}' already exists")
    user = users_repo.add(
        db,
        User(
            username=username,
            display_name=display_name,
            role=role,
            password_hash=hash_password(password),
            is_active=True,
        ),
    )
    db.commit()
    return user
