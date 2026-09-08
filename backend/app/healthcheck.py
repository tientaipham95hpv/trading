"""Container health probe that turns a persistent hang into a clean restart."""

from __future__ import annotations

import os
import signal
import sys
import urllib.request
from pathlib import Path

FAILURE_FILE = Path("/tmp/trading-healthcheck-failures")
MAX_FAILURES_BEFORE_RESTART = 3


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f"health returned HTTP {response.status}")
        FAILURE_FILE.unlink(missing_ok=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - probe must handle every failure mode
        failures = _read_failures() + 1
        FAILURE_FILE.write_text(str(failures), encoding="ascii")
        print(f"healthcheck failure {failures}/{MAX_FAILURES_BEFORE_RESTART}: {exc}", file=sys.stderr)
        if failures >= MAX_FAILURES_BEFORE_RESTART:
            # PID 1 is uvicorn. Docker's restart:unless-stopped policy brings it
            # back; an explicit operator stop remains stopped.
            os.kill(1, signal.SIGTERM)
        return 1


def _read_failures() -> int:
    try:
        return int(FAILURE_FILE.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
