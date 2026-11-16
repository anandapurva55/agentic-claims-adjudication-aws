"""Executes one claim and streams events. Same event contract in replay and live mode."""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from app import alerts, events, memory
from app.config import settings
from app.events import EventBus, use_bus
from app.rules import Decision, adjudicate, load_rules
from app.runstate import RunState, set_state
from app.services import data, guardrail, stores
from app.services.baseline import keyword_flags


async def _pause(speed: float, seconds: float) -> None:
    if speed > 0:
        await asyncio.sleep(seconds / speed)


def _clean(text: str) -> str:
    """Models like em dashes. This product's house style does not use them, so they are removed from any model text."""
    return text.replace(" \u2014 ", ", ").replace("\u2014", ", ").replace("\u2013", "-")


def _memo(s: RunState) -> str:
    d = s.decision
    if d is None:
        raise RuntimeError("a memo is only written once there is a decision")
    head = {"approve": "APPROVE", "deny": "DENY", "refer": "REFER TO SENIOR ADJUSTER"}[d.decision]
    lines = [f"Decision: {head}. Payable: INR {d.payable:,}." if d.payable else f"Decision: {head}.",
             "Clauses: " + ", ".join(d.clauses) + ".", ""]
    lines += [f"- {st['check']}: {st['result']}" for st in d.steps]
    if s.guardrail.get("alerts"):
        lines.append(f"- Security: {len(s.guardrail['alerts'])} sentence(s) removed by the guardrail before agents read the narrative.")
    return "\n".join(lines)


async def _ingest(s: RunState, speed: float, override: str | None = None, defences: bool = True) -> None:
    """Stage 1: intake and extraction, then guardrail on untrusted text."""
    events.node("upload", "active", s.claim_id)
    await _pause(speed, 0.5)
    events.node("upload", "done", "3 files received")
    events.edge("upload", "bda", "claim packet")
    events.node("bda", "active", "form, estimate, photo")
    s.extracted = data.extract_claim(s.claim_id)
    if override is not None:  # red team harness: attacker controlled text replaces the narrative
        s.extracted["narrative"] = override
    await _pause(speed, 1.0)
    events.log("bda", f"extracted {len(s.extracted)} fields and {len(s.extracted['lines'])} estimate lines")
    ph = s.extracted.get("photo")
    events.log("bda", f"damage photo: {', '.join(ph['parts']).replace('_', ' ') or 'no listed part'} ({ph['severity']})" if ph else "no damage photo on this claim")
    events.node("bda", "done", "fields extracted")
    events.edge("bda", "guardrail", "narrative")
    events.node("guardrail", "active", "scanning narrative")
    g = guardrail.sanitize(s.extracted["narrative"]) if defences else {"clean": s.extracted["narrative"], "alerts": [], "engine": "disabled"}
    s.guardrail = g
    s.extracted["narrative"] = g["clean"]
    await _pause(speed, 0.7)
    if g["alerts"]:
        events.node("guardrail", "alert", f"prompt attack blocked ({g['engine']})")
        events.log("guardrail", f"removed {len(g['alerts'])} sentence(s) as prompt attack")
    else:
        events.node("guardrail", "done", f"clean ({g['engine']})")
    events.edge("guardrail", "intake", "sanitised text")


