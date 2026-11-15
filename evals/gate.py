"""Quality gate. Exits non zero when a metric crosses its threshold, which fails the pull request.

Usage:  python evals/gate.py --mode replay
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def check(metrics: dict, rules: dict) -> list[str]:
    failures = []
    for name, bound in rules.items():
        if name.startswith("_"):
            continue
        value = metrics[name]
        if "min" in bound and value < bound["min"]:
            failures.append(f"{name} = {value} is below the minimum {bound['min']}")
        if "max" in bound and value > bound["max"]:
            failures.append(f"{name} = {value} is above the maximum {bound['max']}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="replay")
    ap.add_argument("--label", default="", help="which variant to gate, for example v2")
    args = ap.parse_args()
    mode = args.mode
    name = f"{mode}_{args.label}" if args.label else mode
    report = json.loads((HERE / "reports" / f"{name}.json").read_text())
    failures = check(report["metrics"], json.loads((HERE / "thresholds.json").read_text())[mode])
    if failures:
        print(f"EVAL GATE FAILED ({mode})")
        for f in failures:
            print("  -", f)
        return 1
    print(f"EVAL GATE PASSED ({mode}): " + ", ".join(f"{k}={report['metrics'][k]}" for k in json.loads((HERE / 'thresholds.json').read_text())[mode] if not k.startswith('_')))
    return 0


if __name__ == "__main__":
    sys.exit(main())
