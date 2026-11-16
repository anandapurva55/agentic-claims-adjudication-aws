"""The engine against answers worked out by hand (evals/golden/independent_cases.json). The golden labels were produced by the engine's own code, so they cannot
catch a rule that is wrong in both places. These twenty claims were calculated on paper from the policy wording, each on a boundary, with the working written out."""
import json
from pathlib import Path

import pytest
from app.rules import Facts, Line, Schedule, adjudicate

DOC = json.loads((Path(__file__).resolve().parents[2] / "evals" / "golden" / "independent_cases.json").read_text())
CASES = DOC["cases"]


def build(case: dict) -> tuple[Facts, Schedule]:
    c = {**DOC["defaults"], **case}
    lines = [Line(n, cat, cost) for n, cat, cost in c["lines"]]
    total = sum(ln.cost for ln in lines) + c["labour"]
    facts = Facts(c["id"], "P", "KA01", "KA01", c["incident"], c["reported"], total, total, lines, c["labour"], salvage=c["salvage"],
                  police_fir=c["police_fir"], theft=c["theft"])
    return facts, Schedule("P", c["idv"], c["deductible"], c["reg_year"], c["start"], c["end"], "KA01")


def test_there_are_twenty_independent_cases_with_working_shown():
    assert len(CASES) == 20 and len({c["id"] for c in CASES}) == 20
    assert all(len(c["working"]) > 40 for c in CASES), "every answer must show how it was worked out"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_engine_agrees_with_the_hand_calculation(case):
    facts, sched = build(case)
    d = adjudicate(facts, sched)
    assert (d.decision, d.payable, d.clauses) == (case["expect"]["decision"], case["expect"]["payable"], case["expect"]["clauses"]), case["working"]
