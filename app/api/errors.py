"""Map exceptions to the SPEC 1.3 error contract (REQ-DATA-02..04)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import (
    Conflict,
    DomainError,
    Forbidden,
    IllegalTransition,
    NotAuthenticated,
    NotFound,
    ValidationFailed,
)
from app.logging import log_event, log_exception

STATUS_FOR: dict[type[DomainError], int] = {
    ValidationFailed: 422,
    NotAuthenticated: 401,
    Forbidden: 403,
    NotFound: 404,
    Conflict: 409,
    IllegalTransition: 409,
}

HTTP_CODES = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def error_body(code: str, message: str, details: list[dict[str, str]] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api")


def _field_from_loc(err: dict[str, Any]) -> str:
    ctx = err.get("ctx") or {}
    if err.get("type") == "dependent_field" and "field" in ctx:
        return str(ctx["field"])
    loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
    return ".".join(loc) or "body"


def install_error_handlers(
    app: FastAPI, html_renderer: Callable[[Request, DomainError], Response] | None = None
) -> None:
    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> Response:
        status = STATUS_FOR.get(type(exc), 500)
        if not _is_api(request):
            if isinstance(exc, NotAuthenticated):
                return RedirectResponse("/login", status_code=303)
            if html_renderer is not None:
                return html_renderer(request, exc)  # logs permission_denied itself
        if isinstance(exc, Forbidden):
            log_event("permission_denied", logging.WARNING, route=request.url.path, reason=exc.message)
        details = (
            [{"field": exc.field, "message": exc.message}] if isinstance(exc, ValidationFailed) else None
        )
        return JSONResponse(error_body(exc.code, exc.message, details), status_code=status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        details = [
            {"field": _field_from_loc(dict(err)), "message": str(err.get("msg", "Invalid value"))}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("VALIDATION_ERROR", "Request validation failed", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        code = HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> Response:
        log_exception("unhandled_exception", route=request.url.path)
        request_id = getattr(request.state, "request_id", None)
        body = error_body("INTERNAL_ERROR", "An unexpected error occurred")
        body["error"]["request_id"] = request_id
        return JSONResponse(body, status_code=500)
