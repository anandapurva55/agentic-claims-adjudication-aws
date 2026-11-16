"""FastAPI service. Streams agent graph events to the UI over server-sent events."""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import auth, memory
from app.config import settings
from app.observability import RequestLogMiddleware, configure_logging
from app.runner import run_claim
from app.services import data, guardrail, stores
from app.topology import topology

# Every route needs a signed-in caller except the health check (see app/auth.py).
app = FastAPI(title="Claims Adjudication API", version="1.0.0", dependencies=[Depends(auth.authenticate)])


@app.on_event("startup")
def _restore_state() -> None:
    configure_logging()
    auth.check_startup()
    stores.hydrate()


# In AWS the site and the API share one CloudFront domain, so browsers never make a cross-origin call. Only the local dev server is listed by default.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
app.add_middleware(RequestLogMiddleware)  # added last, so it is outermost and sees every request, including refused ones
_live_lock = asyncio.Semaphore(1)  # tool state is per process, so runs are serialised
_queue: list[object] = []  # requests waiting for the lock, oldest first


class Review(BaseModel):
    """A reviewer's decision. Every field has a fixed set of values or a length limit, so a request cannot store arbitrary amounts of text in the audit log.
    Who the reviewer is and which role they hold come from the sign-in token, never from this body."""
    run_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")  # the run the reviewer was looking at
    action: Literal["accept", "override", "escalate"]
    final_decision: Literal["approve", "deny", "refer"] | None = None  # required for override
    note: str = Field(default="", max_length=1000)


def _claim_summary(cid: str, st: dict | None = None) -> dict:
    ex = data.extract_claim(cid)
    pol = data.policies()[ex["policy_no"]]
    st = st or stores.stage_for(cid)
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
    stages = stores.stages()  # one read of the audit log for the whole list
    return [_claim_summary(c, stages.get(c, {"stage": "new", "ai": None, "review": None})) for c in data.list_claim_ids()]


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


def _check_spend() -> None:
    """The daily spend limit. Live runs stop once today's model spend reaches the limit. Viewing and reviewing cost nothing and keep working. A run
    that is already going is never cut off, so the day can overshoot by at most one run per task."""
    try:
        spent = stores.spend_today()
    except Exception as exc:  # cannot verify the spend, so refuse rather than risk it
        raise HTTPException(503, "live runs are paused because today's spend could not be checked") from exc
    if spent >= settings.daily_budget_usd:
        raise HTTPException(429, f"the daily spend limit of ${settings.daily_budget_usd:.2f} has been reached (${spent:.2f} spent today): "
                                 "live runs resume tomorrow, viewing and reviewing still work", headers={"Retry-After": "3600"})


def _abandon(waiting: asyncio.Future[bool]) -> None:
    """A request stopped waiting for its turn. A wait that is still pending is cancelled, so it no longer holds a place in the lock's line. A wait that was granted at
    that same moment is handed back: nobody will run, so nobody would ever release it and the lock would stay held until the task restarted."""
    waiting.cancel()
    waiting.add_done_callback(lambda w: _live_lock.release() if not w.cancelled() and w.exception() is None else None)


@app.post("/api/claims/{claim_id}/run")  # POST: a run spends money and writes the audit log, so it is not something a link or an image tag can trigger
async def run(claim_id: str, mode: Literal["replay", "live"] | None = Query(default=None)) -> StreamingResponse:
    if claim_id not in data.list_claim_ids():
        raise HTTPException(404, "unknown claim")
    chosen = mode or settings.mode
    if chosen != settings.mode:
        # A deployment runs in one mode. Letting a caller start a replay run in a live deployment would let anyone write the "AI recommendation" that a person then
        # approves, and the replay baseline is the rule-of-thumb system this product exists to beat.
        raise HTTPException(409, f"this deployment runs in {settings.mode} mode, so a {chosen} run is not allowed")
    if chosen == "live":
        _check_spend()  # refuse before any streaming starts, so the caller gets a real status code
    if _live_lock.locked() and len(_queue) >= settings.max_queue:
        raise HTTPException(503, f"the agents are busy: {len(_queue)} runs are already waiting, so try again in a minute", headers={"Retry-After": "30"})

    async def stream():
        me = object()
        waiting: asyncio.Future[bool] | None = None
        if _live_lock.locked():
            _queue.append(me)
            # One acquire per waiter, made before anything is sent, so the lock's own line is the order the requests arrived in. Waiting again after a keepalive
            # must never issue a new acquire: that would send the waiter to the back of the line.
            waiting = asyncio.ensure_future(_live_lock.acquire())
        else:
            await _live_lock.acquire()  # free: taken at once, with no point where another request could slip in
        if waiting is not None:
            try:
                yield f"event: queued\ndata: {json.dumps({'position': _queue.index(me) + 1})}\n\n"
                while True:  # wait for the turn, and say so at every interval: silence for 60 seconds would be a 504 at CloudFront
                    try:
                        await asyncio.wait_for(asyncio.shield(waiting), timeout=settings.queue_keepalive_s)  # the shield keeps a timeout from cancelling the wait
                        break
                    except TimeoutError:
                        yield f"event: queued\ndata: {json.dumps({'position': _queue.index(me) + 1})}\n\n"
            except BaseException:  # the client went away (or the request was cancelled) while waiting
                _abandon(waiting)
                raise
            finally:
                if me in _queue:
                    _queue.remove(me)
        try:
            if chosen == "live":  # runs queued behind another one are checked again once it is their turn
                try:
                    _check_spend()
                except HTTPException as exc:
                    yield f"data: {json.dumps({'type': 'error', 'message': exc.detail})}\n\n"
                    yield "event: end\ndata: {}\n\n"
                    return
            async for ev in run_claim(claim_id, chosen):
                yield f"data: {json.dumps(ev)}\n\n"
            yield "event: end\ndata: {}\n\n"
        finally:
            _live_lock.release()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/claims/{claim_id}/review")
