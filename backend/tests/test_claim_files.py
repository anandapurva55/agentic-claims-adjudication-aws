"""The evidence files are served by claim id and file name, both taken from the URL. The path must only ever be made of a claim this service lists and one of three fixed file
names, so a crafted URL cannot reach any other file. These tests use a throwaway data folder with a file placed where a traversal would land."""
import pytest
from app.api.main import app
from app.config import settings
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    (tmp_path / "claims" / "CLM-1").mkdir(parents=True)
    (tmp_path / "claims" / "CLM-1" / "claim_form.pdf").write_bytes(b"the form")
    (tmp_path / "claims" / "CLM-1" / "notes.txt").write_text("not one of the three files")
    (tmp_path / "claim_form.pdf").write_bytes(b"SECRET one folder above the claims")  # where claim id ".." would land
    (tmp_path / "claims" / "claim_form.pdf").write_bytes(b"SECRET inside the claims folder, not in a claim")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "cognito_user_pool_id", "")
    return tmp_path


def test_a_listed_claim_and_a_known_file_name_are_served(data_dir):
    r = client.get("/api/claims/CLM-1/files/claim_form.pdf")
    assert r.status_code == 200 and r.content == b"the form"


@pytest.mark.parametrize("claim_id", ["CLM-2", "clm-1", "CLM-1%20", "claims", "%2e%2e", "%2e"])
def test_a_claim_id_that_is_not_listed_never_reaches_the_disk(data_dir, claim_id):
    r = client.get(f"/api/claims/{claim_id}/files/claim_form.pdf")
    assert r.status_code == 404
    assert b"SECRET" not in r.content


@pytest.mark.parametrize("name", ["notes.txt", "claim_form.pdf.bak", "CLAIM_FORM.PDF", "claim_form.pdf%20", "damage_photo.jpg.", "claims", "%2e%2e", "%2e"])
def test_a_file_name_that_is_not_one_of_the_three_is_refused(data_dir, name):
    assert client.get(f"/api/claims/CLM-1/files/{name}").status_code == 404


@pytest.mark.parametrize("path", ["/api/claims/CLM-1/files/..%2F..%2Fclaim_form.pdf", "/api/claims/..%2Fclaims/files/claim_form.pdf", "/api/claims/CLM-1/files/%2e%2e",
                                  "/api/claims/%2e%2e/files/claim_form.pdf", "/api/claims/CLM-1/files/claim_form.pdf/../../claim_form.pdf"])
def test_encoded_and_nested_traversal_never_returns_another_file(data_dir, path):
    r = client.get(path)
    assert r.status_code == 404 and b"SECRET" not in r.content
