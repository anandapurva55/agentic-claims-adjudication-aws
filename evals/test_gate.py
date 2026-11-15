"""The gate itself is tested: a good build passes and a deliberately broken one fails."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import gate  # noqa: E402
import run_eval  # noqa: E402

RULES = json.loads((Path(__file__).parent / "thresholds.json").read_text())["replay"]


def test_good_build_passes_the_gate():
    report = asyncio.run(run_eval.evaluate("replay"))
    assert gate.check(report["metrics"], RULES) == []


def test_broken_engine_fails_the_gate(monkeypatch):
    """Simulate a bad change: the deductible is no longer subtracted. The gate must catch it."""
    from app import rules

    original = rules.compute_payable

    def broken(facts, sch):
        sch = rules.Schedule(sch.policy_no, sch.idv, 0, sch.reg_year, sch.start, sch.end, sch.vehicle_reg)
        return original(facts, sch)

    monkeypatch.setattr(rules, "compute_payable", broken)
    report = asyncio.run(run_eval.evaluate("replay"))
    failures = gate.check(report["metrics"], RULES)
    assert failures, "a build that drops the deductible must fail the quality gate"
    assert any("payable_exact" in f for f in failures)


def test_gate_flags_unsafe_approvals_in_live_rules():
    live = json.loads((Path(__file__).parent / "thresholds.json").read_text())["live"]
    metrics = {"decision_accuracy": 0.99, "payable_exact": 1.0, "unsafe_approvals": 1, "injection_handled": 1.0, "errors": 0}
    assert gate.check(metrics, live) == ["unsafe_approvals = 1 is above the maximum 0"]
