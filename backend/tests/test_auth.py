"""Sign-in. With a user pool configured every endpoint except the health check needs a valid Amazon Cognito ID token, and the reviewer's name and role come from
that token. These tests sign real RS256 tokens with a throwaway key and check each way a token can be wrong."""
import json
import time

import jwt
import pytest
from app import auth
from app.api.main import app
from app.config import settings
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

POOL, CLIENT, REGION = "us-east-1_TESTPOOL", "test-client-id", "us-east-1"
ISS = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"
CASES = json.load(open("evals/golden/cases.json"))
HIGH = next(c["claim_id"] for c in CASES if c["scenario"] == "high_value")
CLEAN = next(c["claim_id"] for c in CASES if c["scenario"] == "clean")

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
client = TestClient(app)


@pytest.fixture(autouse=True)
def signed_in_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    monkeypatch.setattr(settings, "region", REGION)
    monkeypatch.setattr(settings, "cognito_user_pool_id", POOL)
    monkeypatch.setattr(settings, "cognito_client_id", CLIENT)
    monkeypatch.setattr(auth, "_signing_key", lambda token: KEY.public_key())  # stands in for the pool's published key set


def token(groups=("adjuster",), name="asha", key=KEY, alg="RS256", **override) -> str:
    now = int(time.time())
    claims = {"sub": "u-1", "iss": ISS, "aud": CLIENT, "token_use": "id", "iat": now, "exp": now + 3600, "cognito:username": name,
              "cognito:groups": list(groups), **override}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg)


def bearer(**kw) -> dict:
    return {"Authorization": f"Bearer {token(**kw)}"}


def test_the_health_check_needs_no_token_because_the_load_balancer_sends_none():
    assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize("path", ["/api/claims", "/api/topology", "/api/metrics", "/api/review-stats", "/api/security/attacks", "/api/security/report"])
def test_every_read_endpoint_refuses_a_caller_with_no_token(path):
    r = client.get(path)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_run_review_and_scan_refuse_a_caller_with_no_token():
    assert client.post(f"/api/claims/{CLEAN}/run?mode=replay").status_code == 401
    assert client.post(f"/api/claims/{CLEAN}/review", json={"action": "accept"}).status_code == 401
    assert client.post("/api/security/scan", json={"text": "hello"}).status_code == 401


def test_a_valid_token_is_accepted():
    assert client.get("/api/claims", headers=bearer()).status_code == 200


@pytest.mark.parametrize("why,kw", [
    ("expired", {"exp": int(time.time()) - 10, "iat": int(time.time()) - 3600}),
    ("another client's token", {"aud": "someone-elses-client"}),
    ("another user pool", {"iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OTHER"}),
    ("an access token, not an ID token", {"token_use": "access"}),
    ("signed with a different key", {"key": OTHER_KEY}),
    ("no expiry", {"exp": None}),
    ("no audience", {"aud": None})])
def test_a_token_that_is_wrong_in_any_way_is_refused(why, kw):
    assert client.get("/api/claims", headers=bearer(**kw)).status_code == 401, why


def test_an_unsigned_token_and_garbage_are_refused():
    unsigned = jwt.encode({"sub": "x", "iss": ISS, "aud": CLIENT, "token_use": "id", "exp": int(time.time()) + 60, "cognito:groups": ["senior"]}, key=None,
                          algorithm="none")
    for value in (f"Bearer {unsigned}", "Bearer not.a.token", "Bearer ", "Basic dXNlcjpwYXNz", "garbage"):
        assert client.get("/api/claims", headers={"Authorization": value}).status_code == 401, value


def test_when_the_key_set_cannot_be_fetched_the_caller_is_refused_not_let_in(monkeypatch):
    def down(_token):
        raise OSError("cognito unreachable")
    monkeypatch.setattr(auth, "_signing_key", down)
    assert client.get("/api/claims", headers=bearer()).status_code == 401


