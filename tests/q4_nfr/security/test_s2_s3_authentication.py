"""S2 – Unauthenticated access (OWASP A01/A07), REQ-ROLE-01. Risk: High. Issue #2.
S3 – Session expiry and logout (OWASP A07), REQ-ROLE-03. Risk: High. Issue #2.

S2 technique: endpoint sweep. The route list is read from the app itself at collection time,
so a newly added endpoint is tested automatically (no hand-maintained list to fall out of date).
Path parameters use IDs that do not exist: SPEC §1.3 says authentication (401) is checked
before existence (404), so a 401 also confirms that order.

S3 technique: boundary value analysis on session age using the injected FixedClock.
Sessions expire LEMMS_SESSION_HOURS after login (default 8). The boundary is tested at
8 h − 1 s (valid), 8 h (expired) and 8 h + 1 s (expired).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.deps import SESSION_COOKIE
from app.api.routes import router as api_router
from app.clock import FixedClock
from app.config import Settings
from app.web.routes import router as web_router
from tests.conftest import NOW

pytestmark = pytest.mark.security

# Endpoints that are public by design (REQ-ROLE-01, REQ-DATA-08).
PUBLIC_API = {("POST", "/api/auth/login")}
PUBLIC_WEB = {("GET", "/login"), ("POST", "/login")}

# Values for path parameters; none of these resources exist in the empty test DB.
PARAM_VALUES = {
    "equipment_id": "EQ-99999",
    "booking_id": "999",
    "fault_id": "999",
    "task_id": "999",
    "op": "start",
}


def _routes(router: APIRouter) -> list[tuple[str, str]]:
    """(method, path) for every route on a router.

    Read from the routers rather than `app.routes`: this FastAPI version nests included routers
    in a private wrapper, and the HTML router is excluded from the OpenAPI schema. Reading
    `app.routes` found 0 API routes, which test_route_discovery_is_not_empty caught.
    """
    return sorted(
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods - {"HEAD"}
    )


def _fill(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: PARAM_VALUES[m.group(1)], path)


API_ROUTES = [r for r in _routes(api_router) if r not in PUBLIC_API]
WEB_ROUTES = [r for r in _routes(web_router) if r not in PUBLIC_WEB]


# ------------------------------------------------------------------ S2


def test_route_discovery_is_not_empty() -> None:
    """Guard: if discovery silently found nothing, every sweep below would pass vacuously."""
    assert len(API_ROUTES) >= 30
    assert len(WEB_ROUTES) >= 15


@pytest.mark.parametrize(("method", "path"), API_ROUTES, ids=[f"{m} {p}" for m, p in API_ROUTES])
def test_api_requires_session(method: str, path: str, anon_client: TestClient) -> None:
    """REQ-ROLE-01: no session → 401 UNAUTHENTICATED on every non-public /api endpoint."""
    resp = anon_client.request(method, _fill(path))
    assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}: {resp.text}"
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(("method", "path"), API_ROUTES, ids=[f"{m} {p}" for m, p in API_ROUTES])
def test_api_rejects_forged_session_cookie(method: str, path: str, app: FastAPI) -> None:
    """REQ-ROLE-01/03: a cookie value that is not a server-side session is treated as no session."""
    with TestClient(app, cookies={SESSION_COOKIE: "forged-token-value"}) as client:
        resp = client.request(method, _fill(path))
    assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"


@pytest.mark.parametrize(("method", "path"), WEB_ROUTES, ids=[f"{m} {p}" for m, p in WEB_ROUTES])
def test_html_pages_redirect_to_login(method: str, path: str, anon_client: TestClient) -> None:
    """REQ-ROLE-01: HTML pages redirect to /login instead of returning 401."""
    resp = anon_client.request(method, _fill(path), follow_redirects=False)
    assert resp.status_code in (302, 303), f"{method} {path} returned {resp.status_code}"
    assert resp.headers["location"].endswith("/login")


def test_health_is_public(anon_client: TestClient) -> None:
    """REQ-DATA-08: /health needs no authentication."""
    assert anon_client.get("/health").status_code == 200


# ------------------------------------------------------------------ S3

SESSION_HOURS = 8


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        pytest.param(timedelta(hours=SESSION_HOURS) - timedelta(seconds=1), 200, id="8h-1s valid"),
        pytest.param(timedelta(hours=SESSION_HOURS), 401, id="8h exactly expired"),
        pytest.param(timedelta(hours=SESSION_HOURS) + timedelta(seconds=1), 401, id="8h+1s expired"),
    ],
)
def test_session_expiry_boundary(
    age: timedelta, expected: int, clock: FixedClock, client_as: Callable[[str], TestClient]
) -> None:
    """REQ-ROLE-03: sessions expire LEMMS_SESSION_HOURS after login, on the injected clock."""
    client = client_as("academic")  # logs in at NOW
    clock.set(NOW + age)
    resp = client.get("/api/auth/me")
    assert resp.status_code == expected, resp.text
    if expected == 401:
        assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_session_hours_setting_is_honoured(
    app: FastAPI, settings: Settings, clock: FixedClock, client_as: Callable[[str], TestClient]
) -> None:
    """REQ-ROLE-03: the lifetime comes from LEMMS_SESSION_HOURS, not a hard-coded 8."""
    app.state.settings = replace(settings, session_hours=1)  # read by the login route
    client = client_as("academic")
    clock.set(NOW + timedelta(hours=1))
    assert client.get("/api/auth/me").status_code == 401


def test_logout_invalidates_session_server_side(app: FastAPI, client_as: Callable[[str], TestClient]) -> None:
    """REQ-ROLE-03: after logout, replaying the old cookie value → 401.

    The test client drops the cookie on logout, so the old value is captured first and replayed
    from a fresh client. This simulates an attacker who stole the cookie before logout.
    """
    client = client_as("academic")
    stolen = client.cookies[SESSION_COOKIE]
    assert client.post("/api/auth/logout").status_code == 204

    with TestClient(app, cookies={SESSION_COOKIE: stolen}) as attacker:
        resp = attacker.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_logout_only_ends_own_session(client_as: Callable[[str], TestClient]) -> None:
    """REQ-ROLE-03: logging out one session must not end another user's session."""
    a, b = client_as("academic"), client_as("technician")
    a.post("/api/auth/logout")
    assert b.get("/api/auth/me").status_code == 200
