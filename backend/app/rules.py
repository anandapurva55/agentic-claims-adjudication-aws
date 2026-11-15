"""Deterministic adjudication engine.

The LLM agents decide the *judgement* questions (was the driver intoxicated, is the
use commercial). This module does everything that must be exactly right: depreciation,
deductible, constructive total loss, authority limits. It is also the baseline the
agents are evaluated against.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from app.config import settings

AUTHORITY_LIMIT = 200_000
LATE_NOTICE_DAYS = 15
AGE_DEPR = [(0.5, 0), (1, 5), (2, 10), (3, 15), (4, 25), (5, 35), (10, 40), (99, 50)]
CAT_DEPR = {"plastic": 50, "rubber": 50, "battery": 50, "fibreglass": 30, "glass": 0}


def load_rules() -> dict:
    return json.loads((Path(settings.data_dir) / "rules.json").read_text())


@dataclass
class Line:
    name: str
    category: str
    cost: int


@dataclass
class Facts:
    """Everything the engine needs. Produced by extraction plus the intake agent."""
    claim_id: str
    policy_no: str
    vehicle_reg: str
    estimate_reg: str
    incident_date: str
    report_date: str
    claimed_amount: int
    estimate_total: int
    lines: list[Line]
    labour: int
    salvage: int = 0
    police_fir: bool | None = None
    # judgement flags set by the intake agent (or keyword baseline)
    intoxicated: bool = False
    commercial_use: bool = False
    unlicensed_driver: bool = False
    mechanical_failure: bool = False
    tyre_only: bool = False
    theft: bool = False


@dataclass
class Schedule:
    policy_no: str
    idv: int
    deductible: int
    reg_year: int
    start: str
    end: str
    vehicle_reg: str


@dataclass
class Decision:
    decision: str
    clauses: list[str]
    payable: int
    reasons: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def dict(self) -> dict:
        return asdict(self)


def dep_rate(category: str, age_years: float) -> int:
    if category in CAT_DEPR:
        return CAT_DEPR[category]
    return next(p for lim, p in AGE_DEPR if age_years <= lim)


def vehicle_age(reg_year: int, incident: str) -> float:
    return (date.fromisoformat(incident) - date(reg_year, 6, 1)).days / 365.0


def compute_payable(facts: Facts, sch: Schedule) -> dict:
    """Pure arithmetic. Returns a breakdown so the memo can show its working."""
    age = vehicle_age(sch.reg_year, facts.incident_date)
    gross = sum(ln.cost for ln in facts.lines) + facts.labour
    rows = []
    net_parts = 0.0
    for ln in facts.lines:
        d = dep_rate(ln.category, age)
        net = ln.cost * (100 - d) / 100
        net_parts += net
        rows.append({"item": ln.name, "category": ln.category, "cost": ln.cost, "depreciation_pct": d, "net": round(net)})
    if facts.theft or gross > 0.75 * sch.idv:
        basis = "theft" if facts.theft else "constructive_total_loss"
        payable = sch.idv - facts.salvage - sch.deductible
    else:
        basis = "partial_loss"
        payable = round(net_parts + facts.labour - sch.deductible)
    return {"basis": basis, "gross_repair": gross, "idv": sch.idv, "deductible": sch.deductible,
            "vehicle_age_years": round(age, 2), "lines": rows, "labour": facts.labour,
            "salvage": facts.salvage, "payable": max(payable, 0), "raw_payable": payable}


def _adjudicate(f: Facts, sch: Schedule) -> Decision:
    """Apply the rules in precedence order. Each step is recorded for the audit trail."""
    steps: list[dict] = []

    def step(name: str, result: str) -> None:
        steps.append({"check": name, "result": result})

    if not (sch.start <= f.incident_date <= sch.end):
        step("Loss within period of insurance", f"No: {f.incident_date} is outside {sch.start} to {sch.end}")
        return Decision("deny", ["PERIOD"], 0, ["Loss occurred outside the policy period."], steps)
    step("Loss within period of insurance", "Yes")

    for flag, clause, text in [
        (f.intoxicated, "SEC1.EXCL.1c", "Driver was under the influence of intoxicating liquor or drugs."),
        (f.commercial_use, "SEC5.3a", "Vehicle was used otherwise than per the Limitations as to Use."),
        (f.unlicensed_driver, "SEC5.3b", "Vehicle was driven by a person other than a driver permitted by the policy."),
        (f.mechanical_failure, "SEC1.EXCL.1a", "Mechanical breakdown is excluded as wear and tear or breakdown."),
        (f.tyre_only, "SEC1.EXCL.1b", "Tyre damage without other vehicle damage is not covered."),
    ]:
        step(f"Exclusion {clause}", "Applies" if flag else "Does not apply")
        if flag:
            return Decision("deny", [clause], 0, [text], steps)

    if f.theft and not f.police_fir:
        step("Police notice for theft", "No FIR recorded")
        return Decision("refer", ["SEC7.1"], 0, ["Theft claim has no police FIR. Refer for investigation."], steps)

    if f.estimate_reg != f.vehicle_reg or f.estimate_total != f.claimed_amount:
        why = []
        if f.estimate_reg != f.vehicle_reg:
            why.append(f"registration differs ({f.vehicle_reg} on the form, {f.estimate_reg} on the estimate)")
        if f.estimate_total != f.claimed_amount:
            why.append(f"amounts differ (INR {f.claimed_amount:,} claimed, INR {f.estimate_total:,} on the estimate)")
        step("Documents consistent", "No: " + "; ".join(why))
        return Decision("refer", ["INT.CONSIST"], 0, ["Documents disagree: " + "; ".join(why)], steps)
    step("Documents consistent", "Yes")

    gap = (date.fromisoformat(f.report_date) - date.fromisoformat(f.incident_date)).days
    if gap > LATE_NOTICE_DAYS:
        step("Notice given promptly", f"No: reported {gap} days after the incident")
        return Decision("refer", ["INT.LATE", "SEC7.1"], 0, [f"Reported {gap} days after the incident."], steps)
    step("Notice given promptly", f"Yes ({gap} days)")

    calc = compute_payable(f, sch)
    cites = {"theft": ["SEC7.1", "SEC7.3a", "SEC6.DEDUCT"], "constructive_total_loss": ["SEC1.CTL", "SEC7.3a", "SEC6.DEDUCT"],
             "partial_loss": ["SEC1.COVER", "SEC1.DEPR", "SEC6.DEDUCT"]}[calc["basis"]]
    step("Payable amount", f"INR {calc['raw_payable']:,} ({calc['basis']})")
    if calc["raw_payable"] <= 0:
        return Decision("deny", ["SEC6.DEDUCT"], 0, ["Claim amount does not exceed the deductible."], steps)
    if calc["payable"] > AUTHORITY_LIMIT:
        step("Within adjuster authority", f"No: above INR {AUTHORITY_LIMIT:,}")
        return Decision("refer", ["INT.AUTH"] + cites, calc["payable"], ["Payable exceeds the approval authority limit."], steps)
    step("Within adjuster authority", "Yes")
    return Decision("approve", cites, calc["payable"], ["All checks passed."], steps)


def next_steps(decision: str, clauses: list[str], payable: int, reasons: list[str]) -> list[str]:
    """Every outcome comes with a concrete next action, so a referral is never a dead end."""
    if decision == "approve":
        return [f"Release payment of INR {payable:,} after sign-off.", "Notify the policy holder of the settlement."]
    if decision == "deny":
        return [f"Send the denial letter citing {', '.join(clauses)}.", "Tell the policy holder how to appeal.",
                "If you disagree with the AI, override with a written reason."]
    if "INT.CONSIST" in clauses:
        return ["Ask the garage and the policy holder to resubmit documents that agree on registration and total.",
                "Do not settle until the documents match.", reasons[0] if reasons else ""]
    if "INT.LATE" in clauses:
        return ["Contact the policy holder for the reason for the delay and any supporting evidence.",
                "Investigate whether the delay prejudiced the insurer, then decide."]
    if "SEC7.1" in clauses and "INT.AUTH" not in clauses and payable == 0:
        return ["Request a copy of the police FIR from the policy holder.", "Theft cannot be processed without police notice."]
    if "INT.AUTH" in clauses:
        return [f"Route to a senior adjuster: payable INR {payable:,} is above the INR {AUTHORITY_LIMIT:,} authority limit.",
                "A senior adjuster can approve, or send it back with questions."]
    return ["Escalate to a senior adjuster for a manual decision."]


def adjudicate(f: Facts, sch: Schedule) -> Decision:
    d = _adjudicate(f, sch)
    d.next_steps = [n for n in next_steps(d.decision, d.clauses, d.payable, d.reasons) if n]
    return d
