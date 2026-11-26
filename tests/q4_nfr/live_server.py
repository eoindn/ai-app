"""Start a real uvicorn process for tests that need true concurrency or restarts."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def live_server(db_url: str, port: int | None = None) -> Iterator[tuple[str, subprocess.Popen[bytes]]]:
    port = port or free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env={**os.environ, "LEMMS_DATABASE_URL": db_url, "PYTHONPATH": str(ROOT)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{base}/health").status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")
        yield base, proc
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
