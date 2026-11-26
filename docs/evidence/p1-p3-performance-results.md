# P1 to P3: performance results and interpretation

Issue #4. Run 2026-11-26 on branch `test/4-nfr-performance`.
Setup: one uvicorn worker, file SQLite DB, fresh seeded DB per run (200 users, 50 equipment),
Locust on the same laptop. Mix: search 70 %, schedule 20 %, booking 10 %.
Commands: `python -m tests.q4_nfr.performance.run_perf` (realistic) and `--stress` (no think time).

## 1. Realistic load (1 to 3 s pause between clicks), median of 3 runs of 60 s

| Users | Search p95 | Schedule p95 | Booking p95 | Failures | Req/s |
|---|---|---|---|---|---|
| 10 | 22 ms | 13 ms | 21 ms | 0 % | 5.2 |
| 50 | 15 ms | 12 ms | 19 ms | 0 % | 25.2 |
| 100 | 15 ms | 14 ms | 18 ms | 0 % | 48.5 |
| 50 + 5,000 bookings (P3) | 14 ms | 13 ms | 19 ms | 0 % | 25.4 |

Against the assumed SLO (p95 < 500 ms reads, < 1 s writes, < 1 % errors at 50 users): **pass**, with a large margin.

**Interpretation**
1. Throughput grows in a straight line with users (about 0.5 req/s per user), so the server was
   never saturated.
2. Booking is slightly slower than reads (about 19 ms vs 15 ms p95), but it does not degrade with load.
   The hypothesis "writes degrade first" was **not confirmed at this load**: about 2 to 5 writes per
   second is far below what SQLite's single writer can handle.
3. P3: 5,000 extra bookings changed p95 by less than 20 %, so volume is not a risk at this scale.
4. Why defect #19 did not appear: each request takes about 7 ms, so even at 100 users less than one
   request is in flight on average (Little's law: 48.5 req/s × 0.007 s ≈ 0.3). Reaching 16 at once
   needs users to act in the same few milliseconds.

## 2. Stress (no pause, so N users = N requests in flight), 1 run of 30 s

| Users | Total requests | Failures | What happened |
|---|---|---|---|
| 10 | 12,928 | 0 % | Steady for 30 s |
| 15 | 8,920 | 0 % | Steady for 30 s, p95 rises to 88 ms (queueing) |
| **16** | **930** | **0 %** | **Served for about 5 s, then zero requests for 25 s** |
| **20** | **390** | **0 %** | **Stopped after about 2 s** |
| **50** | **523** | **0 %** | **Stopped after about 1 s** |

Timeline evidence: `perf/stress_u16_run1_stats_history.csv` (total stays at 930 from second 7).
This confirms defect #19 under a standard load tool: a hard cliff between 15 and 16 concurrent requests.

## 3. False confidence warning
Locust reported **0 % failures and a normal p95** for the 16, 20 and 50 user stress runs, although
the server was frozen. Frozen requests never finished before the run ended, so they were never
counted. Read alone, the summary says "pass". Only the request count and the per second timeline
show the outage. **Lesson: check throughput and the timeline, not just latency and error rate.**

## 4. Limits of these results
- Locust and the server shared one laptop, with no real network, so absolute timings are optimistic.
- Stress runs were 1 run each, and realistic runs 3 runs of 60 s, shorter than the 3 min planned (time).
- One uvicorn worker only (SPEC §7); results do not describe a multi worker deployment.
- The SLO is assumed, because SPEC has no performance requirements (gap, `TEST-STRATEGY.md` §8).

## Re-score
- P1 (writes degrade): L 3 → 2 under realistic load; **availability risk raised** by #19 under bursts.
- P2 (read latency): L 2 → 1.
- P3 (volume): L 2 → 1.