async def _replay(s: RunState, speed: float) -> None:
    events.node("intake", "active", "reading narrative")
    events.edge("intake", "memory", "recall lessons")
    events.node("memory", "active", "recall lessons")
    s.lessons = memory.recall(s.extracted["narrative"])
    await _pause(speed, 0.6)
    events.node("memory", "done", f"{len(s.lessons)} lesson(s)" if s.lessons else "no lessons match")
    s.flags = keyword_flags(s.extracted["narrative"])
    s.facts = data.facts_from(s.extracted, s.flags)
    await _pause(speed, 1.0)
    on = [k for k, v in s.flags.items() if v]
    events.log("intake", "flags: " + (", ".join(on) if on else "none"))
    events.node("intake", "done", ", ".join(on) or "no exclusions flagged")
    events.edge("intake", "policy", "flags")
    events.edge("intake", "fraud", "facts")
    events.node("policy", "active", "matching clauses")
    events.node("fraud", "active", "investigating")
    sch = data.schedule_for(s.extracted["policy_no"])
    from app.rules import compute_payable
    from app.services import policy_search, signals

    phrase = {"intoxicated": "under the influence of intoxicating liquor or drugs", "commercial_use": "used otherwise than Limitations as to Use",
              "unlicensed_driver": "driven by a person other than a Driver as stated in the Driver's Clause",
              "mechanical_failure": "wear and tear mechanical or electrical breakdown", "tyre_only": "damage to tyres and tubes",
              "theft": "burglary housebreaking or theft police notice"}
    query = " ".join(phrase[k] for k in on) or "accidental external means depreciation deductible"
    events.edge("policy", "mcp_policy", "search wording")
    events.node("mcp_policy", "active", "search_policy_wording")
    await _pause(speed, 0.5)
    events.edge("mcp_policy", "kb", "query")
    events.node("kb", "active", "retrieving clauses")
    s.citations = policy_search.local_search(query)
    await _pause(speed, 0.8)
    events.node("kb", "done", f"{len(s.citations)} clauses")
    events.node("mcp_policy", "done", "clauses returned")
    events.edge("policy", "calc", "compute")
    events.node("calc", "active", "depreciation and deductible")
    s.calc = compute_payable(s.facts, sch)
    await _pause(speed, 0.7)
    events.node("calc", "done", f"INR {s.calc['payable']:,}")
    events.edge("fraud", "mcp_ops", "benchmark, FIR, garage")
    events.node("mcp_ops", "active", "benchmark_repair_cost")
    s.signals = signals.investigate(s.extracted)
    await _pause(speed, 0.9)
    events.node("mcp_ops", "done", f"{len(s.signals)} signal(s)")
    events.edge("fraud", "mcp_policy", "claim history")
    events.node("mcp_policy", "active", "get_claim_history")
    await _pause(speed, 0.5)
    events.node("mcp_policy", "done", "history read")
    for sg in s.signals:
        events.log("fraud", f"{sg['severity']} signal: {sg['kind']}")
    events.node("policy", "done", "assessment ready")
    events.node("fraud", "done", f"{len(s.signals)} signal(s)" if s.signals else "no signals")
    for src in ("policy", "fraud", "calc"):
        events.edge(src, "adjudicator", "")
    events.node("adjudicator", "active", "applying rules")
    s.decision = adjudicate(s.facts, sch)
    rules = load_rules()
    s.citations = [{"clause": c, "source": rules[c]["source"], "text": rules[c]["quote"]} for c in s.decision.clauses if c in rules]
    s.memo = _memo(s)
    await _pause(speed, 0.9)
    events.node("adjudicator", "done", s.decision.decision)


def _usage(s: RunState, result, model: str = "unknown") -> None:
    usage = getattr(getattr(result, "metrics", None), "accumulated_usage", None) or {}
    i, o = usage.get("inputTokens", 0), usage.get("outputTokens", 0)
    s.input_tokens += i
    s.output_tokens += o
    m = s.tokens_by_model.setdefault(model, {"input": 0, "output": 0})
    m["input"] += i
    m["output"] += o


async def _collaborate(s: RunState, team) -> None:
    """Bounded back and forth. An agent that doubts another's finding posts a question. The addressee reconsiders and answers.
    The number of rounds and the model call budget are both hard capped, so a debate can never run away."""
    for _ in range(settings.collab_rounds):
        pending = [n for n in s.notes if n["kind"] == "question" and not n.get("answered") and n["to"] in team.agents][:3]
        if not pending:
            return
        for q in pending:
            q["answered"] = True
            target = q["to"]
            events.edge(q["sender"], target, "question")
            events.node(target, "active", "reconsidering")
            events.log(target, f"asked by {q['sender']}: {q['text'][:120]}")
            reply = await team.agents[target].invoke_async(
                f"Claim {s.claim_id}. The {q['sender']} agent asks you: {q['text']}\n"
                f"Reconsider the evidence. If your recorded judgement should change, call record_judgement again. "
                f"Then post your answer with post_note(sender='{target}', to='{q['sender']}', kind='answer', text=...).")
            _usage(s, reply, getattr(team, "model_of", {}).get(target, "unknown"))
            events.edge(target, q["sender"], "answer")
            events.node(target, "done", "answered")


async def _naive(s: RunState) -> None:
    """Red team baseline only: a single model decides directly. See agents/naive.py."""
    from app.agents.naive import build_naive, parse
    events.node("adjudicator", "active", "naive single agent")
    res = await build_naive().invoke_async(f"Decide motor claim {s.claim_id}.")
    _usage(s, res, settings.orchestrator_model)
    text = _clean(str(res))
    decision, payable = parse(text)
    s.decision = Decision(decision, ["NAIVE"], payable, [text[:300]], [], ["Decision made by a single unguarded model."])
    s.memo = text
    events.node("adjudicator", "done", decision)


def add_document_signals(s: RunState) -> None:
    """Document findings (photo versus estimate, two readers disagreeing on a form) are facts from ingestion, so code adds them in every mode."""
    from app.services import signals
    have = {g["detail"] for g in s.signals}
    for g in signals.document_signals(s.extracted):
        if g["detail"] not in have:
            s.signals.append(g)
            events.log("fraud", f"document check: {g['detail']}")


