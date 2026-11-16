"""Cost metering, Bedrock Data Automation and the vision model, tested with fakes so no AWS call is made. Cost accounting is what the cost-per-claim
numbers rest on, and the Data Automation client has a polling loop with a timeout and two failure paths, so both are pinned here."""
import asyncio
import io
import json

import pytest
from app import telemetry
from app.config import settings
from app.runstate import RunState, set_state
from app.services import bda, stores, vision

HAIKU = "global.anthropic.claude-haiku-4-5-20251001-v1:0"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    for name in ("metrics_table", "calls_bucket", "audit_table"):
        monkeypatch.setattr(settings, name, "")
    for k, v in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(k, v)
    set_state(RunState(claim_id="CLM-T"))


# ---- cost metering -------------------------------------------------------------------------------------------------------------------------------

def test_log_call_prices_input_output_and_cache_tokens_separately():
    row = telemetry.log_call("coverage", HAIKU, {"inputTokens": 1000, "outputTokens": 200, "cacheReadInputTokens": 5000, "cacheWriteInputTokens": 400}, 250, 300)
    # 1000*1.00 + 200*5.00 + 5000*0.10 + 400*1.25 = 3000 micro-dollars
    assert row["cost_usd"] == 0.003 and row["latency_ms"] == 250 and row["claim_id"] == "CLM-T"
    assert stores.calls()[-1]["call_id"] == row["call_id"]


def test_log_call_falls_back_to_wall_time_when_the_model_reports_no_latency():
    assert telemetry.log_call("a", HAIKU, {}, 0, 777)["latency_ms"] == 777


def test_an_unknown_model_costs_nothing_instead_of_raising():
    assert telemetry.log_call("a", "some.other-model", {"inputTokens": 10_000}, 1, 1)["cost_usd"] == 0.0


def _model(monkeypatch, events=None, boom=None):
    async def fake_stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        for e in events or []:
            yield e
        if boom:
            raise boom
    monkeypatch.setattr(telemetry.BedrockModel, "stream", fake_stream)
    return telemetry.MeteredBedrockModel(model_id=HAIKU, region_name="us-east-1", agent_name="investigator")


def _drain(model):
    async def go():
        return [e async for e in model.stream([], None, None)]
    return asyncio.run(go())


def test_the_model_logs_one_row_per_call_from_the_streams_metadata_event(monkeypatch):
    events = [{"contentBlockDelta": {}}, {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 50}, "metrics": {"latencyMs": 420}}}]
    assert _drain(_model(monkeypatch, events)) == events  # events pass through untouched
    row = stores.calls()[-1]
    assert (row["agent"], row["input_tokens"], row["output_tokens"], row["latency_ms"], row["model"]) == ("investigator", 100, 50, 420, HAIKU)
    assert row["error"] == ""


def test_a_failing_call_is_logged_with_its_error_and_still_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="throttled"):
        _drain(_model(monkeypatch, boom=RuntimeError("throttled")))
    assert stores.calls()[-1]["error"] == "throttled"


def test_a_telemetry_failure_never_breaks_the_claim_but_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(telemetry, "log_call", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert _drain(_model(monkeypatch, [{"metadata": {"usage": {}}}])) == [{"metadata": {"usage": {}}}]
    assert "recording a model call failed" in caplog.text


# ---- Bedrock Data Automation ---------------------------------------------------------------------------------------------------------------------

class FakeS3:
    def __init__(self, objects):
        self.objects, self.uploaded = objects, []

    def upload_file(self, path, bucket, key):
        self.uploaded.append((path, bucket, key))

    def get_object(self, Bucket, Key):  # noqa: N803  (boto3 argument names)
        return {"Body": io.BytesIO(self.objects[f"s3://{Bucket}/{Key}"])}


class FakeRuntime:
    def __init__(self, statuses):
        self.statuses, self.started = list(statuses), []

    def invoke_data_automation_async(self, **kw):
        self.started.append(kw)
        return {"invocationArn": "arn:job"}

    def get_data_automation_status(self, invocationArn):  # noqa: N803
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]


