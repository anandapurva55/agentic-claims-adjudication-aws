"""Memory recall must never send an empty query to the service: the red team control runs once did, and crashed."""
from app import memory


def test_empty_query_returns_nothing_without_calling_the_service(monkeypatch):
    monkeypatch.setattr(memory, "_live", lambda: (_ for _ in ()).throw(AssertionError("must not reach the service")))
    assert memory.recall("") == []
    assert memory.recall("   ") == []
