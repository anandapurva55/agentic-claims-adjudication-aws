"""Score the system against the golden set.

Usage:  python evals/run_eval.py --mode replay|live
Writes evals/reports/<mode>.json. The same scorer judges the keyword baseline (replay) and the Bedrock agents (live),
so the two numbers are directly comparable.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tempfile  # noqa: E402

from app.config import settings  # noqa: E402
from app.runner import run_claim  # noqa: E402

# Evals and red team runs must never write into the real audit log the workbench reads.
settings.runtime_dir = Path(tempfile.mkdtemp(prefix="claims-adjudication-eval-"))

import os  # noqa: E402

# CLAIMS_CASES points at another case file, for example evals/golden/heldout_cases.json with CLAIMS_DATA_DIR=data/heldout
GOLDEN = json.loads(Path(os.environ.get("CLAIMS_CASES") or Path(__file__).parent / "golden" / "cases.json").read_text())
REPORTS = Path(__file__).parent / "reports"
# Cases written to defeat keyword matching, plus prompt injections. Ablations run on just these to save time and money.
HARD = {"neg_alcohol", "para_alcohol", "para_commercial", "neg_delivery", "para_unlicensed", "injection"}


def tokens(preds: list[dict]) -> dict:
    ok = [p for p in preds if "error" not in p]
    n = len(ok) or 1
    return {"input_tokens_per_claim": round(sum(p.get("input_tokens", 0) for p in ok) / n), "output_tokens_per_claim": round(sum(p.get("output_tokens", 0) for p in ok) / n),
            "model_calls_per_claim": round(sum(p.get("model_calls", 0) for p in ok) / n, 1)}


async def predict(case: dict, mode: str) -> dict:
    out: dict = {"claim_id": case["claim_id"], "scenario": case["scenario"]}
    async for ev in run_claim(case["claim_id"], mode, speed=0):
        if ev["type"] == "result":
            out.update(decision=ev["decision"]["decision"], clauses=ev["decision"]["clauses"], payable=ev["decision"]["payable"],
                       latency_ms=ev["latency_ms"], alerts=len(ev["guardrail"]["alerts"]),
                       input_tokens=ev.get("input_tokens", 0), output_tokens=ev.get("output_tokens", 0), model_calls=ev.get("model_calls", 0),
                       tokens_by_model=ev.get("tokens_by_model", {}), cost_usd=ev.get("cost_usd", 0.0),
                       calls=[{k: c[k] for k in ("agent", "model", "input_tokens", "output_tokens", "cache_read", "cache_write", "latency_ms", "cost_usd")} for c in ev.get("calls", [])])
        elif ev["type"] == "error":
            out["error"] = ev["message"]
    return out


def score(cases: list[dict], preds: list[dict]) -> dict:
    ok = [(c, p) for c, p in zip(cases, preds, strict=True) if "error" not in p]
    n = len(ok) or 1
    dec = sum(p["decision"] == c["expected"]["decision"] for c, p in ok)
    clauses = sum(p["clauses"] == c["expected"]["clauses"] for c, p in ok)
    money = [(c, p) for c, p in ok if c["expected"]["payable"] > 0]
    pay = sum(p["payable"] == c["expected"]["payable"] for c, p in money)
    unsafe = sum(p["decision"] == "approve" and c["expected"]["decision"] != "approve" for c, p in ok)
    inj = [(c, p) for c, p in ok if c["expected"]["injection"]]
    by = defaultdict(lambda: [0, 0])
    for c, p in ok:
        by[c["scenario"]][1] += 1
        by[c["scenario"]][0] += p["decision"] == c["expected"]["decision"]
    lat = sorted(p["latency_ms"] for _, p in ok)
    return {
        "cases": len(cases), "errors": len(cases) - len(ok),
        "decision_accuracy": round(dec / n, 4), "clause_match": round(clauses / n, 4),
        "payable_exact": round(pay / (len(money) or 1), 4), "unsafe_approvals": unsafe,
        "injection_handled": round(sum(p["decision"] == c["expected"]["decision"] for c, p in inj) / (len(inj) or 1), 4),
        "latency_p50_ms": lat[len(lat) // 2] if lat else 0, "latency_p95_ms": lat[min(len(lat) - 1, int(len(lat) * .95))] if lat else 0,
        "by_scenario": {k: {"correct": v[0], "total": v[1]} for k, v in sorted(by.items())},
    }


async def evaluate(mode: str, shard: tuple[int, int] = (0, 1), hard: bool = False, per_scenario: bool = False) -> dict:
    k, n = shard
    pool = [c for c in GOLDEN if c["scenario"] in HARD] if hard else GOLDEN
    if per_scenario:  # one claim per scenario: a small sample that still covers every kind of claim, used to measure cost
        seen: set[str] = set()
        pool = [c for c in pool if not (c["scenario"] in seen or seen.add(c["scenario"]))]
    cases = [c for i, c in enumerate(pool) if i % n == k]
    preds = [await predict(c, mode) for c in cases]
    return {"mode": mode, "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": cases, "metrics": score(cases, preds) | tokens(preds),
            "predictions": preds}


def merge(mode: str, label: str = "") -> dict:
    name = f"{mode}_{label}" if label else mode
    parts = [json.loads(p.read_text()) for p in sorted(REPORTS.glob(f"{name}.shard*.json"))]
    cases = [c for p in parts for c in p["cases"]]
    preds = [x for p in parts for x in p["predictions"]]
    return {"mode": mode, "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "metrics": score(cases, preds) | tokens(preds), "predictions": preds}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="replay", choices=["replay", "live"])
    ap.add_argument("--shard", default="0/1", help="K/N: run every Nth claim starting at K, so slow live runs can use parallel processes")
    ap.add_argument("--merge", action="store_true", help="combine the shard files into one report")
    ap.add_argument("--hard", action="store_true", help="only the hard cases: negations, paraphrases and injections")
    ap.add_argument("--per-scenario", action="store_true", help="one claim per scenario, a small representative sample for cost")
    ap.add_argument("--label", default="", help="names the variant being measured, for example v2 or v2_nomem")
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)
    name = f"{args.mode}_{args.label}" if args.label else args.mode
    if args.merge:
        report = merge(args.mode, args.label)
    else:
        k, n = (int(x) for x in args.shard.split("/"))
        report = asyncio.run(evaluate(args.mode, (k, n), args.hard, args.per_scenario))
        if n > 1:
            (REPORTS / f"{name}.shard{k}.json").write_text(json.dumps(report, indent=2))
            print(f"shard {k}/{n} done: {report['metrics']['decision_accuracy']}")
            return
    (REPORTS / f"{name}.json").write_text(json.dumps(report, indent=2))
    m = report["metrics"]
    print(json.dumps({k: v for k, v in m.items() if k != "by_scenario"}, indent=2))
    wrong = {k: v for k, v in m["by_scenario"].items() if v["correct"] < v["total"]}
    print("scenarios with misses:", wrong or "none")


if __name__ == "__main__":
    main()
