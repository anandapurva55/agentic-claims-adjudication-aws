"""Agent memory.

Short-term memory is the team's working notes for one claim: agents post questions and answers to each other, and each note
is mirrored to Amazon Bedrock AgentCore Memory as an event so the whole conversation is durable and inspectable.

Long-term memory is lessons learned from human adjusters, kept as AgentCore semantic memory records and recalled by meaning.
In replay and CI a local JSONL file with word overlap search stands in, so nothing needs AWS.

Security: the ONLY way into long-term memory is store_lesson(), called by the human review path after a guardrail scan.
Agents have a read only recall tool and no write tool, so text in a customer's narrative can never plant a lesson.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path

from app.config import settings

log = logging.getLogger("adjudication.memory")
NAMESPACE = "/lessons/motor"
MIN_SCORE = 0.42  # measured: relevant lessons score about 0.45 to 0.48, unrelated ones about 0.36
SEED = Path(__file__).resolve().parents[2] / "data" / "lessons_seed.json"


def _live() -> bool:
    return settings.mode == "live" and bool(settings.memory_id)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


def _local_path() -> Path:
    p = Path(settings.runtime_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / "lessons.jsonl"


def _local_lessons() -> list[dict]:
    seed = json.loads(SEED.read_text()) if SEED.exists() else []
    learned = [json.loads(ln) for ln in _local_path().read_text().splitlines() if ln.strip()] if _local_path().exists() else []
    return seed + learned


@lru_cache
def _client():
    import boto3
    return boto3.client("bedrock-agentcore", region_name=settings.region)


@lru_cache
def _strategy_id() -> str:
    import boto3
    cp = boto3.client("bedrock-agentcore-control", region_name=settings.region)
    strategies = cp.get_memory(memoryId=settings.memory_id)["memory"].get("strategies", [])
    return strategies[0]["strategyId"]


def recall(query: str, k: int = 3) -> list[dict]:
    """Lessons relevant to a question, most relevant first. Read only."""
    if not settings.memory_enabled or not query.strip():
        return []
    if _live():
        r = _client().retrieve_memory_records(memoryId=settings.memory_id, namespace=NAMESPACE,
                                              searchCriteria={"searchQuery": query, "memoryStrategyId": _strategy_id(), "topK": k})
        return [{"text": m["content"]["text"], "score": round(m.get("score", 0), 3), "source": "agentcore"}
                for m in r.get("memoryRecordSummaries", []) if m.get("score", 0) >= MIN_SCORE]
    q = _tokens(query)
    scored = sorted(((len(q & _tokens(x["text"])), x) for x in _local_lessons()), key=lambda t: -t[0])
    return [{"text": x["text"], "score": float(sc), "source": x.get("source", "local")} for sc, x in scored[:k] if sc > 1]


def store_lesson(text: str, source: dict) -> bool:
    """Write a lesson. Called only from the human review path. Returns True when stored."""
    text = text.strip()
    if len(text) < 10:
        return False
    if _live():
        _client().batch_create_memory_records(
            memoryId=settings.memory_id,
            records=[{"requestIdentifier": str(uuid.uuid4()), "namespaces": [NAMESPACE], "content": {"text": text},
                      "timestamp": time.time(), "memoryStrategyId": _strategy_id()}])
        return True
    with _local_path().open("a") as f:
        f.write(json.dumps({"text": text, "source": "adjuster", "meta": source, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    return True


def log_event(session: str, actor: str, text: str) -> None:
    """Mirror a short-term note to AgentCore Memory as an event. A no-op offline."""
    if not (_live() and settings.memory_enabled):
        return
    try:
        _client().create_event(memoryId=settings.memory_id, actorId=actor, sessionId=session, eventTimestamp=time.time(),
                               payload=[{"conversational": {"content": {"text": text[:1500]}, "role": "ASSISTANT"}}])
    except Exception:  # memory is an aid. It must never fail a claim run, but it must not fail silently either
        log.warning("mirroring a note to AgentCore Memory failed", exc_info=True)
