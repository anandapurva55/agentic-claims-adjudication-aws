"""Damaged-part recognition with a Bedrock vision model, used next to Amazon Bedrock Data Automation.

Bedrock Data Automation is precise but misses parts (precision 0.95, recall 0.51 on 70 real photos). A vision model finds more (recall 0.68) but is less
precise. The union of the two scored F1 0.80 against 0.76 and 0.66 for the single systems (evals/reports/photo_ensemble.json), so ingestion records both
and the product uses the union. Like Bedrock Data Automation it runs when a document arrives, not on the adjuster's click.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import boto3
from botocore.config import Config

from app.config import settings
from app.services.bda import PARTS

MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
MODEL_LABEL = "claude-haiku-4.5"
PROMPT = ("This photo was submitted as evidence for a motor insurance claim. List the vehicle parts that are visibly damaged. "
          "Use only these words: headlamp, front_bumper, rear_bumper, hood, door. Leave out any part that is not clearly damaged. "
          'Answer with JSON only, like {"damaged_parts": ["door"]}.')


def damaged_parts(path: Path) -> list[str]:
    client = boto3.client("bedrock-runtime", region_name=settings.region, config=Config(retries={"max_attempts": 12, "mode": "adaptive"}, read_timeout=120))
    r = client.converse(modelId=MODEL_ID, messages=[{"role": "user", "content": [
        {"image": {"format": "jpeg", "source": {"bytes": Path(path).read_bytes()}}}, {"text": PROMPT}]}], inferenceConfig={"maxTokens": 100, "temperature": 0.0})
    return parse(r["output"]["message"]["content"][0]["text"])


def parse(text: str) -> list[str]:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        got = json.loads(m.group(0)).get("damaged_parts", []) if m else []
    except json.JSONDecodeError:
        got = []
    return sorted({str(p).strip().lower() for p in got} & PARTS)
