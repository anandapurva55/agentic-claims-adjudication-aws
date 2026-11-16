"""Request limits. Everything a caller sends is either one of a fixed set of values or has a length limit, so a request cannot park arbitrary amounts of text
in the audit log or the lesson memory, and a typo in an action or role is rejected instead of being stored."""
import json

import pytest
from app.api.main import app
from app.config import settings
from fastapi.testclient import TestClient

client = TestClient(app)
CASES = json.load(open("evals/golden/cases.json"))
CLEAN = next(c["claim_id"] for c in CASES if c["scenario"] == "clean")


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)


def _ran() -> str:
    with client.stream("GET", f"/api/claims/{CLEAN}/run?mode=replay") as r:
        list(r.iter_lines())
    return CLEAN


def _review(**body):
    return client.post(f"/api/claims/{CLEAN}/review", json=body)


@pytest.mark.parametrize("body", [
    {"action": "approve"}, {"action": "ACCEPT"}, {"action": ""},
    {"action": "override", "final_decision": "maybe", "note": "a perfectly good reason"},
    {"action": "accept", "role": "admin"}, {"action": "accept", "role": "Senior"}])
def test_unknown_values_are_rejected_before_anything_is_stored(body):
    _ran()
    assert _review(**body).status_code == 422
    assert client.get(f"/api/claims/{CLEAN}").json()["review"] is None


@pytest.mark.parametrize("reviewer", ["", "x" * 61, "<script>alert(1)</script>", "a\nb", "ok; DROP TABLE", " leading"])
def test_a_reviewer_name_is_short_and_plain(reviewer):
    _ran()
    assert _review(action="accept", reviewer=reviewer).status_code == 422


def test_a_reasonable_reviewer_name_is_accepted():
    _ran()
    assert _review(action="accept", reviewer="S. Rao", role="senior").status_code == 200


def test_an_override_reason_over_one_thousand_characters_is_rejected():
    _ran()
    long_note = "Driver was sober according to the breath test. " * 30
    assert len(long_note) > 1000
    assert _review(action="override", final_decision="deny", note=long_note).status_code == 422
    assert _review(action="override", final_decision="deny", note=long_note[:900]).status_code == 200


def test_a_malformed_or_oversized_body_is_rejected():
    assert client.post(f"/api/claims/{CLEAN}/review", content=b"not json", headers={"content-type": "application/json"}).status_code == 422
    assert client.post(f"/api/claims/{CLEAN}/review", json={"action": ["accept"]}).status_code == 422


def test_the_attack_lab_refuses_text_over_four_thousand_characters():
    assert client.post("/api/security/scan", json={"text": "a" * 4000}).status_code == 200
    assert client.post("/api/security/scan", json={"text": "a" * 4001}).status_code == 422
    assert client.post("/api/security/scan", json={}).status_code == 422


def test_the_run_mode_can_only_be_replay_or_live():
    for bad in ("bogus", "LIVE", "replay;live", ""):
        assert client.get(f"/api/claims/{CLEAN}/run?mode={bad}").status_code == 422
    with client.stream("GET", f"/api/claims/{CLEAN}/run?mode=replay") as r:
        assert r.status_code == 200
