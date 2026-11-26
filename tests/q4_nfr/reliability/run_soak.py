"""R2 soak: 50 users with think time for 10 min, polling /health and server memory.

Usage: python -m tests.q4_nfr.reliability.run_soak [--minutes 10] [--users 50]
Writes docs/evidence/soak/ (Locust CSV, health.csv, memory.csv, summary.md).
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import tempfile
import threading
import time

import httpx

from tests.q4_nfr.live_server import ROOT, live_server
from tests.q4_nfr.performance.seed_perf import seed

OUT = ROOT / "docs" / "evidence" / "soak"
LOCUSTFILE = ROOT / "tests" / "q4_nfr" / "performance" / "locustfile.py"


def rss_mb(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout
    return int(out.strip() or 0) / 1024


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=10)
    parser.add_argument("--users", type=int, default=50)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    health: list[tuple[float, str, float]] = []
    memory: list[tuple[float, float]] = []
    stop = threading.Event()

    with tempfile.TemporaryDirectory() as tmp:
        db_url = f"sqlite:///{tmp}/soak.db"
        seed(db_url)
        with live_server(db_url) as (base, proc):
            t0 = time.monotonic()

            def watch() -> None:
                n = 0
                while not stop.is_set():
                    started = time.monotonic()
                    try:
                        status = str(httpx.get(f"{base}/health", timeout=10).status_code)
                    except httpx.TransportError:
                        status = "timeout"
                    health.append((started - t0, status, (time.monotonic() - started) * 1000))
                    if n % 6 == 0:
                        memory.append((started - t0, rss_mb(proc.pid)))
                    n += 1
                    stop.wait(5)

            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "locust",
                    "-f",
                    str(LOCUSTFILE),
                    "--headless",
                    "-u",
                    str(args.users),
                    "-r",
                    "10",
                    "-t",
                    f"{args.minutes}m",
                    "--host",
                    base,
                    "--csv",
                    str(OUT / "soak"),
                    "--html",
                    str(OUT / "soak.html"),
                    "--only-summary",
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            stop.set()
            watcher.join()

    with (OUT / "health.csv").open("w", newline="") as f:
        csv.writer(f).writerows([("elapsed_s", "status", "latency_ms"), *health])
    with (OUT / "memory.csv").open("w", newline="") as f:
        csv.writer(f).writerows([("elapsed_s", "rss_mb"), *memory])
    agg = next(r for r in csv.DictReader((OUT / "soak_stats.csv").open()) if r["Name"] == "Aggregated")
    ok = sum(1 for _, s, _ in health if s == "200")
    summary = (
        f"# R2 soak summary\n\n{args.users} users, {args.minutes} min, think time 1 to 3 s.\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Requests | {agg['Request Count']} |\n| Failures | {agg['Failure Count']} |\n"
        f"| p95 ms | {agg['95%']} |\n| Max ms | {float(agg['Max Response Time']):.0f} |\n"
        f"| Req/s | {float(agg['Requests/s']):.1f} |\n"
        f"| /health checks OK | {ok} of {len(health)} |\n"
        f"| Slowest /health ms | {max(h[2] for h in health):.0f} |\n"
        f"| Server memory start → end MB | {memory[0][1]:.0f} → {memory[-1][1]:.0f} |\n"
    )
    (OUT / "summary.md").write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
