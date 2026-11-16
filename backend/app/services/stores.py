"""Audit log, human review decisions and run metrics. Local JSONL in development and CI, DynamoDB in AWS (the source of truth for the audit log)."""
from __future__ import annotations

import json
import logging
import threading
import time
from decimal import Decimal
from pathlib import Path

from botocore.exceptions import ClientError

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


REVIEW_KEY = "REVIEW"  # fixed sort key: a claim can hold at most one human review item, which is how "one decision per claim" is enforced
_local_lock = threading.Lock()


class AlreadyReviewed(Exception):
    """The claim already has a human decision."""


def _table(name: str):
    import boto3
    return boto3.resource("dynamodb", region_name=settings.region).Table(name)


def _plain(obj):
    """DynamoDB returns Decimal. Turn it back into int or float."""
    return json.loads(json.dumps(obj, default=lambda d: int(d) if d == int(d) else float(d)))


def audit(claim_id: str, actor: str, action: str, detail: dict) -> dict:
    """Append one audit row. In AWS the row goes to DynamoDB only, which is the source of truth, so every task sees the same log.

    A human review is written with a condition that no review exists yet for the claim, so when two reviewers decide at the same moment the database lets
    exactly one through and the other gets AlreadyReviewed. Failures are raised, not swallowed: an audit record that was not stored must not look stored.
    """
    row = {"claim_id": claim_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "actor": actor, "action": action, "detail": detail}
    review, seq = action == "human_review", time.time_ns()
    if settings.audit_table:
        item = json.loads(json.dumps({**row, "at": row["ts"], "seq": seq, "ts": REVIEW_KEY if review else f"{row['ts']}#{seq:020d}"}), parse_float=Decimal)
        try:
            _table(settings.audit_table).put_item(Item=item, **({"ConditionExpression": "attribute_not_exists(claim_id)"} if review else {}))
        except ClientError as exc:
            if review and exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AlreadyReviewed(claim_id) from exc
            raise
        return row
    with _local_lock:  # local development and CI: the same rule, enforced by a lock around check and append
        if review and any(r["claim_id"] == claim_id and r["action"] == "human_review" for r in _read("audit.jsonl")):
            raise AlreadyReviewed(claim_id)
        _append("audit.jsonl", row)
    return row


def _rows(claim_id: str | None = None) -> list[dict]:
    """Audit rows in time order, read from DynamoDB with strong consistency in AWS and from the local file otherwise."""
    if not settings.audit_table:
        return [r for r in _read("audit.jsonl") if claim_id is None or r["claim_id"] == claim_id]
    from boto3.dynamodb.conditions import Key
    t, items, kw = _table(settings.audit_table), [], {"ConsistentRead": True}
    while True:
        r = t.query(KeyConditionExpression=Key("claim_id").eq(claim_id), **kw) if claim_id else t.scan(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    items = _plain(items)
    items.sort(key=lambda i: (i.get("at", ""), i.get("seq", 0)))
    return [{**{k: v for k, v in i.items() if k not in ("at", "seq")}, "ts": i.get("at", i["ts"])} for i in items]


def audit_for(claim_id: str) -> list[dict]:
    return _rows(claim_id)


def record_metric(row: dict) -> None:
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "day": time.strftime("%Y-%m-%d"), **row}
    _append("metrics.jsonl", row)
    _fan_out("run", row, f"run-{row.get('run_id', row['ts'])}")


def metrics() -> list[dict]:
    return _read("metrics.jsonl")


def spend_today() -> float:
    """What live model calls have cost today, in USD. In AWS it is summed from the DynamoDB metrics table through the by_day index, so every task sees the
    spend of every other task; locally it is summed from the metrics file. Raises when the table cannot be read: the caller must not guess."""
    today = time.strftime("%Y-%m-%d")
    if not settings.metrics_table:
        return round(sum(r.get("cost_usd", 0) for r in metrics() if r.get("day") == today and r.get("mode") == "live"), 6)
    from boto3.dynamodb.conditions import Key
    table, total, kw = _table(settings.metrics_table), 0.0, {}
    while True:
        r = table.query(IndexName="by_day", KeyConditionExpression=Key("day").eq(today), **kw)
        total += sum(float(i.get("cost_usd", 0)) for i in r["Items"] if i.get("kind") == "run" and i.get("mode") == "live")
        if "LastEvaluatedKey" not in r:
            return round(total, 6)
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def _reviews_from(rows: list[dict]) -> dict[str, dict]:
    return {r["claim_id"]: r for r in rows if r["action"] == "human_review"}


def reviews() -> dict[str, dict]:
    return _reviews_from(_rows())


def latest(claim_id: str, action: str) -> dict | None:
    rows = [r for r in audit_for(claim_id) if r["action"] == action]
    return rows[-1] if rows else None


def _stage_from(rows: list[dict]) -> dict:
    """Lifecycle from one claim's audit rows: new -> ai_recommended -> reviewed. A human review is the only way out of ai_recommended, and it is final:
    running the agents again afterwards does not reopen the claim."""
    ai = next((r for r in reversed(rows) if r["action"] == "decision"), None)
    human = next((r for r in reversed(rows) if r["action"] == "human_review"), None)
    if human:
        return {"stage": "reviewed", "ai": ai["detail"] if ai else None, "review": human["detail"]}
    if ai:
        return {"stage": "ai_recommended", "ai": ai["detail"], "review": None}
    return {"stage": "new", "ai": None, "review": None}


def stage_for(claim_id: str) -> dict:
    return _stage_from(audit_for(claim_id))


def stages() -> dict[str, dict]:
    """The stage of every claim that has any audit row, from ONE read of the audit log. Listing claims uses this, not one query per claim."""
    by_claim: dict[str, list[dict]] = {}
    for r in _rows():
        by_claim.setdefault(r["claim_id"], []).append(r)
    return {cid: _stage_from(rows) for cid, rows in by_claim.items()}


def review_stats() -> dict:
    rows = _rows()
    details = [r["detail"] for r in _reviews_from(rows).values()]
    accepted = sum(r["action"] == "accept" for r in details)
    overridden = sum(r["action"] == "override" for r in details)
    escalated = sum(r["action"] == "escalate" for r in details)
    decided = accepted + overridden
    return {"reviewed": len(details), "accepted": accepted, "overridden": overridden, "escalated": escalated,
            "agreement_rate": round(accepted / decided, 3) if decided else None,
            "override_candidates": sum(r["action"] == "override_candidate" for r in rows)}


def add_override_candidate(row: dict) -> None:
    """An override means the AI and a human disagreed. Each one is a candidate golden case for the next eval run, kept in the audit log."""
    audit(row["claim_id"], "system", "override_candidate", row)


log = logging.getLogger("adjudication.telemetry")


def _stamp(row: dict) -> dict:
    return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "day": time.strftime("%Y-%m-%d"), "mode": settings.mode, **row}


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
    """On start, rebuild the local metric files from DynamoDB when they are missing, so a new task shows the history of the old one. The audit log is not
    restored here: it is read from DynamoDB directly, because it carries an invariant and a per-task copy would diverge."""
    try:
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
