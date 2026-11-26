"""Runs the P1 to P3 experiment from docs/TEST-STRATEGY.md §5.

Usage: python -m tests.q4_nfr.performance.run_perf [--duration 60] [--runs 3]
Writes Locust CSV and HTML reports plus summary.md to docs/evidence/perf/.
"""

from __future__ import annotations

import argparse
import csv
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from tests.q4_nfr.performance.seed_perf import seed

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "evidence" / "perf"
LOCUSTFILE = Path(__file__).with_name("locustfile.py")
SCENARIOS = [("P1-P2", users, 0) for users in (10, 50, 100)] + [("P3-volume", 50, 5000)]
STRESS = [("stress", users, 0) for users in (10, 15, 16, 20, 50)]
ENDPOINTS = ["browse: search", "schedule: view", "book: create", "Aggregated"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_once(name: str, users: int, extra: int, run: int, duration: int) -> Path:
    prefix = OUT / f"{name}_u{users}_run{run}"
    with tempfile.TemporaryDirectory() as tmp:
        db_url = f"sqlite:///{tmp}/perf.db"
        seed(db_url, extra_bookings=extra)
        port = _free_port()
        env = {**os.environ, "LEMMS_DATABASE_URL": db_url, "PYTHONPATH": str(ROOT)}
        if name == "stress":
            env["LEMMS_NO_THINK"] = "1"
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(0.1)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "locust",
                    "-f",
                    str(LOCUSTFILE),
                    "--headless",
                    "-u",
                    str(users),
                    "-r",
                    "10",
                    "-t",
                    f"{duration}s",
                    "--host",
                    f"http://127.0.0.1:{port}",
                    "--csv",
                    str(prefix),
                    "--html",
                    f"{prefix}.html",
                    "--only-summary",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        finally:
            server.kill()
            server.wait()
    return Path(f"{prefix}_stats.csv")


def read_stats(path: Path) -> dict[str, dict[str, float]]:
    with path.open() as f:
        return {
            row["Name"]: {
                "requests": float(row["Request Count"]),
                "failures": float(row["Failure Count"]),
                "p50": float(row["50%"]),
                "p95": float(row["95%"]),
                "max": float(row["Max Response Time"]),
                "rps": float(row["Requests/s"]),
            }
            for row in csv.DictReader(f)
        }


def summarise(results: dict[tuple[str, int], list[dict[str, dict[str, float]]]]) -> str:
    lines = [
        "# P1 to P3 results (median of runs)",
        "",
        "| Scenario | Users | Endpoint | Requests | Failure % | p50 ms | p95 ms | Max ms | Req/s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (name, users), runs in results.items():
        for ep in ENDPOINTS:
            rows = [r[ep] for r in runs if ep in r]
            if not rows:
                continue

            def med(key: str, rows: list[dict[str, float]] = rows) -> float:
                return statistics.median(r[key] for r in rows)

            fail_pct = 100 * med("failures") / med("requests") if med("requests") else 0.0
            lines.append(
                f"| {name} | {users} | {ep} | {med('requests'):.0f} | {fail_pct:.1f} | {med('p50'):.0f} | "
                f"{med('p95'):.0f} | {med('max'):.0f} | {med('rps'):.1f} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--stress", action="store_true", help="no think time, users 10 to 50")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict[tuple[str, int], list[dict[str, dict[str, float]]]] = {}
    for name, users, extra in STRESS if args.stress else SCENARIOS:
        for run in range(1, args.runs + 1):
            print(f"{name} users={users} run {run}", flush=True)
            results.setdefault((name, users), []).append(
                read_stats(run_once(name, users, extra, run, args.duration))
            )
    summary = summarise(results)
    (OUT / ("stress-summary.md" if args.stress else "summary.md")).write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
