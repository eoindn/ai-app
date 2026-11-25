# LEMMS – Q4 Non-Functional & Quality Attribute Test Strategy

**Scope (brief, Q4):** evaluate security, performance, reliability, data integrity and compatibility;
select appropriate techniques and tools, explain the choices and interpret the results.
Source of truth for requirements: `docs/SPEC.md` (v0.1). Attributes follow ISO/IEC 25010;
security risks are mapped to the OWASP Top 10 (2021).

Accessibility (axe, WCAG 2.2 AA) is **Q3**, not Q4, so it is out of scope here.

---

## 1. Risk scoring

- **Likelihood (L)** 1–3: how likely the defect is, given the design (SQLite single writer, in-process lock, AI-generated code).
- **Impact (I)** 1–3: harm if it reaches users (3 = unauthorised access, data loss or corrupted data).
- **Risk = L × I** → **Critical** 9 · **High** 6 · **Medium** 3–4 · **Low** 1–2.
- Priority sets the order and the depth: Critical/High get automated tests that run in CI; Medium gets targeted tests; Low gets a smoke check or a scan.
- **Adaptive:** after each run, the *Re-score* column is updated from the evidence. A defect found raises L to 3; a clean, repeatable pass lowers L by 1. Re-scored risks feed the release decision.

## 2. Risk-based strategy table