async def _live(s: RunState) -> None:
    from app.agents.graph import build_team
    team = build_team()
    result = await team.graph.invoke_async(f"Process motor claim {s.claim_id}.")
    for name, nr in result.results.items():
        _usage(s, nr.result, team.model_of.get(name, "unknown"))
    await _collaborate(s, team)
    add_document_signals(s)
    for src in ("policy", "fraud", "calc"):
        events.edge(src, "adjudicator", "")
    events.node("adjudicator", "active", "deciding")
    final = await team.adjudicator.invoke_async(f"Finalise motor claim {s.claim_id}.")
    _usage(s, final, team.model_of["adjudicator"])
    events.node("adjudicator", "done", s.decision.decision if s.decision else "")
    s.memo = _clean(str(final))
    if s.decision is None:
        # The decision never depends on a language model remembering to call a tool.
        sch = data.schedule_for(s.extracted["policy_no"])
        if s.facts is None:
            s.decision = Decision("refer", ["INT.AGENT"], 0, ["The intake agent did not record its judgement."],
                                  [{"check": "Agents completed assessment", "result": "No: judgement flags were not recorded"}],
                                  ["Review this claim manually: the AI agents did not complete their assessment.",
                                   "Nothing was guessed. Re-run the agents or decide by hand."])
            events.node("adjudicator", "alert", "agents incomplete: referred")
        else:
            s.decision = adjudicate(s.facts, sch)
            events.log("adjudicator", "decision finalised by the rules engine")
        rules = load_rules()
        s.citations = [{"clause": c, "source": rules[c]["source"], "text": rules[c]["quote"]} for c in s.decision.clauses if c in rules]
        if not s.memo.strip():
            s.memo = _memo(s)


async def run_claim(claim_id: str, mode: str | None = None, speed: float | None = None, narrative_override: str | None = None,
                    defences: bool = True, variant: str = "hardened") -> AsyncIterator[dict]:
    mode = mode or settings.mode
    speed = settings.replay_pace if speed is None else speed
    bus = EventBus()
    use_bus(bus)
    s = RunState(claim_id, variant=variant)
    set_state(s)
    t0 = time.perf_counter()

    async def work() -> None:
        try:
            events.emit("start", claim_id=claim_id, mode=mode)
            await _ingest(s, speed, narrative_override, defences)
            if variant == "naive":
                await _naive(s)
            else:
                await (_replay(s, speed) if mode == "replay" else _live(s))
            events.edge("adjudicator", "ddb", "audit record")
            if s.decision is None:  # every path sets one: a missing decision is a bug, never an approval
                raise RuntimeError("the run finished without a decision")
            stores.audit(claim_id, "ai", "decision", {"decision": s.decision.decision, "payable": s.decision.payable,
                                                      "clauses": s.decision.clauses, "mode": mode})
            events.edge("adjudicator", "human", "for review")
            events.node("human", "waiting", "awaiting adjuster")
            ms = round((time.perf_counter() - t0) * 1000)
            cost = round(sum(c["cost_usd"] for c in s.calls), 6)
            run_row = {"run_id": s.run_id, "claim_id": claim_id, "mode": mode, "latency_ms": ms, "model_calls": s.model_calls,
                       "input_tokens": s.input_tokens, "output_tokens": s.output_tokens, "cost_usd": cost, "variant": variant,
                       "decision": s.decision.decision, "ok": True, "day": time.strftime("%Y-%m-%d")}
            fired = alerts.evaluate(run_row)
            stores.record_metric(run_row)
            alerts.publish(run_row)
            events.emit("result", decision=s.decision.dict(), calc=s.calc, memo=s.memo, citations=s.citations,
                        flags=s.flags, guardrail={"alerts": s.guardrail.get("alerts", []), "engine": s.guardrail.get("engine")},
                        consistency=s.consistency, signals=s.signals, lessons=s.lessons, notes=s.notes, latency_ms=ms, mode=mode,
                        input_tokens=s.input_tokens, output_tokens=s.output_tokens, model_calls=s.model_calls,
                        tokens_by_model=s.tokens_by_model, cost_usd=cost, alerts=fired, calls=s.calls)
        except Exception as exc:  # surfaced to the UI and the metrics, never swallowed
            failed = {"run_id": s.run_id, "claim_id": claim_id, "mode": mode, "latency_ms": round((time.perf_counter() - t0) * 1000),
                      "ok": False, "error": str(exc)[:200], "cost_usd": round(sum(c["cost_usd"] for c in s.calls), 6), "variant": variant,
                      "day": time.strftime("%Y-%m-%d")}
            alerts.evaluate(failed)
            stores.record_metric(failed)
            alerts.publish(failed)
            events.emit("error", message=str(exc)[:300])
        finally:
            bus.close()

    task = asyncio.create_task(work())
    try:
        while (ev := await bus.queue.get()) is not None:
            yield ev
    finally:
        await task
