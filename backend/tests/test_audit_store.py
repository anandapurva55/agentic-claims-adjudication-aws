"""The audit log is the source of truth for human decisions, so these tests pin its guarantees: it survives a restart, every task reads the same log,
and when two reviewers decide the same claim at the same moment exactly one of them wins."""
import json
import threading

import boto3
import pytest
from app.api.main import app
from app.config import settings
from app.services import stores
from fastapi.testclient import TestClient
from moto import mock_aws

CASES = json.load(open("evals/golden/cases.json"))
WORKERS = 8


@pytest.fixture
def ddb(monkeypatch):
    """An in-memory DynamoDB table shaped like the CDK audit table (claim_id, ts)."""
    with mock_aws():
        for k, v in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}.items():
            monkeypatch.setenv(k, v)
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName="audit", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "claim_id", "KeyType": "HASH"}, {"AttributeName": "ts", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "claim_id", "AttributeType": "S"}, {"AttributeName": "ts", "AttributeType": "S"}])
        monkeypatch.setattr(settings, "audit_table", "audit")
        monkeypatch.setattr(settings, "region", "us-east-1")
        yield


def _race(fn, workers: int = WORKERS) -> list:
    """Run fn in several threads released at the same instant. Returns what each one returned, or the exception it raised."""
    out, gate = [None] * workers, threading.Barrier(workers)

    def work(i: int) -> None:
        gate.wait()
        try:
            out[i] = fn(i)
        except Exception as exc:  # noqa: BLE001
            out[i] = exc
    threads = [threading.Thread(target=work, args=(i,)) for i in range(workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return out


def test_audit_rows_are_read_from_dynamodb_not_from_a_local_copy(ddb, tmp_path, monkeypatch):
    stores.audit("CLM-1", "ai", "decision", {"decision": "deny"})
    stores.audit("CLM-1", "adjuster:a", "human_review", {"action": "accept"})
    stores.audit("CLM-1", "system", "outcome", {"final": "deny"})
    monkeypatch.setattr(settings, "runtime_dir", tmp_path / "a_new_task")  # a restarted or second task has no local state at all
    assert [r["action"] for r in stores.audit_for("CLM-1")] == ["decision", "human_review", "outcome"]
    assert stores.stage_for("CLM-1")["stage"] == "reviewed"
    assert not (tmp_path / "a_new_task" / "audit.jsonl").exists(), "AWS mode must not keep a second copy that could diverge"


def test_events_in_the_same_second_keep_their_order(ddb):
    for i in range(12):
        stores.audit("CLM-2", "system", "event", {"i": i})
    assert [r["detail"]["i"] for r in stores.audit_for("CLM-2")] == list(range(12))


def test_a_second_review_of_the_same_claim_is_refused(ddb):
    stores.audit("CLM-3", "adjuster:a", "human_review", {"action": "accept"})
    with pytest.raises(stores.AlreadyReviewed):
        stores.audit("CLM-3", "senior:b", "human_review", {"action": "override"})
    stores.audit("CLM-4", "adjuster:a", "human_review", {"action": "accept"})  # other claims are unaffected
    assert len([r for r in stores.audit_for("CLM-3") if r["action"] == "human_review"]) == 1


def test_two_workers_deciding_one_claim_exactly_one_wins_in_dynamodb(ddb):
    results = _race(lambda i: stores.audit("CLM-5", f"adjuster:w{i}", "human_review", {"action": "accept", "worker": i}))
    winners = [r for r in results if isinstance(r, dict)]
    losers = [r for r in results if isinstance(r, stores.AlreadyReviewed)]
    assert len(winners) == 1 and len(losers) == WORKERS - 1, results
    stored = [r for r in stores.audit_for("CLM-5") if r["action"] == "human_review"]
    assert len(stored) == 1 and stored[0]["detail"]["worker"] == int(stored[0]["actor"].split("w")[1])


def test_the_same_rule_holds_in_local_mode(tmp_path):
    results = _race(lambda i: stores.audit("CLM-6", f"adjuster:w{i}", "human_review", {"action": "accept"}))
    assert sum(isinstance(r, dict) for r in results) == 1 and sum(isinstance(r, stores.AlreadyReviewed) for r in results) == WORKERS - 1


def test_running_the_agents_again_after_a_review_does_not_reopen_the_claim(tmp_path):
    stores.audit("CLM-7", "ai", "decision", {"decision": "deny"})
    stores.audit("CLM-7", "adjuster:a", "human_review", {"action": "accept"})
    stores.audit("CLM-7", "ai", "decision", {"decision": "deny"})  # a later run, for example to compare models
    assert stores.stage_for("CLM-7")["stage"] == "reviewed"


def test_two_reviewers_posting_to_the_api_at_once_get_one_200_and_the_rest_409(ddb):
    cid = next(c["claim_id"] for c in CASES if c["scenario"] == "clean")
    with TestClient(app) as c, c.stream("POST", f"/api/claims/{cid}/run?mode=replay") as r:
        list(r.iter_lines())  # the agents must have produced a recommendation before anyone can review it
    with TestClient(app) as c:
        run_id = c.get(f"/api/claims/{cid}").json()["ai"]["run_id"]  # every reviewer is looking at the same run

    def post(i: int) -> int:
        with TestClient(app) as c:
            return c.post(f"/api/claims/{cid}/review", json={"action": "accept", "note": "", "run_id": run_id}, headers={"X-Demo-Role": "senior", "X-Demo-User": f"w{i}"}).status_code
    codes = sorted(_race(post, workers=6))
    assert codes == [200] + [409] * 5, codes
    stage = stores.stage_for(cid)
    assert stage["stage"] == "reviewed" and len([r for r in stores.audit_for(cid) if r["action"] == "human_review"]) == 1


def test_metrics_and_calls_are_restored(monkeypatch):
    rows = [{"kind": "run", "request_id": "r1", "ts": "2026-11-15T10:00:00", "run_id": "r1", "cost_usd": 0.04},
            {"kind": "call", "request_id": "c1", "ts": "2026-11-15T10:00:01", "call_id": "c1"}]
    monkeypatch.setattr(settings, "metrics_table", "metrics")
    monkeypatch.setattr(stores, "_scan", lambda table: [dict(r) for r in rows])
    stores.hydrate()
    assert stores.metrics()[0]["run_id"] == "r1" and stores.calls()[0]["call_id"] == "c1"


class _Counting:
    """Counts DynamoDB reads so a test can state how many round trips a page load is allowed to make."""
    def __init__(self, table, tally):
        self.t, self.n = table, tally

    def query(self, **kw):
        self.n["query"] += 1
        return self.t.query(**kw)

    def scan(self, **kw):
        self.n["scan"] += 1
        return self.t.scan(**kw)

    def put_item(self, **kw):
        return self.t.put_item(**kw)


def test_listing_claims_reads_the_audit_log_once_not_twice_per_claim(ddb, monkeypatch):
    stores.audit("CLM-2026001", "ai", "decision", {"decision": "approve"})
    stores.audit("CLM-2026002", "ai", "decision", {"decision": "deny"})
    stores.audit("CLM-2026002", "adjuster:a", "human_review", {"action": "accept"})
    real, tally = stores._table, {"query": 0, "scan": 0}
    monkeypatch.setattr(stores, "_table", lambda name: _Counting(real(name), tally))
    with TestClient(app) as c:
        listing = {x["claim_id"]: x["stage"] for x in c.get("/api/claims").json()}
    assert len(listing) == 63 and tally == {"query": 0, "scan": 1}, tally  # was 126 queries
    assert listing["CLM-2026001"] == "ai_recommended" and listing["CLM-2026002"] == "reviewed" and listing["CLM-2026003"] == "new"
    tally.update(query=0, scan=0)
    stores.stage_for("CLM-2026002")
    assert tally == {"query": 1, "scan": 0}, tally  # one query for one claim, not two