| # | Attribute | Risk | REQ IDs | Technique | Tool | Pass criterion | L | I | Priority | Re-score |
|---|---|---|---|---|---|---|---|---|---|---|
| **S1** | Security | Role escalation: a user does an action their role forbids (OWASP A01) | REQ-ROLE-05, REQ-INV-09, REQ-STAT-03, REQ-BOOK-11/12/13, REQ-MAINT-01/05/07/09, REQ-REP-01..03, REQ-ROLE-06, §4 | Decision table generated from the §4 permission matrix | pytest (parametrised) | Every ❌ cell → 403 `FORBIDDEN`; data unchanged | 3 | 3 | **Critical 9** | |
| **S2** | Security | An endpoint is reachable without a session (A01/A07) | REQ-ROLE-01 | Endpoint sweep: every `/api` route with no cookie | pytest + TestClient | All → 401 `UNAUTHENTICATED`, except login and `/health` | 2 | 3 | **High 6** | |
| **S3** | Security | An expired or logged-out session is still accepted (A07) | REQ-ROLE-03 | BVA on session age with the injected clock (8 h − 1 s, 8 h, 8 h + 1 s); cookie replay after logout | pytest + `FixedClock` | Expired or logged-out → 401 | 2 | 3 | **High 6** | |
| **S4** | Security | A dependency has a known CVE (A06) | – (supports ROLE-04/07) | Software composition analysis (SCA) | pip-audit | 0 known vulnerabilities, or each one triaged | 2 | 3 | **High 6** | |
| S5 | Security | Username enumeration from login responses (A07) | REQ-ROLE-02 | Equivalence partitions: wrong password / unknown user / inactive user | pytest | Identical status and body across all three | 2 | 2 | Medium 4 | |
| S6 | Security | A 500 leaks a stack trace, SQL or file paths (A05) | REQ-DATA-04 | Fault injection (a service raises), then inspect the body | pytest + monkeypatch | 500 `INTERNAL_ERROR` with a generic message and `request_id` only | 2 | 2 | Medium 4 | |
| S7 | Security | Academics see other users' identity on the schedule (A01, privacy) | REQ-BOOK-15 | Role-based negative test | pytest | Others' `user_id` and `purpose` = null | 2 | 2 | Medium 4 | |
| S8 | Security | Insecure code patterns: secrets, injection, weak crypto (A02/A03/A05) | REQ-DATA-09, REQ-ROLE-04 | Static application security testing (SAST) | bandit | No High findings; Medium/Low triaged | 2 | 2 | Medium 4 | |
| S9 | Security | Unexpected input crashes the API (500) instead of a 422 (A03/A05) | REQ-DATA-02/03/04 | Property-based API fuzzing from the OpenAPI schema | Schemathesis | No 5xx; responses match the schema | 2 | 2 | Medium 4 | |
| S10 | Security | Cookie readable by JavaScript or sent cross-site (A05/A07) | REQ-ROLE-07 | Inspect the `Set-Cookie` header | pytest | `HttpOnly`, `SameSite=Lax` present | 1 | 3 | Medium 3 | |
| S11 | Security | A password appears in plaintext in the DB, a response or a log (A02) | REQ-ROLE-04 | Check the DB hash format; search responses and captured logs | pytest + `caplog` | `$2b$` hash; password string never found | 1 | 3 | Medium 3 | |
| S12 | Security | SQL injection through search or IDs (A03) | REQ-INV-07, REQ-DATA-02 | Negative inputs (`' OR 1=1--`, `%`, `_`, unicode) | pytest (parametrised) | Treated as literal text; no 500; no extra rows | 1 | 3 | Medium 3 | |
| **P1** | Performance | Booking writes degrade first under concurrency (SQLite single writer) | REQ-BOOK-01, REQ-BOOK-07, REQ-BOOK-16, REQ-DATA-01 | Load experiment at 10, 50 and 100 users, mixed profile | Locust | p95 and error rate within the assumed SLO (§5) | 3 | 2 | **High 6** | |
| P2 | Performance | Equipment browse and search get slow under load | REQ-INV-07, REQ-INV-08 | Load experiment (browse user type) | Locust | p95 < 500 ms at 50 users | 2 | 2 | Medium 4 | |
| P3 | Performance | The conflict check and schedule query slow down as bookings grow | REQ-BOOK-07, REQ-BOOK-15 | Volume test: seed about 5,000 bookings, then repeat P1 | Locust + seed script | p95 change from P1 < 20 % | 2 | 1 | Low 2 | |
| R1 | Reliability | Data is lost on app restart | REQ-DATA-01 | Restart test: write, kill the process, restart, read | pytest + subprocess (uvicorn, file DB) | All records present and identical | 1 | 3 | Medium 3 | |
| R2 | Reliability | Errors under sustained load (failures, not just slowness) | REQ-DATA-04, REQ-DATA-08 | Soak: 50 users for 10 min; watch the error rate and `/health` | Locust + `/metrics` | Error rate < 1 %; `/health` stays 200; no 5xx | 2 | 2 | Medium 4 | |
| R3 | Reliability | `/health` reports ok when the DB is unreachable | REQ-DATA-08 | Fault injection (break the DB connection) | pytest | `/health` ≠ 200 when the DB is down | 1 | 2 | Low 2 | |
| **D1** | Data integrity | Parallel requests double-book one slot (race condition) | REQ-BOOK-16, REQ-BOOK-07 | Concurrency experiment: N = 10, 20 and 50 parallel POSTs for one slot, repeated 20× | pytest + `ThreadPoolExecutor`/httpx against a running uvicorn | Exactly one 201 and N−1 409s on every run; one row in the DB | 3 | 3 | **Critical 9** | |
| **D2** | Data integrity | Out-of-service half-saves (status changed, bookings not cancelled, or the reverse) | REQ-DATA-05, REQ-STAT-06 | Fault injection after the status update | pytest + monkeypatch | Status and all bookings unchanged; no history row | 2 | 3 | **High 6** | |
| **D3** | Data integrity | A maintenance start or complete changes the task but not the equipment | REQ-DATA-05, REQ-MAINT-05/06 | Fault injection, as D2 | pytest + monkeypatch | Task and equipment both unchanged | 2 | 3 | **High 6** | |
| D4 | Data integrity | An audit trail is missing for status changes and security events (A09) | REQ-STAT-07, REQ-DATA-07 | Log and history assertions | pytest + `caplog` | Every transition → one history row and one `status_transition` log line | 2 | 2 | Medium 4 | |
| C1 | Compatibility | Core UI journeys break in Firefox or WebKit (Safari) | REQ-ROLE-01 (redirect), REQ-BOOK-01, REQ-INV-07 | Cross-browser end-to-end smoke tests (login → search → book → cancel) | Playwright (Chromium, Firefox, WebKit) | Same journeys pass in all 3 engines | 2 | 2 | Medium 4 | |
| C2 | Compatibility | The UI is unusable at mobile viewport sizes | UI generally | Device emulation (e.g. iPhone 13, Pixel 5) | Playwright | Journeys pass; no horizontal scroll | 2 | 1 | Low 2 | |
| C3 | Compatibility | The app only works on the developer's machine | Stack (Python 3.12) | Platform matrix in CI | GitHub Actions (ubuntu/windows/macos × py3.12/3.13) | Test suite green on every cell | 1 | 2 | Low 2 | |

## 3. Balance of effort

