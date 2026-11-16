"""Findings the rules can reach must not depend on a model remembering to call a tool. Measured on 28 planted problems: when the investigator agent found a
flagged garage it often described it in its summary without recording it, so the adjuster saw nothing. Code now adds every finding the agent did not record."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from app import events, runner
from app.config import settings
from app.runstate import RunState, set_state
from app.services import data

CASES = json.load(open("evals/golden/cases.json"))
THEFT = next(c["claim_id"] for c in CASES if c["scenario"] == "theft_no_fir")


def extracted(**kw) -> dict:
    base = {"claim_id": "CLM-X", "policy_no": "NO-SUCH-POLICY", "garage": "AutoCare Works", "police_fir": None, "photo": None, "extraction_check": None,
            "lines": [{"name": "Front bumper", "category": "plastic", "cost": 9000}]}
    return {**base, **kw}


FIR: dict[str, bool | None] = {}


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    from app.mcp_servers import claims_ops
    monkeypatch.setattr(events, "log", lambda *a, **k: None)
    real = claims_ops.verify_police_fir

    def fir(claim_id: str) -> dict:  # the fake claims have no PDF, so read the FIR from the test's own data; real claims go to the real lookup
        if claim_id in FIR:
            v = FIR[claim_id]
            return {"claim_id": claim_id, "fir_recorded": v, "status": "not applicable" if v is None else "recorded" if v else "missing"}
        return real(claim_id)
    monkeypatch.setattr(claims_ops, "verify_police_fir", fir)


def state(ex: dict, agent_signals: list[dict] | None = None) -> RunState:
    FIR[ex["claim_id"]] = ex["police_fir"]
    s = RunState(ex["claim_id"], extracted=ex, signals=list(agent_signals or []))
    set_state(s)
    return s


def kinds(s: RunState) -> list[str]:
    return sorted(g["kind"] for g in s.signals)


PROBLEMS = dict(garage="Speedfix Motors", police_fir=False, lines=[{"name": "Front bumper", "category": "plastic", "cost": 22000}])


def test_findings_the_agent_never_recorded_are_added_by_code_and_marked_as_rules():
    s = state(extracted(**PROBLEMS))
    runner.add_rule_signals(s)
    assert kinds(s) == ["garage", "police_fir", "repair_cost"]
    assert all(g["source"] == "rules" for g in s.signals)
    assert "Speedfix Motors" in next(g for g in s.signals if g["kind"] == "garage")["detail"]


def test_a_finding_the_agent_did_record_is_not_duplicated():
    agent = [{"kind": "garage", "severity": "medium", "detail": "Speedfix Motors has 6 flagged estimates.", "source": "agent"}]
    s = state(extracted(**PROBLEMS), agent)
    runner.add_rule_signals(s)
    assert kinds(s) == ["garage", "police_fir", "repair_cost"]
    assert next(g for g in s.signals if g["kind"] == "garage")["source"] == "agent"  # the agent's own record is kept


def test_a_second_inflated_line_is_not_lost_when_the_agent_flagged_only_the_first():
    lines = [{"name": "Windshield", "category": "glass", "cost": 27000}, {"name": "Fender", "category": "metal", "cost": 21000}]
    agent = [{"kind": "repair_cost", "severity": "high", "detail": "Windshield quoted at INR 27,000 is far above the range.", "source": "agent"}]
    s = state(extracted(lines=lines), agent)
    runner.add_rule_signals(s)
    costs = [g for g in s.signals if g["kind"] == "repair_cost"]
    assert len(costs) == 2 and "Fender" in costs[1]["detail"] and costs[1]["source"] == "rules"


def test_what_the_agent_found_beyond_the_rules_is_untouched():
    judgement = {"kind": "other", "severity": "low", "detail": "The narrative contradicts the photo.", "source": "agent"}
    s = state(extracted(), [judgement])
    runner.add_rule_signals(s)
    assert s.signals == [judgement]  # a clean claim: the rules add nothing and the agent's own signal stays


def test_a_clean_claim_gets_no_signals():
    s = state(extracted())
    runner.add_rule_signals(s)
    assert s.signals == []


def test_calling_it_twice_adds_nothing_new():
    s = state(extracted(**PROBLEMS))
    runner.add_rule_signals(s)
    first = list(s.signals)
    runner.add_rule_signals(s)
    assert s.signals == first


def test_the_agents_tool_marks_its_own_signals():
    from app import tools
    s = state(extracted())
    tools.record_risk_signal("garage", "medium", "x")
    assert s.signals[0]["source"] == "agent"


# ---- through the real live path: an agent that records nothing, which is the failure measured -----------------------------------------------------

class SilentAgent:
    """Does what the investigator did in the failing runs: looks at everything, writes a summary, records no signal."""
    async def invoke_async(self, prompt):
        return SimpleNamespace(metrics=None, results={})


def test_the_live_path_delivers_the_signal_even_when_the_agent_records_nothing(monkeypatch):
    monkeypatch.setattr(settings, "collab_rounds", 0)
    from app.agents import graph
    team = SimpleNamespace(graph=SimpleNamespace(invoke_async=SilentAgent().invoke_async), adjudicator=SilentAgent(), agents={}, model_of={"adjudicator": "x"})
    monkeypatch.setattr(graph, "build_team", lambda: team)

    async def go():
        events.use_bus(events.EventBus())
        s = RunState(THEFT, extracted=data.extract_claim(THEFT))
        set_state(s)
        await runner._live(s)
        return s
    s = asyncio.run(go())
    assert "police_fir" in kinds(s), "the theft with no FIR must reach the adjuster even though the agent said nothing"
    assert s.decision is not None  # the decision still never depends on the agent
    assert all(g["source"] == "rules" for g in s.signals)
