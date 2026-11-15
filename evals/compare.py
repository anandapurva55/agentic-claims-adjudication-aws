"""Compare variants of the system on the same cases. Usage: python evals/compare.py

Every report is rescored with the same scorer on two slices: all 63 claims (when the report has them) and the 20 hard cases.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import run_eval  # noqa: E402

GOLD = {c["claim_id"]: c for c in run_eval.GOLDEN}
LABELS = [("replay", "Keyword baseline (no LLM)"), ("live", "Agents v1 (no MCP, memory or collaboration)"),
          ("live_v2", "Agents v2 (MCP, memory, collaboration)"), ("live_v2_nomem", "v2 without memory"),
          ("live_v2_nocollab", "v2 without collaboration")]


def rescore(preds: list[dict], hard_only: bool) -> dict | None:
    rows = [p for p in preds if (not hard_only or GOLD[p["claim_id"]]["scenario"] in run_eval.HARD)]
    if not rows:
        return None
    return run_eval.score([GOLD[p["claim_id"]] for p in rows], rows)


def main() -> None:
    out = {}
    print(f"{'variant':46} {'slice':6} {'n':>3} {'decision acc':>13} {'unsafe approvals':>17} {'payable exact':>14}")
    for key, title in LABELS:
        f = run_eval.REPORTS / f"{key}.json"
        if not f.exists():
            continue
        preds = json.loads(f.read_text())["predictions"]
        for sl, hard in (("all", False), ("hard", True)):
            m = rescore(preds, hard)
            if not m or (sl == "all" and m["cases"] < len(GOLD)):
                continue
            out[f"{key}:{sl}"] = {k: m[k] for k in ("cases", "errors", "decision_accuracy", "unsafe_approvals", "payable_exact", "injection_handled")}
            print(f"{title:46} {sl:6} {m['cases']:>3} {m['decision_accuracy']:>13.1%} {m['unsafe_approvals']:>17} {m['payable_exact']:>14.1%}")
    (run_eval.REPORTS / "comparison.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
