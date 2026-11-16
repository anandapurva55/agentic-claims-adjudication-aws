"""The free-form benchmark is only worth reporting if its construction is sound. The first run scored the agent team 92.7%, and every miss traced to a flaw in how the
claims were built (a tyre-only narrative arrived with an estimate listing a windshield). These tests pin the properties that flaw broke."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

NARRATIVES = json.loads((HERE / "narratives.json").read_text())
FLAGS = ("intoxicated", "commercial_use", "unlicensed_driver", "mechanical_failure", "tyre_only", "theft")


def test_every_kept_narrative_was_labelled_the_same_by_an_independent_model():
    kept = [n for n in NARRATIVES["narratives"] if n["verified"]]
    assert len(kept) == NARRATIVES["kept"] >= 100
    assert all(n["verifier_flags"] == n["flags"] for n in kept), "a kept narrative must carry the label the verifier gave it"
    assert NARRATIVES["writer"] != NARRATIVES["verifier"]
    assert not any(m in NARRATIVES["writer"] + NARRATIVES["verifier"] for m in ("anthropic", "amazon", "nova", "claude")), "neither may be a model the product uses"


def test_nothing_is_dropped_silently():
    dropped = [n for n in NARRATIVES["narratives"] if not n["verified"]]
    assert len(dropped) == NARRATIVES["dropped"] and all(n["dropped_because"] for n in dropped)
    assert NARRATIVES["written"] == NARRATIVES["kept"] + NARRATIVES["dropped"]


def test_the_set_covers_every_flag_and_includes_negated_decoys_and_implicit_cases():
    kept = [n for n in NARRATIVES["narratives"] if n["verified"]]
    for f in FLAGS:
        assert sum(n["flags"][f] for n in kept) >= 10, f
    assert sum(not any(n["flags"].values()) for n in kept) >= 30
    assert sum(n["decoy"] for n in kept) >= 10 and sum(n["implicit"] for n in kept) >= 30


@pytest.fixture(scope="module")
def built():
    import build  # writes data/freeform and evals/golden/freeform_cases.json: deterministic, a couple of seconds
    build.main()
    from app.config import settings
    from app.services import data
    old = settings.data_dir
    settings.data_dir = ROOT / "data" / "freeform"  # the settings may already be loaded, so point them at the benchmark explicitly
    data.policies.cache_clear()
    yield json.loads((ROOT / "evals" / "golden" / "freeform_cases.json").read_text()), data
    settings.data_dir = old
    data.policies.cache_clear()


def test_the_estimate_agrees_with_the_narrative(built):
    """The flaw from the first run: a tyre-only narrative must come with a tyre-only estimate, and a breakdown with repair lines for a breakdown."""
    cases, data = built
    for c in cases:
        lines = [ln["name"].lower() for ln in data.extract_claim(c["claim_id"])["lines"]]
        flags = c["expected"]["flags"]
        if flags["tyre_only"]:
            assert lines and all("tyre" in ln for ln in lines), (c["claim_id"], lines)
        elif flags["mechanical_failure"]:
            assert lines and all(any(w in ln for w in ("engine", "gearbox", "clutch", "wiring", "dashboard")) for ln in lines), (c["claim_id"], lines)
        elif not flags["theft"]:
            assert not any("tyre" in ln for ln in lines), (c["claim_id"], lines)  # a collision claim never lists a tyre-only estimate


def test_the_expected_outcome_is_what_the_engine_gives_for_the_verified_flags(built):
    from app.rules import adjudicate
    cases, data = built
    for c in cases:
        ex = data.extract_claim(c["claim_id"])
        d = adjudicate(data.facts_from(ex, c["expected"]["flags"]), data.schedule_for(c["policy_no"]))
        assert (d.decision, d.payable) == (c["expected"]["decision"], c["expected"]["payable"]), c["claim_id"]


def test_the_cases_are_reproducible(built):
    cases, _ = built
    import build
    build.main()
    assert json.loads((ROOT / "evals" / "golden" / "freeform_cases.json").read_text()) == cases
