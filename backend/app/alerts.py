"""Alert rules, evaluated after every run. Each alert is stored, shown in the UI, and sent to CloudWatch as a metric.

  cost_spike    a run costs more than 3 times the median of the previous 20 live runs (needs at least 10 to compare)
  daily_budget  the day's model spend passed the budget
  failure_rate  more than 20 percent of the last 20 runs failed
"""
from __future__ import annotations

import statistics

from app.config import settings
from app.services import stores

SPIKE_FACTOR = 3.0


def evaluate(run: dict) -> list[dict]:
    fired: list[dict] = []
    runs = [r for r in stores.metrics() if r.get("mode") == run.get("mode")]
    prior = [r for r in runs if r.get("run_id") != run.get("run_id")][-20:]
    costs = [r["cost_usd"] for r in prior if r.get("ok") and r.get("cost_usd")]
    if len(costs) >= 10 and run.get("cost_usd", 0) > SPIKE_FACTOR * statistics.median(costs):
        fired.append({"rule": "cost_spike", "detail": f"Run cost ${run['cost_usd']:.3f} is over {SPIKE_FACTOR:.0f}x the recent median ${statistics.median(costs):.3f}."})
    today = sum(r.get("cost_usd", 0) for r in runs if r.get("day") == run.get("day"))
    if today > settings.daily_budget_usd:
        fired.append({"rule": "daily_budget", "detail": f"Today's model spend ${today:.2f} passed the ${settings.daily_budget_usd:.2f} budget."})
    recent = runs[-20:]
    if len(recent) >= 10 and sum(1 for r in recent if not r.get("ok")) / len(recent) > 0.2:
        fired.append({"rule": "failure_rate", "detail": "More than 20% of the last 20 runs failed."})
    for a in fired:
        stores.record_alert({"claim_id": run.get("claim_id"), **a})
    return fired


def publish(run: dict) -> None:
    """Send the run's cost and latency to CloudWatch so the stack's alarms can watch them. Best effort."""
    if settings.mode != "live":
        return
    try:
        import boto3
        boto3.client("cloudwatch", region_name=settings.region).put_metric_data(Namespace="ClaimsAdjudication", MetricData=[
            {"MetricName": "RunCostUSD", "Value": float(run.get("cost_usd", 0)), "Unit": "None"},
            {"MetricName": "RunLatencyMs", "Value": float(run.get("latency_ms", 0)), "Unit": "Milliseconds"},
            {"MetricName": "RunFailed", "Value": 0.0 if run.get("ok") else 1.0, "Unit": "Count"}])
    except Exception:
        pass
