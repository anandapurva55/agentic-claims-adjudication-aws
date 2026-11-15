"""FastAPI service. Streams agent graph events to the UI over server-sent events."""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app import memory
from app.config import settings
from app.runner import run_claim
from app.services import data, guardrail, stores
from app.topology import topology

app = FastAPI(title="Claims Adjudication API", version="1.0.0")


@app.on_event("startup")
def _restore_state() -> None:
    stores.hydrate()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_live_lock = asyncio.Semaphore(1)  # tool state is per process, so live runs are serialised


class Review(BaseModel):
    action: str  # accept | override | escalate
    final_decision: str | None = None  # required for override: approve | deny | refer
    note: str = ""
    reviewer: str = "adjuster"
    role: str = "adjuster"  # adjuster | senior


def _claim_summary(cid: str) -> dict:
    ex = data.extract_claim(cid)
    pol = data.policies()[ex["policy_no"]]
    st = stores.stage_for(cid)
    return {"claim_id": cid, "holder": pol["holder"], "policy_no": ex["policy_no"], "vehicle": f"{pol['make']} {pol['model']}",
            "vehicle_reg": ex["vehicle_reg"], "incident_date": ex["incident_date"], "claimed_amount": ex["claimed_amount"],
            "stage": st["stage"], "ai": st["ai"], "review": st["review"]}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": settings.mode, "region": settings.region,
            "models": {"orchestrator": settings.orchestrator_model, "fast": settings.fast_model}}


@app.get("/api/topology")
def get_topology() -> dict:
    return topology()


@app.get("/api/claims")
def claims() -> list[dict]:
    return [_claim_summary(c) for c in data.list_claim_ids()]


@app.get("/api/claims/{claim_id}")
def claim(claim_id: str) -> dict:
    if claim_id not in data.list_claim_ids():
        raise HTTPException(404, "unknown claim")
    ex = data.extract_claim(claim_id)
    return {**_claim_summary(claim_id), "extracted": ex, "audit": stores.audit_for(claim_id)}


_FILES = {"damage_photo.jpg", "claim_form.pdf", "repair_estimate.pdf"}


@app.get("/api/claims/{claim_id}/files/{name}")
def claim_file(claim_id: str, name: str) -> FileResponse:
    if claim_id not in data.list_claim_ids() or name not in _FILES:  # whitelist: no path traversal
        raise HTTPException(404, "not found")
    return FileResponse(data.claim_dir(claim_id) / name)


@app.get("/api/claims/{claim_id}/run")
async def run(claim_id: str, mode: str = Query(default=None)) -> StreamingResponse:
    if claim_id not in data.list_claim_ids():
        raise HTTPException(404, "unknown claim")
    mode = mode or settings.mode

    async def stream():
        async with _live_lock:
            async for ev in run_claim(claim_id, mode):
                yield f"data: {json.dumps(ev)}\n\n"
            yield "event: end\ndata: {}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/claims/{claim_id}/review")
def review(claim_id: str, body: Review) -> dict:
    """Human in the loop gate. Nothing is settled until a person decides here."""
    if claim_id not in data.list_claim_ids():
        raise HTTPException(404, "unknown claim")
    if body.action not in ("accept", "override", "escalate"):
        raise HTTPException(422, "action must be accept, override or escalate")
    if body.role not in ("adjuster", "senior"):
        raise HTTPException(422, "role must be adjuster or senior")
    st = stores.stage_for(claim_id)
    if st["stage"] == "new" or not st["ai"]:
        raise HTTPException(409, "run the agents first: there is no AI recommendation to review")
    if st["stage"] == "reviewed":
        raise HTTPException(409, "this claim already has a human decision")
    ai = st["ai"]
    if body.action == "override":
        if body.final_decision not in ("approve", "deny", "refer"):
            raise HTTPException(422, "override requires final_decision: approve, deny or refer")
        if len(body.note.strip()) < 10:
            raise HTTPException(422, "an override needs a reason of at least 10 characters")
        # The reason becomes a long term lesson, so it is scanned like any untrusted text before it is stored.
        if guardrail.sanitize(body.note)["alerts"]:
            raise HTTPException(422, "the reason looks like a prompt attack and was not saved: rewrite it as plain guidance")
    # Four eyes: payouts above the authority limit need a senior adjuster.
    over_limit = "INT.AUTH" in ai["clauses"]
    approving = body.action == "accept" and ai["decision"] in ("approve", "refer") or (body.action == "override" and body.final_decision == "approve")
    if over_limit and approving and body.role != "senior":
        raise HTTPException(403, "this payable is above the adjuster authority limit: a senior adjuster must approve, or you can escalate")
    final = {"accept": ai["decision"], "override": body.final_decision, "escalate": "escalated"}[body.action]
    detail = {**body.model_dump(), "ai_decision": ai["decision"], "ai_payable": ai["payable"], "ai_clauses": ai["clauses"], "final": final}
    row = stores.audit(claim_id, f"{body.role}:{body.reviewer}", "human_review", detail)
    lesson_stored = False
    if body.action == "override":
        stores.add_override_candidate({"claim_id": claim_id, "ai_decision": ai["decision"], "human_decision": final, "reason": body.note,
                                      "ts": row["ts"]})
        # Human decisions are the only way into long term memory.
        lesson_stored = memory.store_lesson(
            f"A human adjuster changed the AI's decision from {ai['decision']} to {final}. Their reason: {body.note.strip()}",
            {"claim_id": claim_id, "reviewer": body.reviewer, "role": body.role})
    outcome = {"approve": f"Settlement of INR {ai['payable']:,} released for payment." if final == "approve" and body.action == "accept"
               else "Approved by reviewer. Payable to be confirmed by the senior adjuster's calculation.",
               "deny": "Denial confirmed. Letter queued for the policy holder.",
               "refer": "Referred to a senior adjuster.", "escalated": "Escalated to a senior adjuster."}[final]
    stores.audit(claim_id, "system", "outcome", {"final": final, "message": outcome})
    return {**row, "final": final, "outcome": outcome, "lesson_stored": lesson_stored}