| Attribute | Rows | Critical/High | Why this weight |
|---|---|---|---|
| Security | 12 | 4 | The most REQs (ROLE-01..07, DATA-04, BOOK-15) and the highest impact. Role logic is AI-generated, so it is the most likely to be wrong. |
| Data integrity | 4 | 3 | Corruption is silent and permanent. BOOK-16 relies on an in-process lock (SPEC §7), a known weak point. |
| Performance | 3 | 1 | The SPEC has no targets, so we baseline it and explain the SQLite bottleneck rather than test against requirements. |
| Reliability | 3 | 0 | Single process with a file DB: few failure modes, and they are cheap to check. |
| Compatibility | 3 | 0 | Server-rendered HTML with little JS, so engine differences are unlikely. Smoke tests are enough. |

## 4. Threat analysis (STRIDE → risks)

| STRIDE | Threat in LEMMS | Covered by |
|---|---|---|
| Spoofing | Use someone else's session; guess valid usernames | S2, S3, S5, S10 |
| Tampering | Craft requests to set `status` or book as another user | S1, S9, S12, REQ-INV-03 |
| Repudiation | A status change with no record of who made it | D4 |
| Information disclosure | Stack traces, password leakage, others' booking details | S6, S7, S11 |
| Denial of service | Booking writes saturate SQLite; brute-force login (no rate limit) | P1, R2; brute force is an accepted risk (§7) |
| Elevation of privilege | An academic does admin actions; a technician returns equipment to service | S1 |

## 5. Experiment design (performance and reliability)

**P1/P2 load experiment**
- *Hypothesis:* booking writes (POST `/api/bookings`) reach the p95 SLO before reads do, because SQLite serialises writers and BOOK-16 adds an in-process lock.
- *Independent variable:* concurrent users = 10, 50, 100 (spawn rate 10/s).
- *Dependent variables:* p50, p95 and p99 latency per endpoint; requests/s; error rate.
- *Controls:* same machine, a fresh seeded DB per run, 3 min per level after ramp-up, a single uvicorn worker, no `--reload`, and other apps closed. Each level runs 3×; report the median.
- *User mix:* browse/search 70 %, view schedule 20 %, create booking 10 % (random future slots, so most succeed, plus some deliberate clashes to exercise conflict checks).
- *Assumed SLO* (the SPEC has none, see §8): p95 < 500 ms for reads and < 1 s for writes at 50 users; error rate < 1 %.
- *Evidence:* Locust HTML report and CSV, charts, and a `/metrics` snapshot.

**D1 concurrency experiment**
- Run against a real uvicorn process with the file DB, not the TestClient, because the TestClient can serialise requests and hide the race (a false pass).
- Repeat 20× per N, because a race that passes once proves little. Report successes per run as a distribution.
- *Interpretation limit:* it proves atomicity for one process only. Multi-worker deployment is unsupported (SPEC §7).

## 6. Tool choices and alternatives considered

| Need | Chosen | Why | Alternative rejected |
|---|---|---|---|
| API security and integrity tests | pytest + FastAPI TestClient | Same framework as Q1/Q2; deterministic with `FixedClock`; runs in CI | Postman/Newman: harder to version, parametrise and run in CI |
| Load testing | Locust | Python (same language); user types are code; built-in p95 and charts | JMeter: GUI-heavy XML plans. k6: JavaScript, a second language |
| SAST | bandit | Python-specific, fast, CI-friendly | Semgrep: broader but needs rule tuning; overkill here |
| SCA | pip-audit | Official PyPA tool, uses the OSV database | Safety: its free database is delayed |
| API fuzzing | Schemathesis | Generates cases from the OpenAPI schema FastAPI already produces | Hand-written fuzz: lower coverage of edge cases |
| Cross-browser | Playwright | One API across Chromium, Firefox and WebKit; Python bindings; CI-ready | Selenium: needs driver management and is slower and flakier |
| DAST (optional) | OWASP ZAP baseline | Passive scan for headers and misconfiguration | Burp Suite: manual and licensed |

## 7. Accepted risks (by design, SPEC §7): documented, not tested beyond the mitigation

| Risk | OWASP | Mitigation | Evidence |
|---|---|---|---|
| No login rate limiting or lockout: brute force | A07 | None | Residual risk in the release decision |
| No CSRF tokens | A01 | `SameSite=Lax` cookie | S10 |
| Multi-worker deployment breaks the booking lock | – | Single process only | Stated limit of D1 |

## 8. Traceability gaps found while building this strategy (report material)

1. **No performance requirements.** P1–P3 use an assumed SLO; recommend adding REQ-PERF IDs.
2. **No compatibility requirements** (browsers, viewports, platforms). C1–C3 use an assumed target.
3. **The cookie `Secure` flag is not required** by REQ-ROLE-07: acceptable on localhost, a risk if deployed.
