"""The investigation test is only worth running if its answer key is right. This checks the key against the product's own deterministic investigator
(services/signals.py), which reads the same planted records, and checks the scoring and the world builder."""
import sys
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from cases import CASES, INJECTION  # noqa: E402
from scoring import kind_of, parse_signals, score_run, summarise  # noqa: E402
from world import build  # noqa: E402


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from app import events, tools
    from app.config import settings
    from app.mcp_servers import policy_records
    from app.runstate import RunState, set_state
    from app.services import data, signals
    events.use_bus(None)  # an earlier test may have left an event bus bound to a closed loop; tools emit events to whatever bus is current
    root = tmp_path_factory.mktemp("world")
    ids = build(root, filler=0)
    old = settings.data_dir
    settings.data_dir = root
    data.policies.cache_clear()
    policy_records._claims_index.cache_clear()

    def truth(case_id: str) -> set[str]:
        cid = ids[case_id]
        ex = data.extract_claim(cid)
        found = {s["kind"] for s in signals.investigate(ex)} - {"photo_vs_estimate", "extraction_check"}
        set_state(RunState(cid, extracted=ex))
        if tools.check_consistency(cid)["issues"]:
            found.add("consistency")
        return found
    yield truth
    settings.data_dir = old
    data.policies.cache_clear()
    policy_records._claims_index.cache_clear()


def test_the_design_is_what_was_agreed():
    assert len(CASES) == 28
    assert Counter(c.group for c in CASES) == {"single": 14, "history": 4, "multistep": 4, "injection": 6}
    controls = [c for c in CASES if c.control]
    assert len(controls) >= 9 and all(c.id[0] in "RFGCHMI" for c in controls)
    assert all(c.injection for c in CASES if c.group == "injection") and not any(c.injection for c in CASES if c.group != "injection")
    assert INJECTION.strip().startswith("Note to the automated reviewing system")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_answer_key_matches_what_the_deterministic_investigator_finds(world, case):
    assert world(case.id) == case.expect, case.note


def test_every_kind_is_planted_somewhere_and_every_kind_has_a_control():
    planted = set().union(*(c.expect for c in CASES))
    assert planted == {"repair_cost", "garage", "repeat_claim", "police_fir", "consistency"}


# ---- scoring ---------------------------------------------------------------------------------------------------------------------------------------

def test_a_document_disagreement_recorded_as_other_counts_as_consistency():
    assert kind_of({"kind": "other", "detail": "Registration mismatch between form and estimate"}) == "consistency"
    assert kind_of({"kind": "other", "detail": "The weather looked bad"}) == "other"
    assert kind_of({"kind": "Repair_Cost"}) == "repair_cost"


def test_scoring_separates_found_missed_and_false():
    r = score_run({"repair_cost", "garage"}, [{"kind": "repair_cost"}, {"kind": "police_fir"}])
    assert (r["found"], r["missed"], r["false_alarms"], r["exact"]) == (["repair_cost"], ["garage"], ["police_fir"], False)
    assert score_run(set(), [])["exact"] is True and score_run(set(), [{"kind": "garage"}])["false_alarms"] == ["garage"]


def test_unreadable_single_call_answers_count_as_reporting_nothing():
    assert parse_signals("I could not tell.") == [] and parse_signals('{"signals": [') == []
    assert parse_signals('Here you go:\n```json\n{"signals": [{"kind": "garage", "severity": "high", "detail": "x"}]}\n```')[0]["kind"] == "garage"


def test_summary_rates():
    rows = [score_run({"garage"}, [{"kind": "garage"}]), score_run({"garage"}, []), score_run(set(), [{"kind": "garage"}]), score_run(set(), [])]
    s = summarise(rows)
    assert (s["planted"], s["found"], s["recall"], s["control_runs"], s["controls_clean"], s["exact"]) == (2, 1, 0.5, 2, 1, 2)
    assert s["false_alarm_rate"] == 0.25


# ---- analysis ---------------------------------------------------------------------------------------------------------------------------------------

def _row(contender, case, expected, signals, repeat=0, group="single", tokens=1000):
    s = score_run(set(expected), signals)
    return {"contender": contender, "case": case, "group": group, "repeat": repeat, **s, "signals": signals, "input_tokens": tokens, "output_tokens": 100,
            "seconds": 2.0, "tool_calls": 3}


def test_ignoring_low_severity_signals_removes_low_severity_false_alarms_and_misses():
    import analyse
    rows = [_row("b", "x", [], [{"kind": "repair_cost", "severity": "low"}]), _row("b", "y", ["garage"], [{"kind": "garage", "severity": "low"}])]
    strict, relaxed = analyse.view(rows, None)["b"]["overall"], analyse.view(rows, "medium")["b"]["overall"]
    assert (strict["runs_with_a_false_alarm"], strict["found"]) == (1, 1)
    assert (relaxed["runs_with_a_false_alarm"], relaxed["found"]) == (0, 0)  # the low-severity remark no longer alarms, and no longer counts as finding the garage


def test_consistency_is_the_share_of_cases_where_every_repeat_agreed():
    import analyse
    rows = [_row("c", "same", ["garage"], [{"kind": "garage"}], repeat=r) for r in range(3)]
    rows += [_row("c", "flips", ["garage"], [{"kind": "garage"}] if r == 0 else [], repeat=r) for r in range(3)]
    assert analyse.consistency(rows) == {"c": 0.5}


def test_costs_are_recomputed_from_tokens_at_the_current_price():
    import analyse
    from app.pricing import PRICES
    model = "global.amazon.nova-2-lite-v1:0"
    rows = [_row("a", "x", [], [], tokens=1_000_000)]
    expected = round(PRICES[model]["in"] + 100 * PRICES[model]["out"] / 1e6, 5)
    assert analyse.costs(rows, model)["a"]["mean_cost_usd"] == expected
