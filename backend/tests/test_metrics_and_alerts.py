"""Cost, latency and alerting: per call records roll up correctly, and the alert rules fire when they should."""
import time

from app import alerts, pricing
from app.api.main import app
from app.services import stores
from fastapi.testclient import TestClient

client = TestClient(app)
HAIKU = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
NOVA = "global.amazon.nova-2-lite-v1:0"


def _call(agent, model, i, o, ms, cost, run="r1", claim="CLM-1", error="", cache_read=0):
    stores.record_call({"call_id": f"{run}-{agent}-{ms}", "run_id": run, "claim_id": claim, "agent": agent, "model": model, "input_tokens": i,
                        "output_tokens": o, "cache_read": cache_read, "cache_write": 0, "latency_ms": ms, "cost_usd": cost, "error": error})


def _run(cost, ok=True, claim="CLM-1", run="r1", ms=5000):
    row = {"run_id": run, "claim_id": claim, "mode": "live", "latency_ms": ms, "cost_usd": cost, "ok": ok, "decision": "approve",
           "day": time.strftime("%Y-%m-%d"), "input_tokens": 1000, "output_tokens": 100}
    stores.record_metric(row)
    return row


def test_call_cost_uses_per_model_prices_and_cache_discount():
    assert round(pricing.call_cost(HAIKU, 1_000_000, 0), 4) == 1.0
    assert round(pricing.call_cost(HAIKU, 0, 1_000_000), 4) == 5.0
    assert pricing.call_cost(HAIKU, 0, 0, cache_read=1_000_000) == 0.10, "cache reads cost a tenth of input"
    assert pricing.call_cost("unknown-model", 1000, 1000) == 0.0


def test_dashboard_attributes_cost_and_latency_to_agents():
    _call("policy", HAIKU, 12000, 900, 4200, 0.0166)
    _call("policy", HAIKU, 8000, 300, 1800, 0.0095, run="r2")
    _call("intake", NOVA, 2000, 40, 450, 0.0008)
    _run(0.027)
    m = client.get("/api/metrics").json()
    by = {a["name"]: a for a in m["by_agent"]}
    assert by["policy"]["calls"] == 2 and by["policy"]["input_tokens"] == 20000
    assert m["by_agent"][0]["name"] == "policy", "the costliest agent is listed first"
    assert round(sum(a["share"] for a in m["by_agent"]), 2) == 1.0
    assert m["slowest_calls"][0]["latency_ms"] == 4200
    assert m["cost"]["total_usd"] > 0 and m["by_day"][0]["cost_usd"] == 0.027


def test_cost_spike_alert_needs_history_then_fires():
    for i in range(10):
        _run(0.03, run=f"h{i}")
    assert alerts.evaluate(_run(0.05, run="normal")) == [], "under 3x the median is fine"
    fired = alerts.evaluate(_run(0.20, run="spike"))
    assert [a["rule"] for a in fired] == ["cost_spike"]
    assert client.get("/api/metrics").json()["alerts"][0]["rule"] == "cost_spike"


def test_no_spike_alert_without_enough_history():
    for i in range(3):
        _run(0.03, run=f"h{i}")
    assert alerts.evaluate(_run(0.9, run="big")) == []


def test_daily_budget_alert(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "daily_budget_usd", 0.10)
    _run(0.08, run="a")
    fired = alerts.evaluate(_run(0.08, run="b"))
    assert "daily_budget" in [a["rule"] for a in fired]


def test_failure_rate_alert():
    for i in range(12):
        _run(0.03, ok=i % 2 == 0, run=f"f{i}")
    fired = alerts.evaluate(_run(0.03, ok=False, run="last"))
    assert "failure_rate" in [a["rule"] for a in fired]


def test_publishing_metrics_is_skipped_offline_sent_live_and_a_failure_is_logged_not_raised(monkeypatch, caplog):
    import boto3
    from app.config import settings
    sent = []

    class Cw:
        def put_metric_data(self, **kw):
            sent.append(kw)
    monkeypatch.setattr(boto3, "client", lambda *a, **k: Cw())
    run = {"cost_usd": 0.04, "latency_ms": 9000, "ok": True}
    monkeypatch.setattr(settings, "mode", "replay")
    alerts.publish(run)
    assert sent == []  # nothing is sent from a replay run
    monkeypatch.setattr(settings, "mode", "live")
    alerts.publish(run)
    assert {m["MetricName"] for m in sent[0]["MetricData"]} == {"RunCostUSD", "RunLatencyMs", "RunFailed"} and sent[0]["Namespace"] == "ClaimsAdjudication"

    def broken(*a, **k):
        raise RuntimeError("throttled")
    monkeypatch.setattr(boto3, "client", broken)
    alerts.publish(run)  # must not raise
    assert "publishing run metrics to CloudWatch failed" in caplog.text
