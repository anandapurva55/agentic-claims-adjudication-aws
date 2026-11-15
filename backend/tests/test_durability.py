"""The audit log and metrics must survive a container restart, which wipes local files."""
from app.config import settings
from app.services import stores


def test_audit_is_copied_to_dynamodb_and_restored(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(settings, "audit_table", "audit")
    monkeypatch.setattr(settings, "metrics_table", "")
    monkeypatch.setattr(stores, "_put", lambda table, item: saved.append((table, item)))
    stores.audit("CLM-1", "adjuster", "human_review", {"decision": "approve"})
    stores.audit("CLM-1", "system", "ai_recommended", {})
    assert [t for t, _ in saved] == ["audit", "audit"]
    assert saved[0][1]["ts"] != saved[1][1]["ts"], "two events in one second must not overwrite each other"

    # a new container: empty runtime dir, same table
    monkeypatch.setattr(settings, "runtime_dir", tmp_path / "fresh")
    monkeypatch.setattr(stores, "_scan", lambda table: [item for _, item in saved])
    stores.hydrate()
    assert [r["action"] for r in stores.audit_for("CLM-1")] == ["human_review", "ai_recommended"]
    assert stores.reviews()["CLM-1"]["detail"]["decision"] == "approve"


def test_metrics_and_calls_are_restored(monkeypatch, tmp_path):
    rows = [{"kind": "run", "request_id": "r1", "ts": "2026-11-15T10:00:00", "run_id": "r1", "cost_usd": 0.04},
            {"kind": "call", "request_id": "c1", "ts": "2026-11-15T10:00:01", "call_id": "c1"}]
    monkeypatch.setattr(settings, "audit_table", "")
    monkeypatch.setattr(settings, "metrics_table", "metrics")
    monkeypatch.setattr(stores, "_scan", lambda table: [dict(r) for r in rows])
    stores.hydrate()
    assert stores.metrics()[0]["run_id"] == "r1" and stores.calls()[0]["call_id"] == "c1"
