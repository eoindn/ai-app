# LEMMS – Software Requirements Specification

Laboratory Equipment & Maintenance Management System. Version 0.1 (draft).

This document is the **source of truth** for LEMMS behaviour. Every business rule in the code cites
a REQ ID from this file. Tests should be derived from this file, not from the code.

> **Status of decisions.** Section 8 lists the decisions that had to be made to build the app.
> Each one is implemented using the *recommended* option and is marked **PROVISIONAL** until the
> group confirms it. Changing a decision means updating this file first, then the code.

---

## 1. System overview

LEMMS manages laboratory equipment across a university's teaching and research labs: an equipment
inventory, bookings, fault reports, maintenance tasks and summary reports. It is a single web
application (JSON REST API under `/api` plus a server-rendered HTML UI) backed by a SQLite database.

It exists as a **system under test** for CPS6002, so rules are explicit, deterministic and small.

**Out of scope:** email or notifications, file uploads, external services or CDNs, recurring bookings,
multiple sites, password reset, account deletion, rate limiting.

### 1.1 Roles

| Role | Who | Summary |
|---|---|---|
| `admin` | Lab administrator | Full control: equipment CRUD, users, scheduling and assigning maintenance, cancelling any booking, returning equipment to service. |
| `technician` | Lab technician | Operates equipment status (check-out, return, out of service), works faults, works maintenance tasks assigned to them, views reports. |
| `academic` | Academic staff | Searches equipment, books equipment, manages their own bookings, reports faults. |

### 1.2 Conventions

- **Time.** All instants are stored in UTC. The lab's local timezone is `Europe/London`. "Today" and
  all calendar-date rules use the local date in `Europe/London`. All rules that depend on the current
  time use the application's injected clock (`app/clock.py`), never the system clock directly.
- **API datetimes** are ISO-8601 strings **with** a UTC offset (e.g. `2026-12-01T10:00:00Z` or
  `2026-12-01T10:00:00+00:00`). Datetimes without an offset are rejected (422).
- **API dates** are `YYYY-MM-DD`.
- **Strings** have leading and trailing whitespace stripped **before** validation. Length limits
  apply to the stripped value and count characters (not bytes).
- **Unknown fields** in a request body are rejected (422).

### 1.3 Error contract

