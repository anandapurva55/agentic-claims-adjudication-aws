"""Run the investigation test: do the agents earn their place when the facts live in records?

  python evals/investigation/run.py [--repeats 3] [--filler 0] [--contenders a b c] [--only ID ...]
  python evals/investigation/run.py --show R1_bumper_2_4x      (print what the single calls are given, call nothing)

Contenders: a = one call, documents only. b = one call, documents plus every record pasted in. c = the product's investigator agent with its tools.
--filler N adds N unrelated claims to the claims history (the scale test). Calls Amazon Bedrock (about 2 to 4 USD for the full run). Writes
evals/reports/investigation_<filler>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

from cases import CASES  # noqa: E402
from world import build  # noqa: E402

NAMES = {"a": "one call, documents only", "b": "one call, records pasted in", "c": "investigator agent with tools"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--filler", type=int, default=0)
    ap.add_argument("--contenders", nargs="+", default=["a", "b", "c"], choices=list(NAMES))
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--show", default="")
    a = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix="investigation-world-"))
    t0 = time.time()
    ids = build(root / "data", filler=a.filler)
    print(f"world built in {time.time() - t0:.0f}s: {len(CASES)} cases, {a.filler} filler claims", flush=True)
    os.environ["CLAIMS_DATA_DIR"] = str(root / "data")  # the MCP servers run as child processes and read this
    os.environ["CLAIMS_RUNTIME_DIR"] = str(root / "runtime")
    os.environ["CLAIMS_REGION"] = "us-east-1"

    import boto3
    from app.config import settings
    from app.services import data
    from botocore.config import Config
    from contenders import agent_run, packet, records_text, single_call
    from scoring import score_run, summarise

    model = settings.fast_model
    if a.show:
        case = next(c for c in CASES if c.id == a.show)
        ex = data.extract_claim(ids[case.id])
        text = packet(ex) + records_text(ex["policy_no"])
        print(f"--- {case.id}: expects {sorted(case.expect) or 'nothing (control)'}\n{text[:2500]}\n... ({len(text):,} characters in all)")
        return

    client = boto3.client("bedrock-runtime", region_name="us-east-1", config=Config(retries={"max_attempts": 12, "mode": "adaptive"}, read_timeout=300))
    cases = [c for c in CASES if not a.only or c.id in a.only]
    rows: list[dict] = []

    def record(contender: str, case, rep: int, out: dict) -> None:
        s = score_run(case.expect, out["signals"])
        rows.append({"contender": contender, "case": case.id, "group": case.group, "repeat": rep, **s,
                     **{k: out[k] for k in ("seconds", "model_calls", "tool_calls", "input_tokens", "output_tokens", "cost_usd")}, "signals": out["signals"]})
        flag = "ok " if s["exact"] else "-- "
        print(f"{flag}{contender} {case.id:34} rep{rep} found {s['found']} missed {s['missed']} false {s['false_alarms']}  ${out['cost_usd']:.4f} {out['seconds']}s", flush=True)

    singles = [(k, c, r) for k in ("a", "b") if k in a.contenders for c in cases for r in range(a.repeats)]
    if singles:
        def one(job):
            k, case, rep = job
            return job, single_call(client, model, data.extract_claim(ids[case.id]), with_records=k == "b")
        with ThreadPoolExecutor(6) as pool:
            for (k, case, rep), out in pool.map(one, singles):
                record(k, case, rep, out)
    if "c" in a.contenders:  # tool state is per process, so agent runs go one at a time
        for case in cases:
            for rep in range(a.repeats):
                ex = data.extract_claim(ids[case.id])
                try:
                    out = asyncio.run(agent_run(ids[case.id], ex))
                except Exception as exc:  # noqa: BLE001
                    out = {"signals": [], "seconds": 0, "model_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "error": str(exc)[:200]}
                    print(f"!! c {case.id} failed: {exc}", flush=True)
                record("c", case, rep, out)

    report: dict = {"model": model, "repeats": a.repeats, "filler_claims": a.filler, "claims_on_file": len(CASES) + a.filler + sum(len(c.history_days) for c in CASES),
                    "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "contenders": {}}
    print(f"\n=== {a.filler} filler claims, {a.repeats} repeats")
    for k in a.contenders:
        mine = [r for r in rows if r["contender"] == k]
        if not mine:
            continue
        by_group = {g: summarise([r for r in mine if r["group"] == g]) for g in ("single", "history", "multistep", "injection")}
        n = len(mine)
        report["contenders"][k] = {"name": NAMES[k], "overall": summarise(mine), "by_group": by_group, "mean_cost_usd": round(sum(r["cost_usd"] for r in mine) / n, 5),
                                   "mean_seconds": round(sum(r["seconds"] for r in mine) / n, 2), "mean_model_calls": round(sum(r["model_calls"] for r in mine) / n, 1),
                                   "mean_tool_calls": round(sum(r["tool_calls"] for r in mine) / n, 1), "mean_input_tokens": round(sum(r["input_tokens"] for r in mine) / n)}
        o = report["contenders"][k]
        print(f"{k} {NAMES[k]:32} found {o['overall']['found']}/{o['overall']['planted']}  false-alarm runs {o['overall']['runs_with_a_false_alarm']}/{n}  "
              f"exact {o['overall']['exact']}/{n}  ${o['mean_cost_usd']:.4f}  {o['mean_seconds']}s  {o['mean_input_tokens']:,} input tokens  {o['mean_tool_calls']} tool calls")
    report["rows"] = rows
    out_path = ROOT / "evals" / "reports" / f"investigation_{a.filler}.json"
    out_path.write_text(json.dumps(report, indent=1))
    print(f"wrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
