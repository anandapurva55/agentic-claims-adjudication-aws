"""Prompt-attack defence for untrusted text (the incident narrative), applied before any agent reads it.

Live: Amazon Bedrock Guardrails (ApplyGuardrail, PROMPT_ATTACK filter). The whole narrative is checked first;
if it is blocked, each sentence is checked on its own so only the offending sentences are redacted and the
legitimate facts are still available to the agents.
Replay: a regex heuristic, clearly labelled as such in the UI, so the app runs with no AWS access.
"""
from __future__ import annotations

import re

from app.config import settings

_HEURISTIC = re.compile(r"ignore (all )?(previous|prior) instructions|system note|pre.?approved|do not mention", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _live_blocked(text: str) -> bool:
    import boto3
    r = boto3.client("bedrock-runtime", region_name=settings.region).apply_guardrail(
        guardrailIdentifier=settings.guardrail_id, guardrailVersion=settings.guardrail_version, source="INPUT",
        content=[{"text": {"text": text}}])
    return r["action"] == "GUARDRAIL_INTERVENED"


def sanitize(text: str) -> dict:
    live = settings.mode == "live" and bool(settings.guardrail_id)
    blocked = (lambda t: _live_blocked(t)) if live else (lambda t: bool(_HEURISTIC.search(t)))
    engine = "bedrock-guardrails" if live else "replay-heuristic"
    if not blocked(text):
        return {"clean": text, "alerts": [], "engine": engine}
    keep, alerts = [], []
    for sentence in _SPLIT.split(text):
        if blocked(sentence):
            alerts.append(sentence)
            keep.append("[sentence removed by guardrail: prompt attack]")
        else:
            keep.append(sentence)
    return {"clean": " ".join(keep), "alerts": alerts, "engine": engine}
