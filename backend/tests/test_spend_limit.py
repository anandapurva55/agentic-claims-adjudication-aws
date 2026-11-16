"""The daily spend limit. Once today's live model spend reaches the limit, live runs are refused with 429. Replay, viewing and reviewing cost nothing and keep
working. The spend is summed from DynamoDB, so it counts every task, not only the one that happens to receive the request."""
import json
import time
from decimal import Decimal

import boto3
import pytest
from app.api import main
from app.api.main import app
from app.config import settings
from app.services import stores
from fastapi.testclient import TestClient
from moto import mock_aws

client = TestClient(app)
CLAIM = json.load(open("evals/golden/cases.json"))[0]["claim_id"]
TODAY = time.strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    monkeypatch.setattr(settings, "metrics_table", "")
    monkeypatch.setattr(settings, "daily_budget_usd", 1.00)
    monkeypatch.setattr(settings, "mode", "live")  # the spend limit is about a live deployment: a deployment runs in one mode, and replay runs are not allowed in it


@pytest.fixture
def no_agents(monkeypatch):
    """Replace the agent run with a stub so no model is called. Records whether a run started."""
    started = []

    async def fake_run(claim_id, mode, **kw):
        started.append(mode)
        yield {"type": "result", "mode": mode}
    monkeypatch.setattr(main, "run_claim", fake_run)
    return started


def _spend(cost, mode="live", day=TODAY, run="r"):
    stores.record_metric({"run_id": f"{run}-{cost}-{mode}-{day}", "claim_id": "C", "mode": mode, "cost_usd": cost, "ok": True, "day": day,
                          "latency_ms": 1000, "decision": "approve", "input_tokens": 1, "output_tokens": 1})


def _run(mode):
    with client.stream("POST", f"/api/claims/{CLAIM}/run?mode={mode}") as r:
        return r.status_code, [json.loads(x[6:]) for x in r.iter_lines() if x.startswith("data: ") and x != "data: {}"], dict(r.headers)


def test_a_live_run_below_the_limit_goes_ahead(no_agents):
    _spend(0.40)
    status, events, _ = _run("live")
    assert status == 200 and events == [{"type": "result", "mode": "live"}] and no_agents == ["live"]


def test_a_live_run_at_or_over_the_limit_gets_429_and_no_agent_starts(no_agents):
    _spend(0.60)
    _spend(0.40, run="b")  # exactly the limit
    status, _, headers = _run("live")
    assert status == 429 and no_agents == [] and "retry-after" in headers
    body = client.post(f"/api/claims/{CLAIM}/run?mode=live").json()
    assert "daily spend limit of $1.00" in body["detail"] and "viewing and reviewing still work" in body["detail"]


def test_viewing_and_reviewing_keep_working_when_the_limit_is_reached(no_agents):
    _spend(50.0)
    assert client.get("/api/claims").status_code == 200 and client.get(f"/api/claims/{CLAIM}").status_code == 200
    assert client.get("/api/metrics").status_code == 200 and client.get("/api/review-stats").status_code == 200


def test_a_replay_deployment_costs_nothing_so_the_spend_limit_does_not_apply_to_it(no_agents, monkeypatch):
    monkeypatch.setattr(settings, "mode", "replay")
    _spend(50.0)
    assert _run("replay")[0] == 200 and no_agents == ["replay"]


def test_only_todays_live_spend_counts():
    _spend(9.0, mode="replay")
    _spend(9.0, day="2020-01-01")
    _spend(0.25)
    assert stores.spend_today() == 0.25


def test_the_limit_is_read_from_settings(no_agents, monkeypatch):
    _spend(0.40)
    monkeypatch.setattr(settings, "daily_budget_usd", 0.30)
    assert _run("live")[0] == 429


def test_a_run_queued_behind_another_is_checked_again_when_its_turn_comes(monkeypatch, no_agents):
    readings = iter([0.0, 5.0])  # fine when the request arrives, over the limit by the time it is its turn
    monkeypatch.setattr(stores, "spend_today", lambda: next(readings))
    status, events, _ = _run("live")
    assert status == 200 and no_agents == []
    assert events[0]["type"] == "error" and "daily spend limit" in events[0]["message"]


def test_when_the_spend_cannot_be_read_live_runs_are_refused_not_allowed(monkeypatch, no_agents):
    def broken():
        raise RuntimeError("dynamodb unavailable")
    monkeypatch.setattr(stores, "spend_today", broken)
    status, _, _ = _run("live")
    assert status == 503 and no_agents == []
    monkeypatch.setattr(settings, "mode", "replay")  # a replay deployment never reads the spend
    assert _run("replay")[0] == 200


# ---- across tasks: the spend comes from DynamoDB ----------------------------------------------------------------------------------------------------

@pytest.fixture
def metrics_table(monkeypatch):
    with mock_aws():
        for k, v in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}.items():
            monkeypatch.setenv(k, v)
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName="metrics", BillingMode="PAY_PER_REQUEST", KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "request_id", "AttributeType": "S"}, {"AttributeName": "day", "AttributeType": "S"},
                                  {"AttributeName": "ts", "AttributeType": "S"}],
            GlobalSecondaryIndexes=[{"IndexName": "by_day", "KeySchema": [{"AttributeName": "day", "KeyType": "HASH"}, {"AttributeName": "ts", "KeyType": "RANGE"}],
                                     "Projection": {"ProjectionType": "ALL"}}])
        monkeypatch.setattr(settings, "metrics_table", "metrics")
        monkeypatch.setattr(settings, "region", "us-east-1")
        yield boto3.resource("dynamodb", region_name="us-east-1").Table("metrics")


def _put(table, rid, kind, cost, mode="live", day=TODAY):
    table.put_item(Item={"request_id": rid, "kind": kind, "mode": mode, "day": day, "ts": f"{day}T10:00:00#{rid}", "cost_usd": Decimal(str(cost))})


def test_spend_is_summed_from_dynamodb_across_tasks(metrics_table):
    _put(metrics_table, "run-task-a", "run", 0.30)  # written by one task
    _put(metrics_table, "run-task-b", "run", 0.45)  # written by another
    _put(metrics_table, "call-1", "call", 0.30)  # per-call rows must not be counted on top of the run total
    _put(metrics_table, "run-replay", "run", 9.0, mode="replay")
    _put(metrics_table, "run-old", "run", 9.0, day="2020-01-01")
    assert stores.spend_today() == 0.75


def test_a_run_by_another_task_can_close_the_door_for_this_one(metrics_table, no_agents):
    _put(metrics_table, "run-task-a", "run", 0.60)
    assert _run("live")[0] == 200
    _put(metrics_table, "run-task-b", "run", 0.50)  # another task spends, and this task's local file knows nothing about it
    assert _run("live")[0] == 429 and no_agents == ["live"]


def test_spend_follows_pagination(metrics_table, monkeypatch):
    for i in range(30):
        _put(metrics_table, f"run-{i}", "run", 0.01)
    real_query = type(metrics_table).query

    def small_pages(self, **kw):
        return real_query(self, Limit=7, **kw)
    monkeypatch.setattr(type(metrics_table), "query", small_pages)
    assert stores.spend_today() == pytest.approx(0.30)
