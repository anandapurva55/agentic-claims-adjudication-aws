"""Score the other systems on the same held-out narratives: the keyword baseline and the Bedrock models, prompted.

Usage: python finetune/eval_baselines.py [--limit N]     (needs Bedrock access: set AWS_PROFILE and AWS_DEFAULT_REGION)
Writes finetune/out/baselines.json. The prompt is identical to the one the open model is given, in zero-shot and few-shot form.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

from app.services.baseline import keyword_flags  # noqa: E402
from scoring import parse_flags, score  # noqa: E402

MODELS = {"nova-2-lite": "global.amazon.nova-2-lite-v1:0", "claude-haiku-4.5": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
          "claude-sonnet-4.6": "global.anthropic.claude-sonnet-4-6"}
SETS = ("test_unseen", "test_golden")


def load(name: str, limit: int) -> list[dict]:
    rows = [json.loads(line) for line in (HERE / "data" / f"{name}.jsonl").read_text().splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def shots(train: list[dict]) -> list[dict]:
    def first(pred):
        return next(x for x in train if pred(x["labels"]))
    return [first(lambda L: L["intoxicated"]), first(lambda L: not any(L.values())), first(lambda L: L["commercial_use"]), first(lambda L: L["unlicensed_driver"])]


def ask(client, model_id: str, system: str, shot_rows: list[dict], narrative: str) -> tuple[str, float]:
    msgs = []
    for ex in shot_rows:
        msgs += [{"role": "user", "content": [{"text": ex["messages"][1]["content"]}]}, {"role": "assistant", "content": [{"text": ex["messages"][2]["content"]}]}]
    msgs.append({"role": "user", "content": [{"text": narrative}]})
    t0 = time.perf_counter()
    r = client.converse(modelId=model_id, system=[{"text": system}], messages=msgs, inferenceConfig={"maxTokens": 80, "temperature": 0.0})
    return r["output"]["message"]["content"][0]["text"], time.perf_counter() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--out", default="baselines", help="output file name, so models can run in parallel processes")
    a = ap.parse_args()
    client = boto3.client("bedrock-runtime", region_name="us-east-1", config=Config(retries={"max_attempts": 10, "mode": "adaptive"}, read_timeout=120))
    train = load("train", 0)
    results: dict = {}

    for name in SETS:  # the keyword baseline
        rows = []
        for r in load(name, a.limit):
            pred = keyword_flags(r["narrative"])
            rows.append({"gold": r["labels"], "pred": {f: bool(pred.get(f, False)) for f in r["labels"]}, "valid": True})
        results[f"{name}/keyword_baseline"] = score(rows)
        print(f"keyword baseline  {name:12} exact={results[f'{name}/keyword_baseline']['exact_match']:.3f}", flush=True)

    for label in a.models.split(","):
        for name in SETS:
            data = load(name, a.limit)
            for mode, sh in (("zero_shot", []), ("few_shot", shots(train))):
                rows, secs = [], []
                for r in data:
                    text, sec = ask(client, MODELS[label], r["messages"][0]["content"], sh, r["messages"][1]["content"])
                    pred, valid = parse_flags(text)
                    rows.append({"gold": r["labels"], "pred": pred, "valid": valid})
                    secs.append(sec)
                s = score(rows)
                s["seconds_per_narrative"] = round(sum(secs) / len(secs), 3)
                results[f"{name}/{label}/{mode}"] = s
                print(f"{label:18} {mode:9} {name:12} exact={s['exact_match']:.3f} microF1={s['micro_f1']:.3f} missed_denials={s['missed_denials']}", flush=True)
                (HERE / "out").mkdir(exist_ok=True)
                (HERE / "out" / f"{a.out}.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