Every error response has this JSON shape:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "human readable", "details": [ { "field": "name", "message": "..." } ] } }
```

`details` is present only for validation errors. Tests should assert on HTTP status and `code`,
not on the exact `message` text.

| HTTP | `code` | When |
|---|---|---|
| 401 | `UNAUTHENTICATED` | No valid session, or login failed. |
| 403 | `FORBIDDEN` | Authenticated but the role / ownership rule does not allow the action. |
| 404 | `NOT_FOUND` | The referenced resource does not exist. |
| 409 | `CONFLICT` | The request clashes with existing data (duplicate ID, overlapping booking, delete blocked, booking already started, etc.). |
| 409 | `ILLEGAL_TRANSITION` | A status change not allowed from the current state (equipment, fault or maintenance task). |
| 422 | `VALIDATION_ERROR` | Input fails the rules in section 6. |
| 500 | `INTERNAL_ERROR` | Unexpected failure. The body never contains a stack trace. |

**Order of checks** (so tests can predict which error wins): authentication (401) → request-body
validation (422) → permission by role (403) → resource exists (404) → ownership (403) → business
rules (409 / 422).

---

## 2. Functional requirements

### 2.1 Equipment inventory (REQ-INV)

| ID | Requirement |
|---|---|
| REQ-INV-01 | An `admin` can create equipment with `equipment_id`, `name`, `location` and optional `description` (rules in section 6.2). On success the API returns **201** with the record, and its `status` is `AVAILABLE`. |
| REQ-INV-02 | `equipment_id` is unique. Creating equipment whose `equipment_id` already exists returns **409 CONFLICT**. The comparison is case-sensitive; the format rule (section 6.2) only allows uppercase anyway. |
| REQ-INV-03 | `status` cannot be set on create or update. Including `status` (or any other unknown field) in the body returns **422**. Status changes only through the events in section 3. |
| REQ-INV-04 | Any authenticated user can view a single equipment record with `GET /api/equipment/{equipment_id}`. An unknown ID returns **404**. |
| REQ-INV-05 | An `admin` can update `name`, `location` and `description` with `PATCH`. Omitted fields are left unchanged. `equipment_id` cannot be changed (including it → **422**). Sending an empty body is valid and changes nothing. |
| REQ-INV-06 | An `admin` can delete equipment, which returns **204**. Deleting is blocked with **409 CONFLICT** if **any** booking, fault or maintenance task, in any status, references that equipment. Deleting also removes the equipment's status history. |
| REQ-INV-07 | Any authenticated user can search with `GET /api/equipment`, using optional parameters `q`, `status`, `limit` and `offset`. `q` is a case-insensitive substring match against `equipment_id`, `name` and `location`; a record matches if any of the three contains `q`. `status` filters exactly; an invalid status value → **422**. Results are sorted by `equipment_id` ascending. |
| REQ-INV-08 | `limit` is an integer from 1 to 100 (default 50). `offset` is an integer ≥ 0 (default 0). Values out of range → **422**. The response is `{ "total": <matches before paging>, "items": [...] }`. |
| REQ-INV-09 | `technician` and `academic` users get **403** on create, update and delete. |

### 2.2 Equipment booking (REQ-BOOK)

A booking reserves one piece of equipment for one user over a half-open interval `[start, end)`.
Booking statuses: `CONFIRMED`, `CANCELLED`.

| ID | Requirement |
|---|---|
| REQ-BOOK-01 | Any authenticated user (all three roles) can create a booking with `equipment_id`, `start`, `end` and `purpose`. On success → **201**, `status` = `CONFIRMED`, and `user_id` is the caller. A user cannot book on behalf of someone else. |
| REQ-BOOK-02 | `end` must be strictly after `start`. Otherwise → **422** (field `end`). |
| REQ-BOOK-03 | Duration (`end − start`) must be **at least 30 minutes** and **at most 8 hours**, both limits inclusive. Otherwise → **422**. *(Decision OD-2.)* |
| REQ-BOOK-04 | `start` and `end` must fall on a 15-minute boundary: minutes ∈ {00, 15, 30, 45}, with seconds and fractional seconds equal to 0. Otherwise → **422**. *(Decision OD-2.)* |
| REQ-BOOK-05 | `start` must not be in the past: `start ≥ now`. Otherwise → **422** (field `start`). |
| REQ-BOOK-06 | `start` must be no more than 30 days ahead: `start ≤ now + 30 days` (inclusive). Otherwise → **422** (field `start`). *(Decision OD-2.)* |
| REQ-BOOK-07 | **No overlaps.** A new booking conflicts with an existing `CONFIRMED` booking for the same equipment when `new.start < existing.end AND existing.start < new.end`. A conflict → **409 CONFLICT**. A booking ending at 10:00 does **not** conflict with one starting at 10:00. `CANCELLED` bookings never conflict. *(Decision OD-1.)* |
| REQ-BOOK-08 | Equipment whose status is `OUT_OF_SERVICE` cannot be booked → **409 CONFLICT**. Equipment that is `AVAILABLE`, `BOOKED` or `UNDER_MAINTENANCE` can be booked for a future slot, subject to the other rules. |
| REQ-BOOK-09 | Equipment with at least one fault that is `OPEN` or `IN_PROGRESS` **and** of severity `HIGH` or `CRITICAL` cannot be booked → **409 CONFLICT**. Faults of severity `LOW` or `MEDIUM` do not block booking. *(Decision OD-3.)* |
| REQ-BOOK-10 | Booking an unknown `equipment_id` → **404**. |
| REQ-BOOK-11 | `GET /api/bookings?scope=mine` (the default) returns the caller's own bookings. `scope=all` returns every booking and is allowed only for `admin` and `technician`; an `academic` gets **403**. Results are sorted by `start` ascending. |
| REQ-BOOK-12 | `GET /api/bookings/{id}`: the owner, any `admin` and any `technician` may view it. Another `academic` gets **403**. An unknown ID → **404**. |
| REQ-BOOK-13 | **Cancel.** `POST /api/bookings/{id}/cancel` sets the status to `CANCELLED` and records `cancelled_at`, `cancelled_by` and `cancel_reason` = `USER_CANCELLED`. The owner may cancel their own booking. An `admin` may cancel anyone's. A `technician` may cancel only their own. Otherwise → **403**. |
| REQ-BOOK-14 | A booking can only be cancelled while `CONFIRMED` and before it has started (`now < start`). Cancelling an already-cancelled booking, or one that has started (`now ≥ start`), → **409 CONFLICT**. |
| REQ-BOOK-15 | `GET /api/equipment/{equipment_id}/bookings` returns that equipment's `CONFIRMED` bookings with `end > now`, sorted by `start`, to any authenticated user. For an `academic` caller, the `user_id` and `purpose` of bookings that are **not their own** are returned as `null`. *(privacy)* |
| REQ-BOOK-16 | Two simultaneous requests for overlapping slots must not both succeed: the conflict check and the insert happen atomically, so at most one booking is created. |

### 2.3 Fault reporting (REQ-FAULT)

Fault statuses: `OPEN`, `IN_PROGRESS`, `RESOLVED`. Severities: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.

| ID | Requirement |
|---|---|
| REQ-FAULT-01 | Any authenticated user can report a fault with `equipment_id`, `title`, `description` and `severity`. On success → **201**, `status` = `OPEN`, and `reported_by` and `reported_at` (now) are recorded. |
| REQ-FAULT-02 | Reporting against an unknown `equipment_id` → **404**. Faults can be reported against equipment in any status. |
| REQ-FAULT-03 | Any authenticated user can list faults (`GET /api/faults`, optional `status`, `severity` and `equipment_id` filters) and view a single fault. Results are sorted by `reported_at` ascending (oldest first). |
| REQ-FAULT-04 | The fault lifecycle follows the table in section 3.2. Only `admin` and `technician` may change fault status. An `academic` → **403**. An illegal transition → **409 ILLEGAL_TRANSITION**. |
| REQ-FAULT-05 | Resolving (`IN_PROGRESS → RESOLVED`) requires `resolution_notes` (5–1000 characters) and records `resolved_by` and `resolved_at`. |
| REQ-FAULT-06 | Reporting a fault, of any severity, does **not** automatically change equipment status. *(Decision OD-9.)* |

### 2.4 Maintenance management (REQ-MAINT)

Task statuses: `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`.

| ID | Requirement |
|---|---|
| REQ-MAINT-01 | An `admin` can schedule a maintenance task with `equipment_id`, `title`, optional `description`, `due_date` and `assigned_technician_id`. On success → **201**, `status` = `SCHEDULED`. Other roles → **403**. |
| REQ-MAINT-02 | `assigned_technician_id` must be the ID of an existing, active user whose role is `technician`. Otherwise → **422** (field `assigned_technician_id`). |
| REQ-MAINT-03 | `due_date`, at creation, must be today or later (local date). A past date → **422**. |
| REQ-MAINT-04 | An `admin` can reassign a `SCHEDULED` or `IN_PROGRESS` task with `POST /api/maintenance/{id}/assign`. The same rule as REQ-MAINT-02 applies. Reassigning a `COMPLETED` or `CANCELLED` task → **409 ILLEGAL_TRANSITION**. |
| REQ-MAINT-05 | **Start** (`SCHEDULED → IN_PROGRESS`): allowed for the assigned technician or any `admin`; another technician → **403**. The equipment must currently be `AVAILABLE`, otherwise → **409 ILLEGAL_TRANSITION**. On success the equipment becomes `UNDER_MAINTENANCE` (event `start_maintenance`). |
| REQ-MAINT-06 | **Complete** (`IN_PROGRESS → COMPLETED`): allowed for the assigned technician or any `admin`. Optional `completion_notes` (≤ 1000 characters). Records `completed_at` and `completed_by`. If the equipment is `UNDER_MAINTENANCE` it becomes `AVAILABLE` (event `complete_maintenance`). If it is `OUT_OF_SERVICE`, its status is left unchanged. |
| REQ-MAINT-07 | **Cancel** (`SCHEDULED → CANCELLED`): `admin` only. An `IN_PROGRESS` task cannot be cancelled → **409 ILLEGAL_TRANSITION**. |
| REQ-MAINT-08 | **Overdue.** A task is overdue when its status is `SCHEDULED` or `IN_PROGRESS` **and** today's local date (Europe/London) is **strictly after** `due_date`. A task is *not* overdue on its due date. `COMPLETED` and `CANCELLED` tasks are never overdue. Every task response includes a computed boolean `is_overdue`. *(Decision OD-4.)* |
| REQ-MAINT-09 | `GET /api/maintenance` (`admin`, `technician`) supports filters `status`, `equipment_id`, `assigned_technician_id` and `overdue=true\|false`. Results are sorted by `due_date` ascending, then `id`. An `academic` → **403**. |
| REQ-MAINT-10 | A technician may be assigned any number of tasks, including tasks with the same due date. *(Decision OD-11.)* |

### 2.5 Equipment status (REQ-STAT)

| ID | Requirement |
|---|---|
| REQ-STAT-01 | Equipment status is one of `AVAILABLE`, `BOOKED`, `UNDER_MAINTENANCE`, `OUT_OF_SERVICE`. New equipment starts `AVAILABLE`. |
| REQ-STAT-02 | Status changes **only** by the events in the transition table (section 3.1). Any other (state, event) pair → **409 ILLEGAL_TRANSITION**, and the status is unchanged. |
| REQ-STAT-03 | Each transition lists the roles allowed to trigger it. A role not listed → **403**, and the status is unchanged. The role check happens before the state check. |
| REQ-STAT-04 | `POST /api/equipment/{equipment_id}/status` with `{ "event": ..., "booking_id"?: int, "reason"?: str }` triggers the manual events `check_out`, `return`, `take_out_of_service` and `return_to_service`. The events `start_maintenance` and `complete_maintenance` can only be triggered through maintenance tasks (REQ-MAINT-05/06). Sending them here → **422**. |
| REQ-STAT-05 | `check_out` requires `booking_id` pointing to a `CONFIRMED` booking for **the same equipment** whose interval contains now (`start ≤ now < end`). Missing `booking_id` → **422**. Unknown booking → **404**. Wrong equipment, cancelled, or outside its interval → **409 CONFLICT**. *(Decision OD-7.)* |
| REQ-STAT-06 | `take_out_of_service` requires `reason` (5–500 characters). When it succeeds, every `CONFIRMED` booking for that equipment with `end > now` is set to `CANCELLED` with `cancel_reason` = `EQUIPMENT_OUT_OF_SERVICE`, all in the same transaction. *(Decision OD-5.)* |
| REQ-STAT-07 | Every successful transition is recorded in the status history with equipment, `from_status`, `to_status`, `event`, `user_id`, timestamp (now) and optional `reason`. `GET /api/equipment/{equipment_id}/history` returns it, newest first, to `admin` and `technician`. An `academic` → **403**. |

### 2.6 User roles and authentication (REQ-ROLE)

| ID | Requirement |
|---|---|
| REQ-ROLE-01 | Every `/api` endpoint except `POST /api/auth/login` and `/health` requires an authenticated session. Without one → **401**. HTML pages redirect to `/login` instead. |
| REQ-ROLE-02 | `POST /api/auth/login` with `{username, password}` sets a session cookie and returns the user (`id`, `username`, `display_name`, `role`). A wrong password, unknown username or inactive user → **401** with the same body in every case (no user enumeration). |
| REQ-ROLE-03 | Sessions are stored server-side and expire `LEMMS_SESSION_HOURS` (default 8) hours after login, measured on the injected clock; an expired session → **401**. `POST /api/auth/logout` deletes the session, so later requests with the old cookie → **401**. `GET /api/auth/me` returns the current user. |
| REQ-ROLE-04 | Passwords are stored only as bcrypt hashes and never appear in any response or log. |
| REQ-ROLE-05 | Every action is authorised server-side against the permission matrix (section 4), whatever the UI shows. |
| REQ-ROLE-06 | An `admin` can list users (`GET /api/users`, optional `role` filter) and create users (`POST /api/users`, rules in section 6.1). Duplicate `username` → **409**. Other roles → **403**. |
| REQ-ROLE-07 | The session cookie is `HttpOnly` and `SameSite=Lax`. |

### 2.7 Reporting (REQ-REP)

All reports are available to `admin` and `technician`. An `academic` → **403**.

| ID | Requirement |
|---|---|
| REQ-REP-01 | `GET /api/reports/availability` returns `{ "total": n, "by_status": { "AVAILABLE": a, "BOOKED": b, "UNDER_MAINTENANCE": c, "OUT_OF_SERVICE": d } }`. All four keys are always present (0 if none), and `a + b + c + d = total`. |
| REQ-REP-02 | `GET /api/reports/faults` returns outstanding faults (status `OPEN` or `IN_PROGRESS`): `{ "total_outstanding": n, "by_severity": {LOW, MEDIUM, HIGH, CRITICAL}, "faults": [...] }`. All four severity keys are always present, and `faults` is sorted oldest `reported_at` first. `RESOLVED` faults are excluded. |
| REQ-REP-03 | `GET /api/reports/maintenance?from=YYYY-MM-DD&to=YYYY-MM-DD` returns `overdue` (all overdue tasks, per REQ-MAINT-08), `upcoming` (tasks with status `SCHEDULED` or `IN_PROGRESS` and today ≤ `due_date` ≤ today + 7 days) and `completed_count` (tasks whose `completed_at` local date lies in `[from, to]`, inclusive). Defaults: `to` = today, `from` = `to − 30 days`. `from > to` → **422**. |

### 2.8 Data management (REQ-DATA)

| ID | Requirement |
|---|---|
| REQ-DATA-01 | All data is persisted in a SQLite database file (path from `LEMMS_DATABASE_URL`, default `sqlite:///./lemms.db`) and survives an application restart. |
| REQ-DATA-02 | All input is validated against section 6. A failure → **422** with one `details` entry per invalid field. |
| REQ-DATA-03 | Unknown request-body fields → **422** (REQ-INV-03). Malformed JSON → **422**. |
| REQ-DATA-04 | Unexpected errors → **500** `INTERNAL_ERROR` with a generic message and the `request_id`. No stack traces, SQL or file paths in the response. |
| REQ-DATA-05 | Operations that change several records (taking equipment out of service and cancelling bookings; starting or completing maintenance and changing equipment status) are atomic: either every change is saved or none is. |
| REQ-DATA-06 | Every response carries an `X-Request-ID` header. If the client sends a valid `X-Request-ID` (1–64 characters of `[A-Za-z0-9._-]`) it is echoed; otherwise a new UUID4 is generated. |
| REQ-DATA-07 | The app writes one JSON log line per request with `request_id`, `user_id`, `role`, `method`, `route`, `status_code` and `duration_ms`. It additionally logs the events `auth_failure`, `permission_denied`, `status_transition` (with `equipment_id`, `status_event`, `from_status`, `to_status`) and `booking_conflict`. |
| REQ-DATA-08 | `GET /health` returns **200** `{"status": "ok"}` when the database is reachable, without authentication. `GET /metrics` exposes Prometheus metrics. |
| REQ-DATA-09 | Seed data (`python -m app.seed`) is synthetic only: no real names or emails, and no passwords committed to the repository. |

