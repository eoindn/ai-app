"""FastAPI dependencies: DB session, clock, current user."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.clock import Clock
from app.domain.errors import NotAuthenticated
from app.logging import set_user
from app.services import auth as auth_service
from app.services.context import Actor

SESSION_COOKIE = "lemms_session"


def get_db(request: Request) -> Iterator[Session]:
    db: Session = request.app.state.sessionmaker()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


DbDep = Annotated[Session, Depends(get_db)]
ClockDep = Annotated[Clock, Depends(get_clock)]


async def get_optional_actor(request: Request, db: DbDep, clock: ClockDep) -> Actor | None:
    # async on purpose: context vars set here are inherited by the (threadpool) endpoint.
    user = auth_service.user_for_token(db, clock, request.cookies.get(SESSION_COOKIE))
    if user is None:
        return None
    request.state.user_id = user.id
    request.state.role = user.role.value
    set_user(user.id, user.role.value)
    return Actor(id=user.id, username=user.username, display_name=user.display_name, role=user.role)


async def get_actor(actor: Annotated[Actor | None, Depends(get_optional_actor)]) -> Actor:
    """REQ-ROLE-01."""
    if actor is None:
        raise NotAuthenticated("Authentication required")
    return actor


ActorDep = Annotated[Actor, Depends(get_actor)]
OptionalActorDep = Annotated[Actor | None, Depends(get_optional_actor)]
