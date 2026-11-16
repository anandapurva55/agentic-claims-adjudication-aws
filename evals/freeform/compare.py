"""Compare the single call and the agent team on the free-form benchmark, and write evals/reports/freeform_comparison.json.

  python evals/freeform/compare.py

Reads the four reports the two systems wrote (the corrected run and the first run, whose estimates contradicted some narratives) and the verified narratives.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "evals" / "reports"
CASES = {c["claim_id"]: c for c in json.loads((ROOT / "evals" / "golden" / "freeform_cases.json").read_text())}
SYSTEMS = {
    "corrected": {"single call": "single_call_baseline_haiku_freeform.json", "agent team": "live_freeform.json"},
    "first_run_contradictory_estimates": {"single call": "single_call_baseline_haiku_freeform_first_run_inconsistent_estimates.json",
                                           "agent team": "live_freeform_first_run_inconsistent_estimates.json"},
}


def load(system: str, name: str) -> tuple[list[dict], dict]:
    rep = json.loads((REPORTS / name).read_text())
    if system == "single call":
        s = rep["sets"]["freeform"]
        return s["predictions"], {"mean_cost_usd": s["mean_cost_usd"], "mean_latency_s": s["mean_latency_s"], "calls_per_claim": 1}
    preds = rep["predictions"]
    m = rep["metrics"]
    return preds, {"mean_cost_usd": round(sum(p.get("cost_usd", 0) for p in preds) / len(preds), 5), "mean_latency_s": round(m["latency_p50_ms"] / 1000, 1),
                   "calls_per_claim": m["model_calls_per_claim"]}


def summarise(preds: list[dict], extra: dict) -> dict:
    wrong, unsafe, by = [], 0, defaultdict(lambda: [0, 0])
    for p in preds:
        exp = CASES[p["claim_id"]]["expected"]["decision"]
        sc = CASES[p["claim_id"]]["scenario"]
        by[sc][1] += 1
        by[sc][0] += p["decision"] == exp
        if p["decision"] != exp:
            wrong.append({"claim_id": p["claim_id"], "scenario": sc, "expected": exp, "got": p["decision"]})
        unsafe += p["decision"] == "approve" and exp != "approve"
    n = len(preds)
    return {"claims": n, "correct": n - len(wrong), "accuracy": round((n - len(wrong)) / n, 4), "unsafe_approvals": unsafe, **extra,
            "by_scenario": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())}, "wrong": wrong}


def main() -> None:
    out = {run: {system: summarise(*load(system, name)) for system, name in files.items()} for run, files in SYSTEMS.items()}
    src = json.loads((ROOT / "evals" / "freeform" / "narratives.json").read_text())
    out["benchmark"] = {"writer": src["writer"], "verifier": src["verifier"], "written": src["written"], "kept": src["kept"], "dropped": src["dropped"],
                        "dropped_implicit": sum(1 for n in src["narratives"] if not n["verified"] and n["implicit"]),
                        "kept_implicit": sum(1 for n in src["narratives"] if n["verified"] and n["implicit"]),
                        "negated_decoys_kept": sum(1 for n in src["narratives"] if n["verified"] and n["decoy"])}
    (REPORTS / "freeform_comparison.json").write_text(json.dumps(out, indent=1))
    for run in SYSTEMS:
        print(f"\n== {run}")
        for system, s in out[run].items():
            print(f"  {system:12} {s['correct']}/{s['claims']} = {s['accuracy']:.1%}  unsafe approvals {s['unsafe_approvals']}  ${s['mean_cost_usd']}/claim  {s['mean_latency_s']}s  {s['calls_per_claim']} calls")
            print("     misses:", {k: v for k, v in s["by_scenario"].items() if v.split("/")[0] != v.split("/")[1]})
    print("\nbenchmark:", out["benchmark"])


if __name__ == "__main__":
    main()
