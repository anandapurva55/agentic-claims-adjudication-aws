"""Request ids and structured logs: every request gets an id, every log line carries it, and each request ends with one line saying who did what."""
import json
import logging

import pytest
from app.api.main import app
from app.config import settings
from app.observability import JsonFormatter, request_id_var
from fastapi.testclient import TestClient

client = TestClient(app)
CLAIM = json.load(open("evals/golden/cases.json"))[0]["claim_id"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)


def lines(caplog):
    return [r for r in caplog.records if r.name == "adjudication.api" and r.getMessage() == "request"]


def test_every_response_carries_a_request_id_and_each_request_is_logged_once(caplog):
    with caplog.at_level(logging.INFO, logger="adjudication.api"):
        r = client.get("/api/health")
    rid = r.headers["x-request-id"]
    assert len(rid) == 16
    (rec,) = lines(caplog)
    assert (rec.fields["method"], rec.fields["path"], rec.fields["status"]) == ("GET", "/api/health", 200)
    assert isinstance(rec.fields["ms"], int) and rec.fields["user"] == "-"


def test_the_log_says_who_called(caplog):
    with caplog.at_level(logging.INFO, logger="adjudication.api"):
        client.get("/api/claims", headers={"X-Demo-User": "asha"})
    assert lines(caplog)[-1].fields["user"] == "asha"


def test_a_plain_id_from_the_caller_is_kept_and_a_hostile_one_is_replaced():
    assert client.get("/api/health", headers={"X-Request-ID": "trace-12345678"}).headers["x-request-id"] == "trace-12345678"
    for bad in ("x", "has spaces in it", 'a"b' * 10, "line\\nbreak" * 4, "x" * 200):
        assert client.get("/api/health", headers={"X-Request-ID": bad}).headers["x-request-id"] != bad


def test_refused_and_failed_requests_are_logged_too(caplog, monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "cognito_user_pool_id", "us-east-1_X")
    monkeypatch.setattr(s, "cognito_client_id", "c")
    with caplog.at_level(logging.INFO, logger="adjudication.api"):
        assert client.get("/api/claims").status_code == 401
    assert lines(caplog)[-1].fields["status"] == 401


def test_an_unhandled_error_is_logged_with_its_traceback_and_request_id(caplog, monkeypatch):
    from app.services import stores
    monkeypatch.setattr(stores, "stages", lambda: (_ for _ in ()).throw(RuntimeError("store down")))
    with caplog.at_level(logging.INFO, logger="adjudication.api"):
        with pytest.raises(RuntimeError):
            TestClient(app).get("/api/claims")
    failed = [r for r in caplog.records if r.getMessage() == "request failed"]
    assert failed and failed[0].exc_info and lines(caplog)[-1].fields["status"] == 500


def test_a_streamed_run_still_streams_and_is_logged_with_its_final_status(caplog):
    with caplog.at_level(logging.INFO, logger="adjudication.api"):
        with client.stream("POST", f"/api/claims/{CLAIM}/run?mode=replay") as r:
            body = "".join(r.iter_text())
    assert "event: end" in body and '"type": "result"' in body
    assert lines(caplog)[-1].fields["path"].endswith("/run") and lines(caplog)[-1].fields["status"] == 200


def test_the_json_formatter_adds_the_request_id_to_any_log_line():
    token = request_id_var.set("abc123")
    try:
        record = logging.LogRecord("adjudication.telemetry", logging.WARNING, __file__, 1, "dynamodb write failed: %s", ("boom",), None)
        out = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert out["request_id"] == "abc123" and out["message"] == "dynamodb write failed: boom" and out["level"] == "WARNING" and out["ts"].endswith("Z")
