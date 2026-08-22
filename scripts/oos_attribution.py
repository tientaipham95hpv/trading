#!/usr/bin/env python3
"""Build OOS attribution JSON from optimizer JSONL."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.oos_attribution import build_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/oos-candles"))
    args = parser.parse_args()
    payloads = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    report = build_report(payloads, args.cache_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=True))
    print(f"wrote {len(report['trades'])} OOS trades to {args.output}")


if __name__ == "__main__":
    main()
