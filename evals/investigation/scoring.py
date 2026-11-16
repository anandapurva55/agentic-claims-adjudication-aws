"""Scoring for the investigation test: which planted problems were found, which signals were false alarms."""
from __future__ import annotations

import json
import re

KINDS = ("repair_cost", "garage", "repeat_claim", "police_fir", "consistency")
CONSISTENCY_WORDS = re.compile(r"mismatch|differ|disagree|does not match|not match|inconsisten", re.I)


def kind_of(signal: dict) -> str:
    """The agent's own tool takes kind=other for anything outside its four named kinds, so a document disagreement arrives as 'other'. Read it by its words."""
    kind = str(signal.get("kind", "")).strip().lower()
    if kind in KINDS:
        return kind
    if kind in ("other", "consistency", "document", "documents", "documents_mismatch") and CONSISTENCY_WORDS.search(str(signal.get("detail", ""))):
        return "consistency"
    return kind or "other"


def parse_signals(text: str) -> list[dict]:
    """A single call answers in JSON, possibly wrapped in prose or a code fence. An unreadable answer counts as reporting nothing."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        got = json.loads(m.group(0)).get("signals", []) if m else []
    except json.JSONDecodeError:
        return []
    return [s for s in got if isinstance(s, dict)]


def score_run(expected: set[str], signals: list[dict]) -> dict:
    predicted = {kind_of(s) for s in signals}
    found, missed, false = expected & predicted, expected - predicted, predicted - expected
    return {"expected": sorted(expected), "predicted": sorted(predicted), "found": sorted(found), "missed": sorted(missed), "false_alarms": sorted(false),
            "exact": predicted == expected}


def summarise(rows: list[dict]) -> dict:
    """Aggregate scored runs: share of planted problems found, share of runs with a false alarm, and exact matches."""
    planted = sum(len(r["expected"]) for r in rows)
    found = sum(len(r["found"]) for r in rows)
    controls = [r for r in rows if not r["expected"]]
    return {"runs": len(rows), "planted": planted, "found": found, "recall": round(found / planted, 3) if planted else None,
            "runs_with_a_false_alarm": sum(bool(r["false_alarms"]) for r in rows), "false_alarm_rate": round(sum(bool(r["false_alarms"]) for r in rows) / len(rows), 3) if rows else None,
            "control_runs": len(controls), "controls_clean": sum(not r["false_alarms"] for r in controls),
            "exact": sum(r["exact"] for r in rows), "exact_rate": round(sum(r["exact"] for r in rows) / len(rows), 3) if rows else None}