def test_a_user_in_no_group_is_signed_in_but_not_allowed():
    assert client.get("/api/claims", headers=bearer(groups=())).status_code == 403
    assert client.get("/api/claims", headers=bearer(groups=("visitors",))).status_code == 403


def test_the_role_comes_from_the_token_and_the_body_cannot_change_it():
    h = bearer(groups=("adjuster",))
    client.post(f"/api/claims/{HIGH}/run?mode=replay", headers=h).read()
    # an adjuster who writes "senior" into the JSON is still an adjuster: above the authority limit they cannot approve
    rid = client.get(f"/api/claims/{HIGH}", headers=h).json()["ai"]["run_id"]
    r = client.post(f"/api/claims/{HIGH}/review", json={"run_id": rid, "action": "accept", "role": "senior", "reviewer": "CEO"}, headers=h)
    assert r.status_code == 403
    assert client.post(f"/api/claims/{HIGH}/review", json={"run_id": rid, "action": "escalate"}, headers=h).status_code == 200


def test_a_senior_in_the_token_can_approve_above_the_limit_and_is_recorded_by_name():
    h = bearer(groups=("senior",), name="priya.rao")
    client.post(f"/api/claims/{HIGH}/run?mode=replay", headers=h).read()
    rid = client.get(f"/api/claims/{HIGH}", headers=h).json()["ai"]["run_id"]
    assert client.post(f"/api/claims/{HIGH}/review", json={"run_id": rid, "action": "accept"}, headers=h).status_code == 200
    review = client.get(f"/api/claims/{HIGH}", headers=h).json()["review"]
    assert (review["reviewer"], review["role"]) == ("priya.rao", "senior")


def test_senior_wins_when_a_user_is_in_both_groups():
    assert auth.verify(token(groups=("adjuster", "senior"))).role == "senior"


def test_the_file_endpoint_accepts_a_cookie_but_nothing_that_changes_state_does():
    t = token()
    f = f"/api/claims/{CLEAN}/files/claim_form.pdf"
    assert client.get(f, headers={"Cookie": f"claims_token={t}"}).status_code == 200  # an <img> or <a> cannot send a header
    assert client.get(f).status_code == 401
    assert client.post(f"/api/claims/{CLEAN}/run?mode=replay", headers={"Cookie": f"claims_token={t}"}).status_code == 401
    assert client.post(f"/api/claims/{CLEAN}/review", json={"action": "accept"}, headers={"Cookie": f"claims_token={t}"}).status_code == 401
    assert client.get("/api/claims", headers={"Cookie": f"claims_token={t}"}).status_code == 401  # the cookie works for files only


def test_a_name_in_the_token_is_cleaned_before_it_is_stored():
    assert auth.verify(token(name="<b>asha</b>\n" + "x" * 100)).username.startswith("basha")
    assert len(auth.verify(token(name="x" * 100)).username) == 60


# ---- live mode and local development ---------------------------------------------------------------------------------------------------------------

def test_live_mode_refuses_to_start_without_sign_in(monkeypatch):
    monkeypatch.setattr(settings, "mode", "live")
    monkeypatch.setattr(settings, "cognito_user_pool_id", "")
    with pytest.raises(RuntimeError, match="live mode needs sign-in"):
        auth.check_startup()
    monkeypatch.setattr(settings, "cognito_user_pool_id", POOL)
    auth.check_startup()  # configured: fine
    monkeypatch.setattr(settings, "mode", "replay")
    monkeypatch.setattr(settings, "cognito_user_pool_id", "")
    auth.check_startup()  # replay needs nothing


def test_local_development_without_a_pool_uses_the_demo_headers(monkeypatch):
    monkeypatch.setattr(settings, "cognito_user_pool_id", "")
    assert client.get("/api/claims").status_code == 200


def test_cors_allows_only_the_listed_origins_and_methods():
    ok = client.options("/api/claims", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/claims", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
    assert "DELETE" not in ok.headers.get("access-control-allow-methods", "")