---

## 3. State-transition tables

### 3.1 Equipment status

| # | From | Event | To | Roles allowed | Extra rule |
|---|---|---|---|---|---|
| T1 | AVAILABLE | `check_out` | BOOKED | admin, technician | REQ-STAT-05 (active booking) |
| T2 | BOOKED | `return` | AVAILABLE | admin, technician | – |
| T3 | AVAILABLE | `start_maintenance` | UNDER_MAINTENANCE | admin, technician | via maintenance task only (REQ-MAINT-05) |
| T4 | UNDER_MAINTENANCE | `complete_maintenance` | AVAILABLE | admin, technician | via maintenance task only (REQ-MAINT-06) |
| T5 | AVAILABLE | `take_out_of_service` | OUT_OF_SERVICE | admin, technician | reason required; cancels future bookings (REQ-STAT-06) |
| T6 | BOOKED | `take_out_of_service` | OUT_OF_SERVICE | admin, technician | as T5 |
| T7 | UNDER_MAINTENANCE | `take_out_of_service` | OUT_OF_SERVICE | admin, technician | as T5 |
| T8 | OUT_OF_SERVICE | `return_to_service` | AVAILABLE | **admin only** | – |

**Illegal transitions.** Every (from, event) pair not listed above is illegal → 409 ILLEGAL_TRANSITION. In full:

