# LEMMS – Laboratory Equipment & Maintenance Management System

System under test for CPS6002 Assessment 2. Requirements live in [`docs/SPEC.md`](docs/SPEC.md):
every business rule in the code cites a REQ ID from there.

## Quick start

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                 # optional; all settings have defaults
python -m app.seed                   # synthetic data; prints the generated password
uvicorn app.main:app --reload        # http://127.0.0.1:8000
```

Seed users (all share the printed password, or `LEMMS_SEED_PASSWORD` if set):

| Username | Role |
|---|---|
| admin1 | admin |
| tech1, tech2 | technician |
| academic1, academic2 | academic |

Re-seed from scratch with `python -m app.seed --reset`.

## Useful URLs
- UI: `/` (log in at `/login`)
- API docs (OpenAPI/Swagger): `/docs`
- Health: `/health` · Prometheus metrics: `/metrics`

## Quality commands
```bash
ruff check .          # lint
mypy app              # strict type check
pytest                # tests (to be written by the team from SPEC.md)
```

## Architecture
```
app/
  domain/        pure business rules: no DB, no HTTP, no clock calls
    status.py        equipment state machine (transition table)
    permissions.py   role -> action matrix
    booking.py       booking window rules + conflict detection
    maintenance.py   task lifecycle + overdue rule
    faults.py        fault lifecycle
  services/      orchestrate domain + repositories, own transactions
  repositories/  SQLAlchemy models and queries
  api/           JSON REST routes (/api/...), schemas, error mapping
  web/           server-rendered HTML (Jinja2) using the same services
  clock.py       Clock protocol: SystemClock / FixedClock (inject in tests)
  logging.py     JSON logs + X-Request-ID middleware
  seed.py        synthetic seed data
```

## Testing hooks
- `create_app(settings=Settings("sqlite://", ...), clock=FixedClock(datetime(...)))` gives an isolated
  in-memory app with a controllable clock.
- Every response carries `X-Request-ID`; logs are JSON on stdout, one line per request plus
  `auth_failure`, `permission_denied`, `status_transition` and `booking_conflict` events.
- Errors use one shape: `{"error": {"code", "message", "details"?}}` (see SPEC 1.3).
