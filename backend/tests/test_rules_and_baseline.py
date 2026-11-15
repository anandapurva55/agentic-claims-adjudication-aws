"""Ground truth consistency, extraction fidelity and the keyword baseline."""
import json
from pathlib import Path

import pytest
from app.config import settings
from app.rules import adjudicate
from app.services import data
from app.services.baseline import keyword_flags

CASES = json.loads((Path(settings.data_dir).parent / "evals" / "golden" / "cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["claim_id"])
def test_extraction_matches_ground_truth(case):
    got = data.extract_claim(case["claim_id"])
    for key, value in case["expected"]["fields"].items():
        assert got[key] == value, key


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["claim_id"])
def test_engine_with_true_flags_reproduces_golden(case):
    """The calculator must be exactly right whenever the judgement flags are right."""
    extracted = data.extract_claim(case["claim_id"])
    facts = data.facts_from(extracted, case["expected"]["flags"])
    result = adjudicate(facts, data.schedule_for(case["policy_no"]))
    expected = case["expected"]
    assert result.decision == expected["decision"], result.reasons
    assert result.clauses == expected["clauses"]
    assert result.payable == expected["payable"]


def test_keyword_baseline_is_good_but_beatable():
    """Report baseline accuracy. It must be decent (so beating it means something) yet imperfect."""
    right = 0
    for case in CASES:
        extracted = data.extract_claim(case["claim_id"])
        facts = data.facts_from(extracted, keyword_flags(extracted["narrative"]))
        right += adjudicate(facts, data.schedule_for(case["policy_no"])).decision == case["expected"]["decision"]
    accuracy = right / len(CASES)
    print(f"keyword baseline decision accuracy: {accuracy:.1%} ({right}/{len(CASES)})")
    assert 0.70 <= accuracy < 1.0


REFER_ACTION = {"high_value": "senior adjuster", "reg_mismatch": "resubmit", "amount_mismatch": "resubmit",
                "late_notice": "reason for the delay", "theft_no_fir": "police FIR"}


@pytest.mark.parametrize("scenario,keyword", list(REFER_ACTION.items()))
def test_every_referral_names_a_concrete_next_action(scenario, keyword):
    case = next(c for c in CASES if c["scenario"] == scenario)
    facts = data.facts_from(data.extract_claim(case["claim_id"]), case["expected"]["flags"])
    result = adjudicate(facts, data.schedule_for(case["policy_no"]))
    assert result.decision == "refer"
    assert any(keyword.lower() in step.lower() for step in result.next_steps), result.next_steps


def test_all_outcomes_have_next_steps():
    for case in CASES:
        facts = data.facts_from(data.extract_claim(case["claim_id"]), case["expected"]["flags"])
        assert adjudicate(facts, data.schedule_for(case["policy_no"])).next_steps, case["claim_id"]
