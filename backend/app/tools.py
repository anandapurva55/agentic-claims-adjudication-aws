"""Tools the agents call. Judgement goes to the LLM, arithmetic and policy facts come from here."""
from __future__ import annotations

from strands import tool

from app import events, memory
from app.rules import adjudicate, compute_payable, load_rules
from app.runstate import state
from app.services import data, policy_search


@tool
def get_claim_packet(claim_id: str) -> dict:
    """Return the structured fields extracted from the claim packet (claim form and repair estimate).

    Args:
        claim_id: The claim identifier, for example CLM-2026001.
    """
    events.edge("bda", "guardrail", "extracted fields")
    s = state()
    return {k: v for k, v in s.extracted.items()}


@tool
def record_judgement(intoxicated: bool, commercial_use: bool, unlicensed_driver: bool, mechanical_failure: bool,
                     tyre_only: bool, theft: bool, evidence: str) -> str:
    """Record your judgement flags for this claim after reading the incident narrative.

    Mark a flag true only when the narrative clearly supports it. A negated statement such as
    "had not consumed any alcohol" means the flag is false.

    Args:
        intoxicated: Driver was under the influence of alcohol or drugs.
        commercial_use: Vehicle was being used for hire, delivery or other commercial purposes at the time.
        unlicensed_driver: Driver did not hold a valid licence or was not a permitted driver.
        mechanical_failure: Loss was a mechanical or electrical breakdown rather than an accident.
        tyre_only: Only tyres were damaged and nothing else on the vehicle.
        theft: The vehicle was stolen.
        evidence: The exact sentence or phrase from the narrative that supports your judgement.
    """
    s = state()
    s.flags = dict(intoxicated=intoxicated, commercial_use=commercial_use, unlicensed_driver=unlicensed_driver,
                   mechanical_failure=mechanical_failure, tyre_only=tyre_only, theft=theft)
    s.evidence = {"quote": evidence}
    s.facts = data.facts_from(s.extracted, s.flags)
    return "recorded"


@tool
def search_policy_wording(query: str) -> list[dict]:
    """Search the policy wording for clauses relevant to a question. Cite clause ids in your answer.

    Args:
        query: What you want to know, for example "exclusion for driving under the influence".
    """
    events.edge("policy", "kb", query[:48])
    events.node("kb", "active", query)
    hits = policy_search.search(query)
    state().citations.extend(h for h in hits if h not in state().citations)
    events.node("kb", "done", f"{len(hits)} clauses")
    return hits


@tool
def calculate_payable(claim_id: str) -> dict:
    """Compute the payable amount exactly: depreciation by part type and vehicle age, deductible, total loss rule.

    Args:
        claim_id: The claim identifier.
    """
    events.edge("policy", "calc", "compute")
    events.node("calc", "active", "depreciation and deductible")
    s = state()
    sch = data.schedule_for(s.extracted["policy_no"])
    s.calc = compute_payable(s.facts or data.facts_from(s.extracted, s.flags), sch)
    events.node("calc", "done", f"INR {s.calc['payable']:,}")
    return s.calc


@tool
def check_consistency(claim_id: str) -> dict:
    """Compare the claim form, repair estimate and policy schedule for disagreements and timing problems.

    Args:
        claim_id: The claim identifier.
    """
    events.edge("fraud", "ddb", "read schedule")
    events.node("ddb", "active", "policy schedule")
    s = state()
    sch = data.schedule_for(s.extracted["policy_no"])
    ex = s.extracted
    issues = []
    if ex["estimate_reg"] != ex["vehicle_reg"]:
        issues.append(f"Registration mismatch: form {ex['vehicle_reg']} vs estimate {ex['estimate_reg']}")
    if ex["estimate_total"] != ex["claimed_amount"]:
        issues.append(f"Amount mismatch: claimed {ex['claimed_amount']:,} vs estimate {ex['estimate_total']:,}")
    if ex["vehicle_reg"] != sch.vehicle_reg:
        issues.append("Form registration differs from the policy schedule")
    s.consistency = {"issues": issues, "policy_period": [sch.start, sch.end]}
    events.node("ddb", "done", "schedule read")
    return s.consistency


@tool
def finalize_decision(claim_id: str) -> dict:
    """Apply the policy rules to the recorded judgement flags and return the decision with its audit steps.

    Args:
        claim_id: The claim identifier.
    """
    s = state()
    sch = data.schedule_for(s.extracted["policy_no"])
    s.facts = s.facts or data.facts_from(s.extracted, s.flags)
    s.decision = adjudicate(s.facts, sch)
    rules = load_rules()
    s.citations = [{"clause": c, "source": rules[c]["source"], "text": rules[c]["quote"]} for c in s.decision.clauses if c in rules]
    return s.decision.dict()


@tool
def record_risk_signal(kind: str, severity: str, detail: str) -> str:
    """Record an advisory risk signal found while investigating. Signals are shown to the human adjuster.
    They never change the decision on their own.

    Args:
        kind: One of repair_cost, garage, repeat_claim, police_fir, other.
        severity: low, medium or high.
        detail: One sentence with the evidence, including the numbers.
    """
    if severity not in ("low", "medium", "high"):
        severity = "low"
    state().signals.append({"kind": kind, "severity": severity, "detail": detail[:300]})
    return "recorded"


@tool
def recall_lessons(situation: str) -> list[dict]:
    """Recall guidance that human adjusters recorded when they corrected the AI on earlier claims. Read only.
    Apply a lesson only when it clearly matches this claim.

    Args:
        situation: A short description of what you are trying to judge, in your own words.
    """
    hits = memory.recall(situation)
    s = state()
    for h in hits:
        if h not in s.lessons:
            s.lessons.append(h)
    return hits or [{"text": "No relevant lessons.", "score": 0}]


@tool
def post_note(sender: str, to: str, kind: str, text: str) -> str:
    """Post a note to the team's shared working memory for this claim. Use kind=question to ask another agent to
    reconsider something specific, kind=answer to reply to a question, kind=note for anything else. Ask at most one question.

    Args:
        sender: Your own agent name: intake, policy or fraud.
        to: Who should read it: intake, policy, fraud, adjudicator or team.
        kind: question, answer or note.
        text: One or two sentences. Quote the evidence.
    """
    if kind not in ("question", "answer", "note") or to not in ("intake", "policy", "fraud", "adjudicator", "team"):
        return "rejected: kind must be question, answer or note, and to must be a known agent"
    s = state()
    s.notes.append({"sender": sender, "to": to, "kind": kind, "text": text[:400]})
    memory.log_event(s.claim_id, sender, f"[{kind} to {to}] {text}")
    events.emit("note", sender=sender, to=to, kind=kind, text=text[:200])
    if to != "team" and sender != to:
        events.edge(sender, to, kind)
    return "posted"


@tool
def read_notes() -> list[dict]:
    """Read everything the team has posted to the shared working memory for this claim so far."""
    return list(state().notes) or [{"text": "No notes yet."}]
