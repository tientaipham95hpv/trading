#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.high_vol_ablation import build_ablation
from app.services.oos_attribution import fetch_candles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/high-vol-candles"))
    args = parser.parse_args()
    payloads = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    datasets = {(p["symbol"], p["tf"]): fetch_candles(p["symbol"], p["tf"], p["max_close"], args.cache_dir)
                for p in payloads}
    report = build_ablation(payloads, datasets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=True))
    print(f"wrote {len(report['folds'])} folds to {args.output}")


if __name__ == "__main__":
    main()