def _client(monkeypatch, statuses, objects=None):
    s3, rt = FakeS3(objects or {}), FakeRuntime(statuses)
    sts = type("Sts", (), {"get_caller_identity": lambda self: {"Account": "123456789012"}})()
    monkeypatch.setattr(bda.boto3, "client", lambda svc, **kw: {"s3": s3, "bedrock-data-automation-runtime": rt, "sts": sts}[svc])
    monkeypatch.setattr(bda.time, "sleep", lambda s: None)
    return bda.BdaClient("bkt", "arn:project"), s3, rt


def test_process_uploads_polls_until_success_and_returns_blueprint_fields(monkeypatch, tmp_path):
    out = "s3://bkt/bda/output/CLM/form"
    meta = {"output_metadata": [{"segment_metadata": [{"custom_output_path": "s3://bkt/c.json", "standard_output_path": "s3://bkt/s.json"}]}]}
    objects = {f"{out}/job.json": json.dumps(meta).encode(),
               "s3://bkt/c.json": json.dumps({"inference_result": {"damaged_parts": ["Door"]}, "matched_blueprint": {"name": "photo"}}).encode(),
               "s3://bkt/s.json": json.dumps({"summary": "dented door"}).encode()}
    status_ok = {"status": "Success", "outputConfiguration": {"s3Uri": f"{out}/job.json"}}
    client, s3, rt = _client(monkeypatch, [{"status": "InProgress"}, {"status": "InProgress"}, status_ok], objects)
    f = tmp_path / "form.pdf"
    f.write_bytes(b"x")
    result = client.process(f, "CLM")
    assert result["custom"] == {"damaged_parts": ["Door"]} and result["blueprint"] == "photo" and result["standard"] == {"summary": "dented door"}
    assert s3.uploaded == [(str(f), "bkt", "bda/input/CLM/form.pdf")]
    assert rt.started[0]["dataAutomationProfileArn"].endswith("123456789012:data-automation-profile/us.data-automation-v1")
    assert bda.photo_parts(result) == ["door"]


def test_process_raises_with_the_service_message_when_the_job_fails(monkeypatch, tmp_path):
    client, *_ = _client(monkeypatch, [{"status": "ClientError", "errorMessage": "bad file"}])
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="ClientError: bad file"):
        client.process(f, "CLM")


def test_process_gives_up_after_the_timeout(monkeypatch, tmp_path):
    client, *_ = _client(monkeypatch, [{"status": "InProgress"}])
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    with pytest.raises(TimeoutError, match="still running"):
        client.process(f, "CLM", timeout=-1)


def test_photo_parts_keeps_only_the_five_known_words_normalised():
    assert bda.photo_parts({"custom": {"damaged_parts": ["Front Bumper", "wing mirror", "HOOD", "hood"]}}) == ["front_bumper", "hood"]
    assert bda.photo_parts({}) == [] and bda.photo_parts({"custom": {"damaged_parts": None}}) == []


# ---- vision model --------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ('{"damaged_parts": ["door", "Hood"]}', ["door", "hood"]),
    ('Sure! ```json\n{"damaged_parts": ["headlamp", "roof"]}\n```', ["headlamp"]),
    ("no json here", []), ('{"damaged_parts": ', []), ('{"other": 1}', [])])
def test_vision_parse_is_tolerant_and_keeps_only_known_parts(text, expected):
    assert vision.parse(text) == expected


def test_damaged_parts_sends_the_photo_and_parses_the_answer(monkeypatch, tmp_path):
    seen = {}

    class Client:
        def converse(self, **kw):
            seen.update(kw)
            return {"output": {"message": {"content": [{"text": '{"damaged_parts": ["rear_bumper"]}'}]}}}
    monkeypatch.setattr(vision.boto3, "client", lambda *a, **k: Client())
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpegbytes")
    assert vision.damaged_parts(photo) == ["rear_bumper"]
    assert seen["modelId"] == vision.MODEL_ID and seen["messages"][0]["content"][0]["image"]["source"]["bytes"] == b"jpegbytes"
    assert seen["inferenceConfig"]["temperature"] == 0.0
