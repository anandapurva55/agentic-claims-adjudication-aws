"""Damaged-part recognition on the 70 real photos: Bedrock vision models, scored exactly like Amazon Bedrock Data Automation (evals/reports/bda_photo.json).

  python evals/vision_eval.py --models nova-2-lite,claude-haiku-4.5,claude-sonnet-4.6
The ground truth is the dataset's own part annotations (Kaggle Coco Car Damage Detection Dataset, CC0).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "real" / "car_damage_coco"
MODELS = {"nova-2-lite": "global.amazon.nova-2-lite-v1:0", "claude-haiku-4.5": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
          "claude-sonnet-4.6": "global.anthropic.claude-sonnet-4-6"}
PARTS = ["headlamp", "front_bumper", "rear_bumper", "hood", "door"]
PROMPT = ("This photo was submitted as evidence for a motor insurance claim. List the vehicle parts that are visibly damaged. "
          "Use only these words: headlamp, front_bumper, rear_bumper, hood, door. Leave out any part that is not clearly damaged. "
          'Answer with JSON only, like {"damaged_parts": ["door"]}.')


def truth() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(SRC.glob("*/COCO_mul_*_annos.json")):
        d = json.loads(f.read_text())
        cat, img = {c["id"]: c["name"] for c in d["categories"]}, {i["id"]: i["file_name"] for i in d["images"]}
        for a in d["annotations"]:
            out.setdefault(img[a["image_id"]], set()).add(cat[a["category_id"]])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(MODELS))
    a = ap.parse_args()
    client = boto3.client("bedrock-runtime", region_name="us-east-1", config=Config(retries={"max_attempts": 12, "mode": "adaptive"}, read_timeout=120))
    t = truth()
    files = {p.name: p for p in SRC.glob("img/*.jpg") if p.name in t}
    report, predictions = {}, {}
    for label in a.models.split(","):
        def one(name: str, label: str = label) -> tuple[str, set[str], float]:
            t0 = time.perf_counter()
            r = client.converse(modelId=MODELS[label], messages=[{"role": "user", "content": [
                {"image": {"format": "jpeg", "source": {"bytes": files[name].read_bytes()}}}, {"text": PROMPT}]}], inferenceConfig={"maxTokens": 100, "temperature": 0.0})
            txt = r["output"]["message"]["content"][0]["text"]
            m = re.search(r"\{.*\}", txt, re.S)
            try:
                got = {str(p).lower() for p in json.loads(m.group(0)).get("damaged_parts", [])} & set(PARTS) if m else set()
            except json.JSONDecodeError:
                got = set()
            return name, got, time.perf_counter() - t0
        with ThreadPoolExecutor(3) as pool:
            res = list(pool.map(one, sorted(files)))
        tp = sum(len(g & t[n]) for n, g, _ in res)
        fp = sum(len(g - t[n]) for n, g, _ in res)
        fn = sum(len(t[n] - g) for n, g, _ in res)
        p, rc = tp / max(1, tp + fp), tp / max(1, tp + fn)
        report[label] = {"photos": len(res), "precision": round(p, 3), "recall": round(rc, 3), "f1": round(2 * p * rc / max(1e-9, p + rc), 3),
                         "exact_set_match": sum(g == t[n] for n, g, _ in res), "mean_seconds": round(sum(s for *_, s in res) / len(res), 1),
                         "headlamp_recall": round(sum("headlamp" in g and "headlamp" in t[n] for n, g, _ in res) / max(1, sum("headlamp" in t[n] for n in t if n in files)), 3)}
        predictions[label] = {n: sorted(g) for n, g, _ in res}
        print(label, json.dumps(report[label]), flush=True)
        (ROOT / "evals" / "reports" / "vision_models.json").write_text(json.dumps(report, indent=1))
        (ROOT / "evals" / "reports" / "vision_predictions.json").write_text(json.dumps(predictions))


if __name__ == "__main__":
    main()
