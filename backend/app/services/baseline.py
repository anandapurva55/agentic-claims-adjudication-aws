"""Keyword baseline for the judgement flags.

This is what the LLM intake agent is measured against. It is deliberately simple:
a competent engineer could write it in an afternoon, so beating it is meaningful.
"""
from __future__ import annotations

import re

PATTERNS = {
    "intoxicated": r"\b(drink|drinks|drinking|drunk|alcohol|intoxicat\w*|liquor|under the influence)\b",
    "commercial_use": r"\b(delivery|deliver|taxi|cab ride|ride.?share|passengers? for hire|commercial)\b",
    "unlicensed_driver": r"\b(does not hold a driving licen[cs]e|without a (valid )?licen[cs]e|no (valid )?driving licen[cs]e|unlicensed)\b",
    "mechanical_failure": r"\b(engine failed|engine overhaul|gearbox|breakdown|broke down|no collision)\b",
    "tyre_only": r"\b(no other damage)\b",
    "theft": r"\b(stolen|theft)\b",
}


def keyword_flags(narrative: str) -> dict[str, bool]:
    t = narrative.lower()
    return {k: bool(re.search(p, t)) for k, p in PATTERNS.items()}