def review(claim_id: str, body: Review, who: auth.Identity = Depends(auth.authenticate)) -> dict:
    """Human in the loop gate. Nothing is settled until a person decides here."""
    if who is None:  # unreachable: only the health check is open
        raise HTTPException(401, "sign in to use this API")
    if claim_id not in data.list_claim_ids():
        raise HTTPException(404, "unknown claim")
    st = stores.stage_for(claim_id)
    if st["stage"] == "new" or not st["ai"]:
        raise HTTPException(409, "run the agents first: there is no AI recommendation to review")
    if st["stage"] == "reviewed":
        raise HTTPException(409, "this claim already has a human decision")
    ai = st["ai"]
    if ai.get("mode") != settings.mode:  # an older replay recommendation in a live deployment can no longer be approved
        raise HTTPException(409, f"this recommendation came from a {ai.get('mode', 'unknown')} run, and this deployment runs in {settings.mode} mode: run the agents again")
    if ai.get("run_id") != body.run_id:  # "accept" means accept what the reviewer looked at, not whatever is latest when the server reads it
        raise HTTPException(409, "the recommendation changed since you looked at it (someone ran the agents again): reload the claim and review the new result")
    if body.action == "override":
        if body.final_decision is None:
            raise HTTPException(422, "override requires final_decision: approve, deny or refer")
        if len(body.note.strip()) < 10:
            raise HTTPException(422, "an override needs a reason of at least 10 characters")
        # The reason becomes a long term lesson, so it is scanned like any untrusted text before it is stored.
        if guardrail.sanitize(body.note)["alerts"]:
            raise HTTPException(422, "the reason looks like a prompt attack and was not saved: rewrite it as plain guidance")
    # Four eyes: payouts above the authority limit need a senior adjuster.
    over_limit = "INT.AUTH" in ai["clauses"]
    approving = body.action == "accept" and ai["decision"] in ("approve", "refer") or (body.action == "override" and body.final_decision == "approve")
    if over_limit and approving and who.role != "senior":
        raise HTTPException(403, "this payable is above the adjuster authority limit: a senior adjuster must approve, or you can escalate")
    final = {"accept": ai["decision"], "override": body.final_decision, "escalate": "escalated"}[body.action]
    detail = {**body.model_dump(), "reviewer": who.username, "role": who.role, "ai_decision": ai["decision"], "ai_payable": ai["payable"], "ai_clauses": ai["clauses"], "final": final}
    try:  # the database decides a race: exactly one reviewer gets through, before any side effect below happens
        row = stores.audit(claim_id, f"{who.role}:{who.username}", "human_review", detail)
    except stores.AlreadyReviewed:
        raise HTTPException(409, "this claim already has a human decision") from None
    lesson_stored = False
    if body.action == "override":
        stores.add_override_candidate({"claim_id": claim_id, "ai_decision": ai["decision"], "human_decision": final, "reason": body.note,
                                      "ts": row["ts"]})
        # Human decisions are the only way into long term memory.
        lesson_stored = memory.store_lesson(
            f"A human adjuster changed the AI's decision from {ai['decision']} to {final}. Their reason: {body.note.strip()}",
            {"claim_id": claim_id, "reviewer": who.username, "role": who.role})
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
    text: str = Field(max_length=4000)


@app.get("/api/security/attacks")
def security_attacks() -> list[dict]:
    return json.loads((_REDTEAM / "attacks.json").read_text())


@app.post("/api/security/scan")
def security_scan(body: Scan) -> dict:
    """Attack lab: run any text through the same guardrail the pipeline uses and show what was removed."""
    return guardrail.sanitize(body.text)


@app.get("/api/security/report")
def security_report() -> dict:
    f = _REDTEAM / "reports" / "latest.json"
    if not f.exists():
        raise HTTPException(404, "no red team report yet: run python redteam/run.py")
    r = json.loads(f.read_text())
    r.pop("rows", None)
    return r
