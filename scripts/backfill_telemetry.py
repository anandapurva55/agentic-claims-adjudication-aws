"""Load measured evaluation runs into the telemetry lake (S3), so Athena and QuickSight can query them.

The live product writes these records itself as it runs. This script replays the per call details that the evaluation reports
kept (evals/reports/*.json), so the cost experiment and the baseline sit in the same tables with a `variant` label.
Usage: python scripts/backfill_telemetry.py <telemetry bucket> [report name ...]
"""
import json
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "evals" / "reports"
LABELS = {"live_v2_cost": "baseline", "live_opt_parallel": "parallel_tools", "live_opt_parallel_haiku": "parallel_tools_haiku_memo"}


def main() -> None:
    bucket = sys.argv[1]
    names = sys.argv[2:] or list(LABELS)
    s3 = boto3.client("s3", region_name="us-east-1")
    n_calls = n_runs = 0
    for name in names:
        f = REPORTS / f"{name}.json"
        if not f.exists():
            print("skip (no report):", name)
            continue
        report = json.loads(f.read_text())
        day = report["generated"][:10]
        variant = LABELS.get(name, name)
        for p in report["predictions"]:
            if "error" in p or not p.get("calls"):
                continue
            run_id = f"{name}-{p['claim_id']}"
            run = {"run_id": run_id, "claim_id": p["claim_id"], "mode": "live", "variant": variant, "decision": p["decision"],
                   "latency_ms": p["latency_ms"], "model_calls": p["model_calls"], "input_tokens": p["input_tokens"],
                   "output_tokens": p["output_tokens"], "cost_usd": p["cost_usd"], "ok": True, "error": "", "ts": report["generated"], "day": day}
            s3.put_object(Bucket=bucket, Key=f"runs/dt={day}/{run_id}.json", Body=json.dumps(run).encode())
            n_runs += 1
            for i, c in enumerate(p["calls"]):
                row = {"call_id": f"{run_id}-{i}", "run_id": run_id, "claim_id": p["claim_id"], "agent": c["agent"], "model": c["model"],
                       "input_tokens": c["input_tokens"], "output_tokens": c["output_tokens"], "cache_read": c["cache_read"],
                       "cache_write": c["cache_write"], "latency_ms": c["latency_ms"], "wall_ms": c["latency_ms"], "cost_usd": c["cost_usd"],
                       "error": "", "variant": variant, "ts": report["generated"], "day": day, "mode": "live"}
                s3.put_object(Bucket=bucket, Key=f"calls/dt={day}/{row['call_id']}.json", Body=json.dumps(row).encode())
                n_calls += 1
    print(f"uploaded {n_runs} runs and {n_calls} calls to s3://{bucket}")


if __name__ == "__main__":
    main()
