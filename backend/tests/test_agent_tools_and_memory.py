"""The tools the agents call, long-term memory, and the naive baseline's answer parser. Tools hold the arithmetic and the audit trail, so a mistake here
changes money or hides evidence; memory is the one place a customer's text could plant a lesson, so its write path is pinned too."""
import json
import uuid

import pytest
from app import memory, tools
from app.agents import naive
from app.config import settings
from app.rules import adjudicate
from app.runstate import RunState, set_state
from app.services import data, policy_search

CASES = json.load(open("evals/golden/cases.json"))
CLEAN = next(c for c in CASES if c["expected"]["decision"] == "approve")


@pytest.fixture(autouse=True)
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    monkeypatch.setattr(settings, "mode", "replay")
    s = RunState(claim_id=CLEAN["claim_id"], extracted=data.extract_claim(CLEAN["claim_id"]))
    set_state(s)
    return s


NO_FLAGS = dict(intoxicated=False, commercial_use=False, unlicensed_driver=False, mechanical_failure=False, tyre_only=False, theft=False)


# ---- tools ---------------------------------------------------------------------------------------------------------------------------------------

def test_get_claim_packet_returns_the_extracted_fields(run):
    assert tools.get_claim_packet(CLEAN["claim_id"]) == run.extracted


def test_record_judgement_sets_flags_evidence_and_facts(run):
    assert tools.record_judgement(**{**NO_FLAGS, "intoxicated": True}, evidence="had two beers") == "recorded"
    assert run.flags["intoxicated"] is True and run.evidence == {"quote": "had two beers"} and run.facts.intoxicated is True


def test_finalize_decision_applies_the_engine_and_cites_only_known_clauses(run):
    tools.record_judgement(**NO_FLAGS, evidence="")
    out = tools.finalize_decision(CLEAN["claim_id"])
    expected = adjudicate(run.facts, data.schedule_for(run.extracted["policy_no"]))
    assert out["decision"] == expected.decision == CLEAN["expected"]["decision"] and out["payable"] == expected.payable
    assert {c["clause"] for c in run.citations} == set(expected.clauses)


def test_calculate_payable_uses_the_recorded_flags(run):
    tools.record_judgement(**NO_FLAGS, evidence="")
    assert tools.calculate_payable(CLEAN["claim_id"])["payable"] == CLEAN["expected"]["payable"]


def test_calculate_payable_works_before_any_judgement_is_recorded(run):
    assert tools.calculate_payable(CLEAN["claim_id"])["payable"] >= 0


def test_check_consistency_is_quiet_for_a_clean_claim_and_lists_each_mismatch(run):
    assert tools.check_consistency(CLEAN["claim_id"])["issues"] == []
    run.extracted.update(estimate_reg="XX99ZZ9999", estimate_total=run.extracted["claimed_amount"] + 1, vehicle_reg="YY00AA0000")
    issues = tools.check_consistency(CLEAN["claim_id"])["issues"]
    assert len(issues) == 3 and any("Registration mismatch" in i for i in issues) and any("Amount mismatch" in i for i in issues)


def test_record_risk_signal_clamps_severity_and_truncates_detail(run):
    tools.record_risk_signal("garage", "catastrophic", "x" * 500)
    tools.record_risk_signal("repeat_claim", "high", "third claim in a year")
    assert [(s["severity"], len(s["detail"])) for s in run.signals] == [("low", 300), ("high", 21)]


def test_post_note_rejects_unknown_kinds_and_recipients_and_truncates(run):
    assert tools.post_note("fraud", "policy", "gossip", "x").startswith("rejected")
    assert tools.post_note("fraud", "the internet", "note", "x").startswith("rejected")
    assert run.notes == []
    assert tools.post_note("fraud", "policy", "question", "y" * 900) == "posted"
    assert len(run.notes[0]["text"]) == 400 and tools.read_notes() == run.notes


def test_read_notes_says_so_when_empty():
    assert tools.read_notes() == [{"text": "No notes yet."}]


def test_search_policy_wording_adds_each_citation_once(run, monkeypatch):
    hit = {"clause": "SEC1.DEP", "text": "depreciation", "source": "x"}
    monkeypatch.setattr(policy_search, "search", lambda q: [hit])
    tools.search_policy_wording("depreciation")
    tools.search_policy_wording("depreciation again")
    assert run.citations == [hit]


def test_recall_lessons_dedupes_and_has_a_placeholder_when_nothing_matches(run, monkeypatch):
    lesson = {"text": "Delivery work counts as commercial use", "score": 3.0}
    monkeypatch.setattr(memory, "recall", lambda q: [lesson])
    tools.recall_lessons("food delivery")
    tools.recall_lessons("food delivery")
    assert run.lessons == [lesson]
    monkeypatch.setattr(memory, "recall", lambda q: [])
    assert tools.recall_lessons("nothing")[0]["text"] == "No relevant lessons."


