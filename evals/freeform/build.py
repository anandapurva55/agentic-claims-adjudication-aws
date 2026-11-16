"""Turn the verified free-form narratives into claims the evaluation runner can score.

  python evals/freeform/build.py

Reads evals/freeform/narratives.json (written by generate.py and committed). Writes data/freeform (real claim form and estimate PDFs, the same layout the
product reads) and evals/golden/freeform_cases.json. The expected decision for each claim comes from the rules engine applied to the VERIFIED labels, so what
is being tested is whether a system reads the narrative correctly. The engine itself is checked separately against 20 hand-calculated claims.
Run the systems on it with:  CLAIMS_DATA_DIR=data/freeform CLAIMS_CASES=evals/golden/freeform_cases.json python evals/run_eval.py --mode live
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
OUT = ROOT / "data" / "freeform"
os.environ["CLAIMS_DATA_DIR"] = str(OUT)  # the product reads policies and rules from here
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals" / "investigation"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.rules import adjudicate  # noqa: E402
from app.services import data  # noqa: E402
from app.services.extract import LocalPdfExtractor  # noqa: E402
from generate_data import PARTS  # noqa: E402  (the parts and prices the other claim sets use)
from world import write_claim  # noqa: E402

FLAGS = ("intoxicated", "commercial_use", "unlicensed_driver", "mechanical_failure", "tyre_only", "theft")


def mechanical_lines(brief: str) -> list[tuple[str, str, int]]:
    """Repair lines that match the breakdown the narrative describes."""
    b = brief.lower()
    if "gearbox" in b:
        return [("Gearbox repair", "metal", 38000)]
    if "clutch" in b:
        return [("Clutch plate replacement", "metal", 18000)]
    if "short circuit" in b or "wiring" in b:
        return [("Wiring harness repair", "metal", 15000), ("Dashboard replacement", "plastic", 22000)]
    return [("Engine overhaul", "metal", 60000)]


def main() -> None:
    src = json.loads((HERE / "narratives.json").read_text())
    kept = [n for n in src["narratives"] if n["verified"]]
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "claims").mkdir(parents=True)
    for name in ("policies.json", "rules.json", "lessons_seed.json"):
        shutil.copy(ROOT / "data" / name, OUT / name)
    policies = json.loads((OUT / "policies.json").read_text())
    rng, cases = random.Random(7), []
    for i, n in enumerate(kept, 1):
        pol = rng.choice(policies)
        start, end = date.fromisoformat(pol["start"]), date.fromisoformat(pol["end"])
        incident = start + timedelta(days=rng.randint(10, max(11, (end - start).days - 20)))
        theft = n["flags"]["theft"]
        lines = [(nm, cat, cost) for nm, cat, cost in rng.sample(PARTS, 1 if theft else rng.randint(1, 3))]
        labour, total = rng.randint(3, 9) * 1000, 0
        # The estimate must agree with the narrative, as a real garage's would. The first version of this builder gave every claim random body-repair lines, so a
        # "tyre only" narrative arrived with an estimate listing a windshield and a radiator. The agents cross-check the two and (reasonably) would not call
        # it tyre-only, which scored them against a contradiction I had built in. See the README for that first run.
        if n["flags"]["tyre_only"]:
            count = rng.randint(1, 4)
            lines, labour = [(f"Tyre replacement x{count}", "rubber", 7000 * count)], 800
        elif n["flags"]["mechanical_failure"]:
            lines, labour = mechanical_lines(n["brief"]), rng.randint(2, 6) * 1000
        if theft:  # a stolen car is claimed at its insured value, not as repairs
            lines, labour = [("Vehicle replacement value", "metal", pol["idv"])], 0
        total = sum(c for _, _, c in lines) + labour
        fir = (i % 2 == 0) if theft else None
        cid = f"CLM-{5000000 + i}"
        write_claim(OUT, cid, pol, incident, lines, labour, total, total, "AutoCare Works", n["narrative"], fir)
        ex = LocalPdfExtractor().extract(OUT / "claims" / cid)
        decision = adjudicate(data.facts_from(ex, n["flags"]), data.schedule_for(pol["policy_no"]))
        scenario = "ff_" + ("clean_decoy" if n["decoy"] else n["label"]) + ("_implicit" if n["implicit"] else "")
        cases.append({"claim_id": cid, "scenario": scenario, "policy_no": pol["policy_no"], "input_dir": f"data/freeform/claims/{cid}",
                      "expected": {"fields": {k: ex[k] for k in ("claim_id", "policy_no", "vehicle_reg", "incident_date", "report_date", "claimed_amount")},
                                   "decision": decision.decision, "clauses": decision.clauses, "payable": decision.payable, "injection": False, "flags": n["flags"]},
                      "narrative_id": n["id"]})
    (ROOT / "evals" / "golden" / "freeform_cases.json").write_text(json.dumps(cases, indent=2))
    from collections import Counter
    print(f"{len(cases)} claims; decisions {dict(Counter(c['expected']['decision'] for c in cases))}")
    print("scenarios:", dict(Counter(c["scenario"] for c in cases)))


if __name__ == "__main__":
    main()
