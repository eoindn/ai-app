# LEMMS – Laboratory Equipment & Maintenance Management System

This app is a **system under test** for a software testing module (CPS6002).
Testability matters more than features. Keep it simple, explicit and deterministic.

## Stack
- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, SQLite (file DB; in-memory for tests)
- Server-rendered UI: Jinja2 templates + a little HTMX. No SPA framework.
- Auth: session cookie, passwords hashed with bcrypt. Roles: `admin`, `technician`, `academic`.
- Tooling: uv (or pip + requirements.txt), ruff, mypy, pytest.

## Architecture (strict layering)
```
app/
  domain/        # PURE logic: no DB, no HTTP, no datetime.now(). Business rules live here.
    booking.py       # conflict detection
    status.py        # equipment status state machine (explicit transition table)
    maintenance.py   # overdue calculation
    permissions.py   # role -> action permission matrix (explicit table)
  services/      # orchestrates domain + repositories, raises domain exceptions
  repositories/  # SQLAlchemy data access only
  api/           # JSON REST routes (FastAPI routers)
  web/           # HTML routes + templates
  clock.py       # Clock protocol; SystemClock and FixedClock. ALWAYS inject, never call now() directly.
  logging.py     # structured JSON logs + request-ID middleware
  seed.py        # synthetic seed data: `python -m app.seed`
docs/SPEC.md     # requirements with IDs (REQ-INV-01 etc.) – source of truth
```
- Every business rule must be traceable to a REQ ID in `docs/SPEC.md`. Put the REQ ID in the function docstring.
- Status transitions and permissions are **data tables**, not scattered if-statements.
- Validation errors return 422 with a clear message; permission failures 403; not found 404; conflicts 409.

## Observability
- JSON logs with `request_id`, `user_id`, `role`, `route`, `status_code`, `duration_ms`.
- Always log: auth failures, permission denials, status transitions (from -> to), booking conflicts.
- `/health` endpoint. `/metrics` via prometheus-fastapi-instrumentator.

## Git workflow (non-negotiable)
- Never commit to `main`. One branch per GitHub issue: `feat/<issue#>-short-slug` or `fix/<issue#>-short-slug`.
- Conventional commits (`feat:`, `fix:`, `test:`, `ci:`, `docs:`, `refactor:`), small and focused.
- Finish work by opening a PR with `gh pr create`, body includes `Closes #<issue>` and the REQ IDs touched.
- Do not merge PRs yourself. A human reviews and merges.

## Testing rules (important – read twice)
- **Do not write tests unless the task explicitly asks for tests.** Tests are designed by the humans from SPEC.md.
- **Never modify an existing test to make it pass.** If a test fails, stop and report: test name, failure, your hypothesis.
- If you notice a bug while doing something else, **do not silently fix it**. Use the `defect-report` skill to file an issue.
- Seed data must be synthetic. No real names/emails. No secrets in the repo; config via env vars with `.env.example`.

## Accessibility
- Semantic HTML, every input has a `<label>`, visible focus states, form errors announced (`aria-live`),
  sufficient colour contrast. Aim for WCAG 2.2 AA.

## Commands
- Run: `uvicorn app.main:app --reload`
- Seed: `python -m app.seed`
- Lint/type: `ruff check . && mypy app`
- Tests: `pytest`
