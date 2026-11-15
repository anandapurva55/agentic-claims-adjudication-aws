"""Every test gets its own audit log and metrics, so tests never create fake pending work in the real runtime store."""
import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_dir", tmp_path / "runtime")
    monkeypatch.setattr(settings, "replay_pace", 0)