@app.get("/api/review-stats")
def review_stats() -> dict:
    return stores.review_stats()


def _pct(values: list[float], p: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(len(v) * p))] if v else 0


@app.get("/api/metrics")
def get_metrics() -> dict:
    """Everything the observability dashboard shows: speed, cost, failures, where the money goes, alerts."""
    rows = stores.metrics()
    ok = [r for r in rows if r.get("ok")]
    calls = stores.calls()
    lat = [r["latency_ms"] for r in ok]
    costs = [r.get("cost_usd", 0) for r in ok if r.get("cost_usd")]
    by_day: dict[str, dict] = {}
    for r in rows:
        d = by_day.setdefault(r["day"], {"day": r["day"], "runs": 0, "failures": 0, "tokens": 0, "cost_usd": 0.0})
        d["runs"] += 1
        d["failures"] += 0 if r.get("ok") else 1
        d["tokens"] += r.get("input_tokens", 0) + r.get("output_tokens", 0)
        d["cost_usd"] = round(d["cost_usd"] + r.get("cost_usd", 0), 6)
    by_agent: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    for c in calls:
        for key, bucket in ((c["agent"], by_agent), (c["model"], by_model)):
            b = bucket.setdefault(key, {"name": key, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cost_usd": 0.0, "latencies": [], "errors": 0})
            b["calls"] += 1
            b["input_tokens"] += c["input_tokens"]
            b["output_tokens"] += c["output_tokens"]
            b["cache_read"] += c.get("cache_read", 0)
            b["cost_usd"] += c["cost_usd"]
            b["latencies"].append(c["latency_ms"])
            b["errors"] += 1 if c.get("error") else 0
    total_cost = sum(c["cost_usd"] for c in calls)

    def finish(bucket: dict) -> list[dict]:
        out = []
        for b in bucket.values():
            lats = b.pop("latencies")
            out.append({**b, "cost_usd": round(b["cost_usd"], 5), "share": round(b["cost_usd"] / total_cost, 3) if total_cost else 0,
                        "avg_latency_ms": round(sum(lats) / len(lats)), "p95_latency_ms": round(_pct(lats, 0.95))})
        return sorted(out, key=lambda x: -x["cost_usd"])

    today = time.strftime("%Y-%m-%d")
    return {"runs": len(rows), "failure_rate": round(1 - len(ok) / len(rows), 3) if rows else 0,
            "latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "max": max(lat) if lat else 0},
            "cost": {"total_usd": round(total_cost, 4), "per_claim_avg_usd": round(sum(costs) / len(costs), 4) if costs else 0,
                     "per_claim_p95_usd": round(_pct(costs, 0.95), 4), "today_usd": round(by_day.get(today, {}).get("cost_usd", 0), 4),
                     "daily_budget_usd": settings.daily_budget_usd},
            "decisions": dict(Counter(r["decision"] for r in ok)), "by_day": sorted(by_day.values(), key=lambda x: x["day"]),
            "by_agent": finish(by_agent), "by_model": finish(by_model),
            "slowest_calls": sorted(calls, key=lambda c: -c["latency_ms"])[:5],
            "alerts": stores.alerts()[-10:][::-1], "recent": rows[-20:]}


_REDTEAM = Path(__file__).resolve().parents[3] / "redteam"


class Scan(BaseModel):
    text: str


@app.get("/api/security/attacks")
def security_attacks() -> list[dict]:
    return json.loads((_REDTEAM / "attacks.json").read_text())


@app.post("/api/security/scan")
def security_scan(body: Scan) -> dict:
    """Attack lab: run any text through the same guardrail the pipeline uses and show what was removed."""
    if len(body.text) > 4000:
        raise HTTPException(413, "text too long")
    return guardrail.sanitize(body.text)


@app.get("/api/security/report")
def security_report() -> dict:
    f = _REDTEAM / "reports" / "latest.json"
    if not f.exists():
        raise HTTPException(404, "no red team report yet: run python redteam/run.py")
    r = json.loads(f.read_text())
    r.pop("rows", None)
    return r