| From \ Event | check_out | return | start_maintenance | complete_maintenance | take_out_of_service | return_to_service |
|---|---|---|---|---|---|---|
| AVAILABLE | ✅ T1 | ❌ | ✅ T3 | ❌ | ✅ T5 | ❌ |
| BOOKED | ❌ | ✅ T2 | ❌ | ❌ | ✅ T6 | ❌ |
| UNDER_MAINTENANCE | ❌ | ❌ | ❌ | ✅ T4 | ✅ T7 | ❌ |
| OUT_OF_SERVICE | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ T8 |

Notable illegal cases: BOOKED → UNDER_MAINTENANCE (equipment must be returned first);
OUT_OF_SERVICE → BOOKED; OUT_OF_SERVICE → UNDER_MAINTENANCE; any self-transition (for example
`take_out_of_service` on OUT_OF_SERVICE); an `academic` triggering any event (403, rule REQ-STAT-03).

### 3.2 Fault status

| From | Event | To | Roles |
|---|---|---|---|
| OPEN | `start` | IN_PROGRESS | admin, technician |
| IN_PROGRESS | `resolve` | RESOLVED | admin, technician (notes required) |

Illegal: OPEN → RESOLVED directly, anything from RESOLVED, and any self-transition.

### 3.3 Maintenance task status

