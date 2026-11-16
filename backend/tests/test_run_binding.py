"""A person approves what the AI recommended, so the recommendation has to be the deployment's own and the reviewer has to approve the one they looked at.
A review of the system found that a signed-in user could start a replay run in a live deployment, which stored the keyword baseline's answer as the "AI
recommendation" that a person then approved, and that "accept" meant "whatever is latest when the server reads it". These tests pin both fixes."""
import json

import pytest
from app.api.main import app
from app.config import settings
from app.services import stores
from fastapi.testclient import TestClient

client = TestClient(app)
CASES = json.load(open("evals/golden/cases.json"))
CLEAN = next(c["claim_id"] for c in CASES if c["scenario"] == "clean")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    from app.api import main
    real = main.run_claim

    def never_live(claim_id, mode, *a, **kw):  # if a guard under test ever breaks, fail the test instead of calling Bedrock and spending money
        assert mode != "live", "a test reached a live agent run"
        return real(claim_id, mode, *a, **kw)
    monkeypatch.setattr(main, "run_claim", never_live)


def run(claim=CLEAN, mode="replay"):
    with client.stream("POST", f"/api/claims/{claim}/run?mode={mode}") as r:
        events = [json.loads(x[6:]) for x in r.iter_lines() if x.startswith("data: ") and x != "data: {}"]
        return r.status_code, events


def ai(claim=CLEAN) -> dict:
    return client.get(f"/api/claims/{claim}").json()["ai"]


def review(run_id, claim=CLEAN, **body):
    return client.post(f"/api/claims/{claim}/review", json={"action": "accept", "run_id": run_id, **body})


# ---- a deployment runs in one mode -----------------------------------------------------------------------------------------------------------------

def test_a_live_deployment_refuses_a_replay_run_and_stores_nothing(monkeypatch):
    monkeypatch.setattr(settings, "mode", "live")
    status, _ = run(mode="replay")
    assert status == 409
    assert client.get(f"/api/claims/{CLEAN}").json()["ai"] is None and stores.stage_for(CLEAN)["stage"] == "new"
    detail = client.post(f"/api/claims/{CLEAN}/run?mode=replay").json()["detail"]
    assert "runs in live mode" in detail and "replay run is not allowed" in detail


def test_the_reported_attack_fails_at_both_steps(monkeypatch):
    """Run replay in a live deployment, then accept it: the first step is refused, and with nothing recommended the second is refused too."""
    monkeypatch.setattr(settings, "mode", "live")
    assert run(mode="replay")[0] == 409
    assert review("anything").status_code == 409


def test_a_replay_deployment_refuses_a_live_run(monkeypatch):
    monkeypatch.setattr(settings, "mode", "replay")
    assert client.post(f"/api/claims/{CLEAN}/run?mode=live").status_code == 409


def test_leaving_the_mode_out_means_the_deployments_own():
    status, events = run(mode="replay")
    with client.stream("POST", f"/api/claims/{CLEAN}/run") as r:
        assert r.status_code == 200
        list(r.iter_lines())
    assert status == 200 and events[-1]["type"] == "result"


# ---- a review names the run it looked at -----------------------------------------------------------------------------------------------------------

def test_the_decision_row_and_the_result_event_carry_the_run_id():
    _, events = run()
    result = next(e for e in events if e["type"] == "result")
    assert ai()["run_id"] == result["run_id"] and ai()["mode"] == "replay" and len(result["run_id"]) >= 8


def test_a_review_must_name_a_run_and_a_wrong_one_is_refused_without_deciding_the_claim():
    run()
    assert client.post(f"/api/claims/{CLEAN}/review", json={"action": "accept"}).status_code == 422
    r = review("not-the-run-you-saw")
    assert r.status_code == 409 and "changed since you looked" in r.json()["detail"]
    assert stores.stage_for(CLEAN)["stage"] == "ai_recommended"  # nothing was decided


def test_accept_means_the_run_the_reviewer_looked_at_not_whatever_is_latest():
    _, first = run()
    looked_at = next(e for e in first if e["type"] == "result")["run_id"]
    _, second = run()  # someone else runs the agents again while the reviewer reads
    latest = next(e for e in second if e["type"] == "result")["run_id"]
    assert latest != looked_at
    assert review(looked_at).status_code == 409
    ok = review(latest)
    assert ok.status_code == 200
    row = client.get(f"/api/claims/{CLEAN}").json()["review"]
    assert row["run_id"] == latest, "the audit row records which run the human decided on"


def test_a_recommendation_that_has_no_run_id_cannot_be_approved():
    stores.audit(CLEAN, "ai", "decision", {"decision": "approve", "payable": 1, "clauses": [], "mode": "replay"})  # written before run ids existed
    assert review("whatever").status_code == 409


def test_an_old_replay_recommendation_cannot_be_approved_in_a_live_deployment(monkeypatch):
    stores.audit(CLEAN, "ai", "decision", {"decision": "approve", "payable": 1, "clauses": [], "mode": "replay", "run_id": "run-from-replay"})
    monkeypatch.setattr(settings, "mode", "live")
    r = review("run-from-replay")  # the run id matches, but it was not produced by this deployment's mode
    assert r.status_code == 409 and "came from a replay run" in r.json()["detail"]
    assert stores.stage_for(CLEAN)["stage"] == "ai_recommended"
