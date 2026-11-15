"""Audit log, human review decisions and run metrics. Local JSONL in dev, DynamoDB in AWS."""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from pathlib import Path

from app.config import settings


def _path(name: str) -> Path:
    p = Path(settings.runtime_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / name


def _append(name: str, row: dict) -> None:
    with _path(name).open("a") as f:
        f.write(json.dumps(row) + "\n")


def _read(name: str) -> list[dict]:
    p = _path(name)
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []


def audit(claim_id: str, actor: str, action: str, detail: dict) -> dict:
    row = {"claim_id": claim_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "actor": actor, "action": action, "detail": detail}
    _append("audit.jsonl", row)
    _put(settings.audit_table, json.loads(json.dumps({**row, "ts": f"{row['ts']}#{time.time_ns()}"}), parse_float=Decimal))
    return row


def audit_for(claim_id: str) -> list[dict]:
    return [r for r in _read("audit.jsonl") if r["claim_id"] == claim_id]


def record_metric(row: dict) -> None:
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "day": time.strftime("%Y-%m-%d"), **row}
    _append("metrics.jsonl", row)
    _fan_out("run", row, f"run-{row.get('run_id', row['ts'])}")


def metrics() -> list[dict]:
    return _read("metrics.jsonl")


def reviews() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in _read("audit.jsonl"):
        if r["action"] == "human_review":
            out[r["claim_id"]] = r
    return out


def latest(claim_id: str, action: str) -> dict | None:
    rows = [r for r in audit_for(claim_id) if r["action"] == action]
    return rows[-1] if rows else None


def stage_for(claim_id: str) -> dict:
    """Lifecycle: new -> ai_recommended -> reviewed. A human review is the only way out of ai_recommended."""
    ai, human = latest(claim_id, "decision"), latest(claim_id, "human_review")
    if human and (not ai or human["ts"] >= ai["ts"]):
        return {"stage": "reviewed", "ai": ai["detail"] if ai else None, "review": human["detail"]}
    if ai:
        return {"stage": "ai_recommended", "ai": ai["detail"], "review": None}
    return {"stage": "new", "ai": None, "review": None}


def review_stats() -> dict:
    rows = [r["detail"] for r in reviews().values()]
    accepted = sum(r["action"] == "accept" for r in rows)
    overridden = sum(r["action"] == "override" for r in rows)
    escalated = sum(r["action"] == "escalate" for r in rows)
    decided = accepted + overridden
    return {"reviewed": len(rows), "accepted": accepted, "overridden": overridden, "escalated": escalated,
            "agreement_rate": round(accepted / decided, 3) if decided else None,
            "override_candidates": len(_read("override_candidates.jsonl"))}


def add_override_candidate(row: dict) -> None:
    """An override means the AI and a human disagreed. Each one is a candidate golden case for the next eval run."""
    _append("override_candidates.jsonl", row)


log = logging.getLogger("adjudication.telemetry")


def _stamp(row: dict) -> dict:
    return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "day": time.strftime("%Y-%m-%d"), "mode": settings.mode, **row}


def _put(table: str, item: dict) -> None:
    """Durable copy in DynamoDB. A container restart wipes local files, and the audit log must survive that."""
    if not table:
        return
    try:
        import boto3
        boto3.resource("dynamodb", region_name=settings.region).Table(table).put_item(Item=item)
    except Exception as exc:
        log.warning("dynamodb write failed for %s: %s", table, exc)


def _scan(table: str) -> list[dict]:
    import boto3
    t, items, kw = boto3.resource("dynamodb", region_name=settings.region).Table(table), [], {}
    while True:
        r = t.scan(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            return json.loads(json.dumps(items, default=lambda d: int(d) if d == int(d) else float(d)))
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def hydrate() -> None:
    """On start, rebuild the local files from DynamoDB when they are missing, so a new task sees the audit log and metrics of the old one."""
    try:
        if settings.audit_table and not _path("audit.jsonl").exists():
            rows = sorted(_scan(settings.audit_table), key=lambda r: r["ts"])
            for r in rows:
                r["ts"] = r["ts"].split("#")[0]
                _append("audit.jsonl", r)
        if settings.metrics_table and not _path("metrics.jsonl").exists():
            files = {"run": "metrics.jsonl", "call": "calls.jsonl", "alert": "alerts.jsonl"}
            for r in sorted(_scan(settings.metrics_table), key=lambda r: r.get("ts", "")):
                kind = r.pop("kind", None)
                r.pop("request_id", None)
                if kind in files:
                    _append(files[kind], r)
    except Exception as exc:
        log.warning("hydrate failed: %s", exc)


def _fan_out(kind: str, row: dict, key: str) -> None:
    """Optional durable copies. Telemetry is an aid and must never fail a claim run, so every error is logged and swallowed."""
    if settings.metrics_table:
        try:
            import boto3
            item = json.loads(json.dumps({**row, "kind": kind, "request_id": key}), parse_float=Decimal)
            boto3.resource("dynamodb", region_name=settings.region).Table(settings.metrics_table).put_item(Item=item)
        except Exception as exc:
            log.warning("dynamodb write failed: %s", exc)
    if settings.calls_bucket and kind in ("call", "run"):
        try:
            import boto3
            boto3.client("s3", region_name=settings.region).put_object(
                Bucket=settings.calls_bucket, Key=f"{kind}s/dt={row['day']}/{key}.json", Body=json.dumps(row).encode(), ContentType="application/json")
        except Exception as exc:
            log.warning("s3 write failed: %s", exc)


def record_call(row: dict) -> None:
    row = _stamp(row)
    _append("calls.jsonl", row)
    _fan_out("call", row, row["call_id"])


def calls() -> list[dict]:
    return _read("calls.jsonl")


def record_alert(row: dict) -> None:
    row = _stamp(row)
    _append("alerts.jsonl", row)
    _fan_out("alert", row, f"alert-{row['ts']}-{row['rule']}")


def alerts() -> list[dict]:
    return _read("alerts.jsonl")
