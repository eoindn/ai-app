"""Structured JSON logging + request-ID middleware (REQ-DATA-06, REQ-DATA-07)."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)
role_var: ContextVar[str | None] = ContextVar("role", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_logger = logging.getLogger("lemms")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # Log timestamps use wall-clock time on purpose: they are not business rules.
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
            "role": role_var.get(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    if any(getattr(h, "_lemms", False) for h in _logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._lemms = True  # type: ignore[attr-defined]
    _logger.addHandler(handler)
    _logger.setLevel(level)
    _logger.propagate = False


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    _logger.log(level, event, extra={"fields": fields})


def log_exception(event: str, **fields: Any) -> None:
    _logger.error(event, exc_info=True, extra={"fields": fields})


def set_user(user_id: int | None, role: str | None) -> None:
    user_id_var.set(user_id)
    role_var.set(role)


class RequestContextMiddleware:
    """Pure ASGI middleware so context vars set by endpoints are visible when we log."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming if incoming and _REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        user_id_var.set(None)
        role_var.set(None)
        scope.setdefault("state", {})["request_id"] = request_id

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            state = scope.get("state", {})
            # Auth stores the user in scope state; context vars may not survive threadpool hops.
            user_id_var.set(state.get("user_id"))
            role_var.set(state.get("role"))
            log_event(
                "request",
                method=scope.get("method"),
                route=getattr(route, "path", scope.get("path")),
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            request_id_var.reset(token)
