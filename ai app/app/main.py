"""Application factory. Tests call create_app(settings=..., clock=FixedClock(...))."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from app.api.errors import install_error_handlers
from app.api.routes import router as api_router
from app.clock import Clock, SystemClock
from app.config import Settings, load_settings
from app.db import Base, make_engine, make_sessionmaker
from app.logging import RequestContextMiddleware, configure_logging
from app.repositories import models  # noqa: F401  (registers tables on Base.metadata)
from app.web.routes import render_error
from app.web.routes import router as web_router

STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    database_url: str | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    if database_url is not None:
        settings = replace(settings, database_url=database_url)
    configure_logging()

    app = FastAPI(title="LEMMS", version="0.1.0")
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.clock = clock or SystemClock()

    install_error_handlers(app, html_renderer=render_error)
    app.include_router(api_router)
    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health")
    def health(request: Request) -> JSONResponse:
        """REQ-DATA-08."""
        try:
            with request.app.state.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    Instrumentator().instrument(app).expose(app, include_in_schema=False)
    app.add_middleware(RequestContextMiddleware)
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """`uvicorn app.main:app` builds the app lazily, so importing this module has no side effects."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
