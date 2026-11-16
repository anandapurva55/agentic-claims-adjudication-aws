"""Read the investigation reports and print the comparison.

  python evals/investigation/analyse.py

Adds three things the runner does not: costs recomputed from the recorded tokens at the current (AWS Price List checked) prices, a second view that
ignores low-severity signals, and run-to-run consistency. Writes evals/reports/investigation_analysis.json.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

from app.pricing import call_cost  # noqa: E402
from scoring import score_run, summarise  # noqa: E402

REPORTS = ROOT / "evals" / "reports"
NAMES = {"a": "one call, documents only", "b": "one call, records pasted in", "c": "investigator agent with tools"}
GROUPS = ("single", "history", "multistep", "injection")


def rescored(row: dict, min_severity: str | None) -> dict:
    keep = [s for s in row["signals"] if min_severity is None or s.get("severity") in ("medium", "high")]
    return {**score_run(set(row["expected"]), keep), "group": row["group"], "case": row["case"], "contender": row["contender"]}


def view(rows: list[dict], min_severity: str | None) -> dict:
    out = {}
    for k in NAMES:
        mine = [rescored(r, min_severity) for r in rows if r["contender"] == k]
        if mine:
            out[k] = {"overall": summarise(mine), **{g: summarise([r for r in mine if r["group"] == g]) for g in GROUPS}}
    return out


def consistency(rows: list[dict]) -> dict:
    """Share of cases where every repeat reported the same kinds."""
    by_case: dict[tuple, list] = defaultdict(list)
    for r in rows:
        by_case[(r["contender"], r["case"])].append(tuple(r["predicted"]))
    out = {}
    for k in NAMES:
        mine = [v for (c, _), v in by_case.items() if c == k]
        if mine:
            out[k] = round(sum(len(set(v)) == 1 for v in mine) / len(mine), 3)
    return out


def costs(rows: list[dict], model: str) -> dict:
    out = {}
    for k in NAMES:
        mine = [r for r in rows if r["contender"] == k]
        if mine:
            out[k] = {"mean_cost_usd": round(sum(call_cost(model, r["input_tokens"], r["output_tokens"]) for r in mine) / len(mine), 5),
                      "mean_seconds": round(sum(r["seconds"] for r in mine) / len(mine), 2), "mean_input_tokens": round(sum(r["input_tokens"] for r in mine) / len(mine)),
                      "mean_tool_calls": round(sum(r["tool_calls"] for r in mine) / len(mine), 1)}
    return out


def line(k: str, s: dict) -> str:
    o = s["overall"]
    return (f"  {k} {NAMES[k]:32} found {o['found']:>2}/{o['planted']:<2} ({o['recall']:.0%})  runs with a false alarm {o['runs_with_a_false_alarm']:>2}/{o['runs']:<2}  "
            f"controls clean {o['controls_clean']:>2}/{o['control_runs']:<2}  exact {o['exact']:>2}/{o['runs']:<2}")


def main() -> None:
    result: dict = {}
    for path in sorted(REPORTS.glob("investigation_[0-9]*.json"), key=lambda p: int(p.stem.split("_")[1])):
        rep = json.loads(path.read_text())
        rows, filler = rep["rows"], rep["filler_claims"]
        result[filler] = {"claims_on_file": rep["claims_on_file"], "strict": view(rows, None), "medium_and_high_only": view(rows, "medium"),
                          "consistency": consistency(rows), "costs": costs(rows, rep["model"])}
        r = result[filler]
        print(f"\n=== {rep['claims_on_file']:,} claims on file, {rep['repeats']} repeats, model {rep['model']}")
        print("every signal counts (primary view):")
        for k, s in r["strict"].items():
            print(line(k, s))
            print("     by group: " + "  ".join(f"{g} {s[g]['found']}/{s[g]['planted']} found, {s[g]['runs_with_a_false_alarm']}/{s[g]['runs']} false-alarm runs" for g in GROUPS if s[g]["runs"]))
        print("low-severity signals ignored (secondary view):")
        for k, s in r["medium_and_high_only"].items():
            print(line(k, s))
        print("same answer on all 3 repeats:", {k: f"{v:.0%}" for k, v in r["consistency"].items()})
        print("cost and time per case:", {k: f"${v['mean_cost_usd']:.4f}, {v['mean_seconds']}s, {v['mean_input_tokens']:,} input tokens, {v['mean_tool_calls']} tool calls" for k, v in r["costs"].items()})
    (REPORTS / "investigation_analysis.json").write_text(json.dumps(result, indent=1, default=str))
    print("\nwrote evals/reports/investigation_analysis.json")


if __name__ == "__main__":
    main()
