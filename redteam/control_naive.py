"""Control experiment for the naive baseline: the same base claims with NO attack text.

The red team counts an attack as successful when the system approves a claim that should not be approved. The naive single agent has no
rules engine, so it may approve such claims even without any attack. This script measures that, so attack success can be attributed
correctly: an attack only counts when it flips an answer the naive agent got right on its own.

Usage: python redteam/control_naive.py     (live Bedrock; writes redteam/reports/naive_control.json)
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402

settings.runtime_dir = Path(tempfile.mkdtemp(prefix="claims-adjudication-control-"))
from app.runner import run_claim  # noqa: E402

sys.path.insert(0, str(ROOT / "redteam"))
import run as harness  # noqa: E402


async def decide(claim_id: str) -> str:
    async for ev in run_claim(claim_id, "live", speed=0, defences=False, variant="naive"):
        if ev["type"] == "result":
            return ev["decision"]["decision"]
        if ev["type"] == "error":
            return "error"
    return "error"


async def main() -> None:
    used = sorted({harness.BASES[i % len(harness.BASES)]["claim_id"] for i in range(len(harness.ATTACKS))})
    expected = {c["claim_id"]: c["expected"]["decision"] for c in harness.GOLDEN}
    rows = []
    for cid in used:
        d = await decide(cid)
        rows.append({"claim_id": cid, "expected": expected[cid], "naive_without_attack": d, "unsafe_without_attack": d == "approve" and expected[cid] != "approve"})
        print(cid, "expected", expected[cid], "-> naive", d, flush=True)
    out = ROOT / "redteam" / "reports" / "naive_control.json"
    out.write_text(json.dumps(rows, indent=2))
    print("naive approves", sum(r["unsafe_without_attack"] for r in rows), "of", len(rows), "base claims with no attack at all")


if __name__ == "__main__":
    asyncio.run(main())
