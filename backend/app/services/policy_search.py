"""Policy wording retrieval. Bedrock Knowledge Base in AWS, lexical search over the clause registry locally."""
from __future__ import annotations

import logging
import re

from app.config import settings
from app.rules import load_rules

log = logging.getLogger(__name__)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


def local_search(query: str, k: int = 3) -> list[dict]:
    q = _tokens(query)
    scored = []
    for cid, r in load_rules().items():
        overlap = len(q & _tokens(r["quote"] + " " + cid))
        scored.append((overlap, {"clause": cid, "source": r["source"], "text": r["quote"], "score": overlap}))
    scored.sort(key=lambda x: -x[0])
    return [r for s, r in scored[:k] if s > 0]


def kb_search(query: str, k: int = 3) -> list[dict]:
    import boto3
    client = boto3.client("bedrock-agent-runtime", region_name=settings.region)
    resp = client.retrieve(knowledgeBaseId=settings.knowledge_base_id, retrievalQuery={"text": query},
                           retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": k}})
    # Clause cards carry their clause id as metadata, so a retrieved card is already a citation. Raw chunks have no id.
    return [{"clause": (r.get("metadata") or {}).get("clause_id", "policy wording"),
             "source": r.get("location", {}).get("s3Location", {}).get("uri", "policy wording"),
             "text": r["content"]["text"], "score": round(r.get("score", 0), 3)} for r in resp["retrievalResults"]]


def search(query: str, k: int = 3) -> list[dict]:
    """Retrieval failures degrade the explanation, not the decision: the engine owns the outcome, so an unreachable knowledge base returns no clauses."""
    if settings.mode == "live" and settings.knowledge_base_id:
        try:
            return kb_search(query, k)
        except Exception as exc:  # noqa: BLE001
            log.warning("knowledge base retrieval failed, returning no clauses: %s", exc)
            return []
    return local_search(query, k)