| From | Event | To | Roles |
|---|---|---|---|
| SCHEDULED | `start` | IN_PROGRESS | admin, assigned technician |
| IN_PROGRESS | `complete` | COMPLETED | admin, assigned technician |
| SCHEDULED | `cancel` | CANCELLED | admin |

Illegal: IN_PROGRESS → CANCELLED, SCHEDULED → COMPLETED, anything from COMPLETED or CANCELLED.

---

## 4. Permission matrix

✅ allowed · ❌ 403 · **own** = only records where the caller is the owner (bookings) or the assignee (maintenance).

| Action | admin | technician | academic | REQ |
|---|---|---|---|---|
| View / search equipment | ✅ | ✅ | ✅ | INV-04, INV-07 |
| Create equipment | ✅ | ❌ | ❌ | INV-01 |
| Update equipment | ✅ | ❌ | ❌ | INV-05 |
| Delete equipment | ✅ | ❌ | ❌ | INV-06 |
| Change equipment status (check_out, return, take_out_of_service) | ✅ | ✅ | ❌ | STAT-03 |
| Return equipment to service | ✅ | ❌ | ❌ | STAT-03 |
| View equipment status history | ✅ | ✅ | ❌ | STAT-07 |
| Create booking (for self) | ✅ | ✅ | ✅ | BOOK-01 |
| View own bookings | ✅ | ✅ | ✅ | BOOK-11 |
| View all bookings | ✅ | ✅ | ❌ | BOOK-11 |
| Cancel own booking | ✅ | ✅ | ✅ | BOOK-13 |
| Cancel another user's booking | ✅ | ❌ | ❌ | BOOK-13 |
| View equipment schedule (others' identity) | ✅ | ✅ | masked | BOOK-15 |
| Report fault | ✅ | ✅ | ✅ | FAULT-01 |
| View faults | ✅ | ✅ | ✅ | FAULT-03 |
| Start / resolve fault | ✅ | ✅ | ❌ | FAULT-04 |
| View maintenance tasks | ✅ | ✅ | ❌ | MAINT-09 |
| Schedule maintenance | ✅ | ❌ | ❌ | MAINT-01 |
| Assign / reassign technician | ✅ | ❌ | ❌ | MAINT-04 |
| Start / complete maintenance task | ✅ | own | ❌ | MAINT-05, 06 |
| Cancel maintenance task | ✅ | ❌ | ❌ | MAINT-07 |
| View reports | ✅ | ✅ | ❌ | REP-01..03 |
| List / create users | ✅ | ❌ | ❌ | ROLE-06 |

---

## 5. Data model (summary)

| Entity | Key fields |
|---|---|
| User | id, username, display_name, role, password_hash, is_active |
| Equipment | id (internal), equipment_id (public), name, description, location, status, created_at, updated_at |
| Booking | id, equipment_id, user_id, start, end, purpose, status, created_at, cancelled_at, cancelled_by, cancel_reason |
| Fault | id, equipment_id, title, description, severity, status, reported_by, reported_at, resolution_notes, resolved_by, resolved_at |
| MaintenanceTask | id, equipment_id, title, description, due_date, assigned_technician_id, status, created_by, created_at, started_at, completed_at, completed_by, completion_notes |
| StatusChange | id, equipment_id, from_status, to_status, event, user_id, reason, changed_at |

---

## 6. Validation rules

All failures return **422 VALIDATION_ERROR** with a `details` entry naming the field.

### 6.1 User (`POST /api/users`, `POST /api/auth/login`)

| Field | Type | Req. | Rules | Error if invalid |
|---|---|---|---|---|
| username | string | yes | 3–30 chars, `^[a-z0-9_]+$`, unique | 422; duplicate → 409 |
| display_name | string | yes | 2–60 chars | 422 |
| role | enum | yes | `admin` \| `technician` \| `academic` | 422 |
| password | string | yes | 8–64 chars (create); 1–128 chars (login) | 422 |

### 6.2 Equipment

| Field | Type | Req. | Rules | Error if invalid |
|---|---|---|---|---|
| equipment_id | string | yes (create) | `^EQ-[0-9]{5}$` (ASCII digits only), e.g. `EQ-00042`; uppercase only; unique; immutable | 422; duplicate → 409 |
| name | string | yes (create) | 3–100 chars | 422 |
| location | string | yes (create) | 2–50 chars | 422 |
| description | string | no | 0–500 chars; empty or whitespace-only is stored as `null` | 422 |
| status | – | – | not accepted in body | 422 |

### 6.3 Booking

| Field | Type | Req. | Rules | Error if invalid |
|---|---|---|---|---|
| equipment_id | string | yes | must exist | 404 |
| start | datetime w/ offset | yes | REQ-BOOK-04/05/06 | 422 |
| end | datetime w/ offset | yes | REQ-BOOK-02/03/04 | 422 |
| purpose | string | yes | 3–200 chars | 422 |

### 6.4 Fault

| Field | Type | Req. | Rules | Error if invalid |
|---|---|---|---|---|
| equipment_id | string | yes | must exist | 404 |
| title | string | yes | 3–100 chars | 422 |
| description | string | yes | 10–1000 chars | 422 |
| severity | enum | yes | `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` | 422 |
| resolution_notes | string | yes (resolve) | 5–1000 chars | 422 |

### 6.5 Maintenance task

| Field | Type | Req. | Rules | Error if invalid |
|---|---|---|---|---|
| equipment_id | string | yes | must exist | 404 |
| title | string | yes | 3–100 chars | 422 |
| description | string | no | 0–1000 chars | 422 |
| due_date | date | yes | `YYYY-MM-DD`; ≥ today at creation | 422 |
| assigned_technician_id | int | yes | active user with role `technician` | 422 |
| completion_notes | string | no | 0–1000 chars | 422 |

### 6.6 Status change (`POST /api/equipment/{id}/status`)

| Field | Type | Req. | Rules | Error if invalid |
|---|---|---|---|---|
| event | enum | yes | `check_out` \| `return` \| `take_out_of_service` \| `return_to_service` | 422 |
| booking_id | int | for `check_out` | REQ-STAT-05 | 422 / 404 / 409 |
| reason | string | for `take_out_of_service` | 5–500 chars; optional (≤ 500) otherwise | 422 |

### 6.7 Query parameters

| Param | Endpoint | Rules |
|---|---|---|
| limit | equipment search | int 1–100, default 50 |
| offset | equipment search | int ≥ 0, default 0 |
| q | equipment search | 0–100 chars |
| status / severity | list endpoints | must be a valid enum value |
| scope | bookings | `mine` \| `all` |
| from / to | maintenance report | `YYYY-MM-DD`, from ≤ to |

---

## 7. Known limitations (by design)

- Single-process deployment: booking atomicity (REQ-BOOK-16) uses an in-process lock plus a transaction.
  Running several worker processes is unsupported.
- No login rate limiting or account lockout.
- No CSRF tokens. Mitigated only by `SameSite=Lax` cookies.
- The database schema is created at startup. There are no migrations.
- HTML booking forms take local Europe/London times. For times that are ambiguous when the clocks go
  back (01:00–02:00 on the last Sunday of October), the first occurrence (BST) is used.

---

## 8. Open decisions (all PROVISIONAL – implemented with the recommended option)

| ID | Question | Options | Recommended → implemented |
|---|---|---|---|
| OD-1 | Does a booking ending 10:00 conflict with one starting 10:00? | (a) No, half-open `[start, end)`; (b) Yes, closed intervals; (c) Require a buffer gap (e.g. 15 min) | **(a)**: standard and easiest to explain; produces clean boundary tests. |
| OD-2 | Duration limits and booking horizon | (a) 30 min–8 h, 15-min slots, ≤ 30 days ahead; (b) 1 h–24 h, any minute, ≤ 90 days; (c) no limits | **(a)**: gives several clear boundaries for BVA. |
| OD-3 | Can equipment be booked while a fault is open? | (a) Always; (b) Never; (c) Blocked only by HIGH/CRITICAL open faults | **(c)**: realistic and creates a decision-table rule. |
| OD-4 | When is maintenance overdue? | (a) After the due date (local date > due_date); (b) On the due date (≥); (c) A fixed time, e.g. due_date 17:00 | **(a)**: "due on the 5th" means you may still do it on the 5th. |
| OD-5 | What happens to future bookings when equipment goes out of service? | (a) Auto-cancel with a reason; (b) Block the transition while bookings exist; (c) Keep them and flag them | **(a)**: keeps the data consistent; (b) would let one booking prevent a safety action. |
| OD-6 | Timezone handling | (a) Store UTC, rules in Europe/London, API requires an offset; (b) Store local naive times; (c) UTC everywhere including dates | **(a)**: makes the BST/GMT changeover testable and unambiguous. |
| OD-7 | Is `BOOKED` a stored status or derived from bookings? | (a) Stored, set by `check_out`/`return` with an active booking; (b) Derived from "a booking is active now"; (c) Drop `BOOKED` as a status | **(a)**: gives a real state machine that doesn't depend on the clock. |
| OD-8 | Can equipment with history be deleted? | (a) Block with 409; (b) Soft delete; (c) Cascade delete | **(a)**: protects history; use `OUT_OF_SERVICE` to retire equipment. |
| OD-9 | Does a CRITICAL fault automatically take equipment out of service? | (a) No, manual; (b) Yes | **(a)**: keeps components decoupled; OD-3 already blocks booking. |
| OD-10 | Can technicians book equipment? | (a) Yes; (b) No | **(a)**. |
| OD-11 | Can a technician hold overlapping maintenance tasks? | (a) Yes, unlimited; (b) Max N open tasks | **(a)**: tasks have dates, not time slots. |
| OD-12 | Equipment search matching | (a) Case-insensitive substring; (b) Exact; (c) Case-sensitive prefix | **(a)**. |
