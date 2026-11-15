"""Scoring shared by every system in the fine-tune comparison, so all numbers come from the same code. Pure Python, no heavy imports."""
from __future__ import annotations

import json
import re

FLAGS = ["intoxicated", "commercial_use", "unlicensed_driver", "mechanical_failure", "tyre_only", "theft"]
DENY_FLAGS = ["intoxicated", "commercial_use", "unlicensed_driver"]  # missing one of these lets a bad claim through


def parse_flags(text: str) -> tuple[dict[str, bool], bool]:
    """Pull the JSON out of a model answer. Anything unparseable counts as all false, and is counted as invalid."""
    m = re.search(r"\{.*?\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
        return {f: bool(d.get(f, False)) for f in FLAGS}, bool(m) and all(f in d for f in FLAGS)
    except Exception:
        return {f: False for f in FLAGS}, False


def score(rows: list[dict]) -> dict:
    """Per flag precision, recall and F1, micro F1, exact match on all six flags, and how often the answer was not valid JSON.

    Each row needs `gold` and `pred` (dicts of flag to bool) and `valid`. `missed_denials` counts true intoxicated, commercial or
    unlicensed flags the system failed to raise, which would let a claim that must be denied through. `false_denials` is the opposite.
    """
    out: dict = {"n": len(rows), "invalid_json": round(sum(not r["valid"] for r in rows) / len(rows), 4), "per_flag": {}}
    tp_all = fp_all = fn_all = 0
    for f in FLAGS:
        tp = sum(r["pred"][f] and r["gold"][f] for r in rows)
        fp = sum(r["pred"][f] and not r["gold"][f] for r in rows)
        fn = sum(not r["pred"][f] and r["gold"][f] for r in rows)
        p, rc = (tp / (tp + fp) if tp + fp else 0.0), (tp / (tp + fn) if tp + fn else 0.0)
        out["per_flag"][f] = {"precision": round(p, 3), "recall": round(rc, 3), "f1": round(2 * p * rc / (p + rc), 3) if p + rc else 0.0,
                              "false_pos": fp, "false_neg": fn}
        tp_all, fp_all, fn_all = tp_all + tp, fp_all + fp, fn_all + fn
    p, rc = tp_all / (tp_all + fp_all) if tp_all + fp_all else 0.0, tp_all / (tp_all + fn_all) if tp_all + fn_all else 0.0
    out["micro_f1"] = round(2 * p * rc / (p + rc), 4) if p + rc else 0.0
    out["exact_match"] = round(sum(r["pred"] == r["gold"] for r in rows) / len(rows), 4)
    out["missed_denials"] = sum(r["gold"][f] and not r["pred"][f] for r in rows for f in DENY_FLAGS)
    out["false_denials"] = sum(r["pred"][f] and not r["gold"][f] for r in rows for f in DENY_FLAGS)
    return out