# ---- long-term memory ----------------------------------------------------------------------------------------------------------------------------

def test_a_stored_lesson_is_recalled_by_meaning_overlap_and_unrelated_text_is_not():
    text = "Hospital transport for a passenger is not commercial use of the vehicle"
    assert memory.store_lesson(text, {"claim_id": "C1"}) is True
    hits = memory.recall("was the passenger transport to hospital commercial use")
    assert any(h["text"] == text and h["source"] == "adjuster" for h in hits)
    assert not [h for h in memory.recall("zebra giraffe antelope savanna") if h["text"] == text]


def test_lessons_that_are_too_short_are_refused():
    assert memory.store_lesson("  ok  ", {}) is False and memory.store_lesson("", {}) is False


def test_recall_returns_nothing_when_memory_is_off_or_the_query_is_blank(monkeypatch):
    memory.store_lesson("Pre-existing damage must be proven with dated photos", {})
    assert memory.recall("   ") == []
    monkeypatch.setattr(settings, "memory_enabled", False)
    assert memory.recall("dated photos pre-existing damage") == []


class FakeAgentCore:
    def __init__(self, records=None, fail=False):
        self.records, self.fail, self.created, self.events = records or [], fail, [], []

    def retrieve_memory_records(self, **kw):
        self.query = kw
        return {"memoryRecordSummaries": self.records}

    def batch_create_memory_records(self, **kw):
        self.created.append(kw)

    def create_event(self, **kw):
        if self.fail:
            raise RuntimeError("throttled")
        self.events.append(kw)


@pytest.fixture
def live(monkeypatch):
    fake = FakeAgentCore([{"content": {"text": "relevant"}, "score": 0.47}, {"content": {"text": "unrelated"}, "score": 0.36}, {"content": {"text": "no score"}}])
    monkeypatch.setattr(settings, "mode", "live")
    monkeypatch.setattr(settings, "memory_id", "mem-1")
    monkeypatch.setattr(memory, "_client", lambda: fake)
    monkeypatch.setattr(memory, "_strategy_id", lambda: "strat-1")
    return fake


def test_live_recall_keeps_only_records_above_the_relevance_threshold(live):
    hits = memory.recall("is this commercial use", k=2)
    assert [h["text"] for h in hits] == ["relevant"] and hits[0]["source"] == "agentcore"
    assert live.query["searchCriteria"] == {"searchQuery": "is this commercial use", "memoryStrategyId": "strat-1", "topK": 2}


def test_live_store_writes_one_record_in_the_lessons_namespace(live):
    assert memory.store_lesson("Always ask for the FIR when theft is claimed", {"claim_id": "C9"}) is True
    rec = live.created[0]["records"][0]
    assert live.created[0]["memoryId"] == "mem-1" and rec["namespaces"] == [memory.NAMESPACE] and rec["memoryStrategyId"] == "strat-1"
    uuid.UUID(rec["requestIdentifier"])


def test_log_event_is_a_noop_offline_and_mirrors_notes_live(live, monkeypatch):
    memory.log_event("C1", "fraud", "x" * 3000)
    assert len(live.events[0]["payload"][0]["conversational"]["content"]["text"]) == 1500 and live.events[0]["sessionId"] == "C1"
    monkeypatch.setattr(settings, "mode", "replay")
    memory.log_event("C1", "fraud", "offline")
    assert len(live.events) == 1


def test_a_memory_outage_never_fails_a_claim(live):
    live.fail = True
    memory.log_event("C1", "fraud", "note")  # must not raise


def test_agents_have_no_tool_that_writes_memory():
    """The only write path into long-term memory is the human review path. Guard it: no agent tool may call store_lesson."""
    src = open(tools.__file__).read()
    assert "store_lesson" not in src


# ---- naive baseline parser -----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Looks fine.\nDECISION: approve\nPAYABLE: 12,500", ("approve", 12500)),
    ("DECISION: **deny**\nPAYABLE: ₹0", ("deny", 0)),
    ("decision: Refer\npayable: INR 4,000", ("refer", 4000)),
    ("DECISION: approve", ("approve", 0)),
    ("I think this should be paid.", ("refer", 0)),
    ("DECISION: maybe\nPAYABLE: lots", ("refer", 0))])
def test_naive_parse_defaults_to_refer_never_to_approve(text, expected):
    assert naive.parse(text) == expected


def test_naive_search_tool_delegates_to_policy_search(monkeypatch):
    monkeypatch.setattr(policy_search, "search", lambda q: [{"clause": q}])
    assert naive.search_policy_wording("exclusions") == [{"clause": "exclusions"}]
