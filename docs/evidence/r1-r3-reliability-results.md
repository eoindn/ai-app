# R1 to R3: reliability results and interpretation

Issue #5. Run 2026-11-26 on branch `test/5-nfr-reliability`.

## R1: persistence across restart (REQ-DATA-01): pass
Real uvicorn process, file SQLite DB. Created 2 equipment, 1 booking, 1 fault and 1 status change
through the API, stopped the server, restarted it on the same file and compared every table.

| Stop type | Rows identical after restart | Old session cookie still valid |
|---|---|---|
| Graceful (SIGTERM) | Yes | Yes |
| Crash (SIGKILL) | Yes | Yes |

Interpretation: every change is committed before the API replies, so a crash straight after a
201 loses nothing. Sessions are stored server side (REQ-ROLE-03), so users stay logged in across a restart.
Sensitivity check: with the booking commit removed, the API still said 201 but the booking was
missing after restart, and the test failed. So the test detects "acknowledged but not saved".

## R2: 10 minute soak, 50 users with think time: pass

| Minute | Req/s | p95 | Failures |
|---|---|---|---|
| 1 | 24.6 | 18 ms | 0 |
| 3 | 24.6 | 15 ms | 0 |
| 5 | 24.6 | 15 ms | 0 |
| 7 | 24.9 | 15 ms | 0 |
| 9 | 24.7 | 15 ms | 0 |

Totals: 14,883 requests, 0 failures, `/health` 120 of 120 OK (slowest 122 ms).
Server memory: 73 MB at startup, then flat between 47 and 51 MB for the whole run (one spike to 69 MB at 2 min).

Interpretation: no degradation over time, no errors, and no memory growth, so there is no sign of a
leak or of the database slowing as bookings accumulate. Throughput here (24.9 req/s) matches P1 at 50 users.

Limit: with think time the load never reaches 16 requests in flight, so this soak cannot show
defect #19. Under bursts the same server freezes (see `p1-p3-performance-results.md`). A
10 minute soak is also short; leaks that grow slowly over hours would not show.

Raw data: `soak/soak_stats_history.csv`, `soak/health.csv`, `soak/memory.csv`, `soak/soak.html`.

## R3: /health with a lost database (REQ-DATA-08): pass
Pointed the app at a database file in a directory that does not exist.
`/health` returned **503 `{"status": "unavailable"}`**, then **200** again once the real DB was restored.
Sensitivity check: with `/health` hard coded to "ok", the test failed.

Open question for the report: during the #19 freeze `/health` also stops answering. A monitor that
treats a timeout as unhealthy would still notice, but one that only checks status codes might not.

## Re-score
- R1: L 1 → 1 (confirmed low).
- R2: L 2 → 1 under steady load; availability risk under bursts tracked by #19.
- R3: L 1 → 1.
