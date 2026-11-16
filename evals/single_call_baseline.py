"""The missing baseline: ONE structured model call for the six judgement flags, then the SAME rules engine the agent team uses.

  python evals/single_call_baseline.py [--model haiku|nova] [--zero-shot]

It answers one question: do the agents earn their cost? The agent team sets the same six flags (with tools, memory, retrieval and collaboration) and costs
20 model calls per claim. This baseline spends one call per claim, then goes through exactly the same code path (data.facts_from, rules.adjudicate), so
any difference in the outcome comes from how the flags were produced, nothing else.

Fairness notes, stated so the comparison is read correctly:
  * the prompt is the one the fine-tuning study used (finetune/data/train.jsonl system message) with the same four fixed examples
  * no guardrail: the agent team scans narratives with Bedrock Guardrails first, this baseline reads the raw text, so injection claims are its exposure
  * no memory and no retrieval: lessons from memory are not available to it
Runs the golden set and both held-out sets. Writes evals/reports/single_call_baseline.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "finetune"))
sys.path.insert(0, str(ROOT / "evals"))

from app import pricing  # noqa: E402
from app.config import settings  # noqa: E402
from app.rules import adjudicate  # noqa: E402
from app.services import data  # noqa: E402

settings.runtime_dir = Path(tempfile.mkdtemp(prefix="claims-adjudication-baseline-"))

from run_eval import score  # noqa: E402  (the same scorer that judged the agent team)
from scoring import parse_flags  # noqa: E402

MODELS = {"haiku": "global.anthropic.claude-haiku-4-5-20251001-v1:0", "nova": "global.amazon.nova-2-lite-v1:0"}
SETS = {"golden": ("data", "evals/golden/cases.json"), "heldout_1": ("data/heldout", "evals/golden/heldout_cases.json"),
        "heldout_2": ("data/heldout2", "evals/golden/heldout2_cases.json")}
FLAGS = ("intoxicated", "commercial_use", "unlicensed_driver", "mechanical_failure", "tyre_only", "theft")


def shots(train: list[dict]) -> list[dict]:
    def first(pred):
        return next(x for x in train if pred(x["labels"]))
    return [first(lambda L: L["intoxicated"]), first(lambda L: not any(L.values())), first(lambda L: L["commercial_use"]), first(lambda L: L["unlicensed_driver"])]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="haiku", choices=list(MODELS))
    ap.add_argument("--zero-shot", action="store_true")
    a = ap.parse_args()
    model_id = MODELS[a.model]
    train = [json.loads(line) for line in (ROOT / "finetune" / "data" / "train.jsonl").read_text().splitlines() if line.strip()]
    system, examples = train[0]["messages"][0]["content"], ([] if a.zero_shot else shots(train))
    msgs0 = []
    for ex in examples:
        msgs0 += [{"role": "user", "content": [{"text": ex["messages"][1]["content"]}]}, {"role": "assistant", "content": [{"text": ex["messages"][2]["content"]}]}]
    client = boto3.client("bedrock-runtime", region_name="us-east-1", config=Config(retries={"max_attempts": 12, "mode": "adaptive"}, read_timeout=120))
    price = pricing.PRICES[model_id]

    report: dict = {"model": model_id, "few_shot": not a.zero_shot, "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "sets": {}}
    for name, (data_dir, cases_path) in SETS.items():
        settings.data_dir = ROOT / data_dir
        cases = json.loads((ROOT / cases_path).read_text())
        preds = []
        for c in cases:
            ex = data.extract_claim(c["claim_id"])
            t0 = time.perf_counter()
            r = client.converse(modelId=model_id, system=[{"text": system}], messages=msgs0 + [{"role": "user", "content": [{"text": ex["narrative"]}]}],
                                inferenceConfig={"maxTokens": 80, "temperature": 0.0})
            sec = time.perf_counter() - t0
            flags, valid = parse_flags(r["output"]["message"]["content"][0]["text"])
            u = r["usage"]
            cost = (u["inputTokens"] * price["in"] + u["outputTokens"] * price["out"]) / 1e6
            facts = data.facts_from(ex, {k: bool(flags.get(k, False)) for k in FLAGS})
            d = adjudicate(facts, data.schedule_for(ex["policy_no"]))
            preds.append({"claim_id": c["claim_id"], "scenario": c["scenario"], "decision": d.decision, "clauses": d.clauses, "payable": d.payable,
                          "latency_ms": round(sec * 1000), "input_tokens": u["inputTokens"], "output_tokens": u["outputTokens"], "model_calls": 1,
                          "cost_usd": round(cost, 6), "flags": flags, "valid_json": valid, "alerts": 0})
            print(f"{name} {c['claim_id']} {c['scenario']:16} -> {d.decision:8} (expected {c['expected']['decision']})", flush=True)
        m = score(cases, preds)
        wrong = [{"claim_id": c["claim_id"], "scenario": c["scenario"], "expected": c["expected"]["decision"], "got": p["decision"], "flags": p["flags"]}
                 for c, p in zip(cases, preds, strict=True) if p["decision"] != c["expected"]["decision"]]
        report["sets"][name] = {"metrics": m, "mean_cost_usd": round(sum(p["cost_usd"] for p in preds) / len(preds), 6),
                                "mean_latency_s": round(sum(p["latency_ms"] for p in preds) / len(preds) / 1000, 2), "wrong": wrong, "predictions": preds}
        print(f"=== {name}: accuracy {m['decision_accuracy']}, unsafe approvals {m['unsafe_approvals']}, payable exact {m['payable_exact']}, "
              f"wrong {len(wrong)} of {len(cases)}", flush=True)
        (ROOT / "evals" / "reports" / f"single_call_baseline_{a.model}{'_zero' if a.zero_shot else ''}.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
