"""Retrieval evaluation for the policy Knowledge Bases.

Usage: python evals/retrieval/run.py

For each of 48 natural language questions (4 per policy clause) it retrieves the top 5 passages from each Knowledge Base variant and
checks whether a correct passage was returned.

A passage is correct for the raw PDF chunks when it contains the clause's identifying wording (a regex over real policy text,
accepting any of the three insurers). For clause cards, which carry the clause id as metadata, it is correct only when the id is exact.
Metrics: recall@1, recall@3, recall@5 and MRR@5. The questions were written by the project author: see the README.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

HERE = Path(__file__).parent
REPORTS = HERE.parent / "reports"
REGION = "us-east-1"
QUERIES = json.loads((HERE / "queries.json").read_text())
K = 5


def outputs() -> dict[str, str]:
    cf = boto3.client("cloudformation", region_name=REGION)
    out = cf.describe_stacks(StackName="ClaimsAdjudicationData")["Stacks"][0]["Outputs"]
    return {o["OutputKey"]: o["OutputValue"] for o in out}


def variants(o: dict[str, str]) -> dict[str, str]:
    v = {"c300 (baseline)": o["KnowledgeBaseId"]}
    for key, label in (("c150", "c150"), ("c800", "c800"), ("cards", "c300 + clause cards")):
        if f"Retrieval{key}KbId" in o:
            v[label] = o[f"Retrieval{key}KbId"]
    return v


def retrieve(client, kb: str, question: str, search_type: str | None = None) -> list[dict]:
    cfg: dict = {"vectorSearchConfiguration": {"numberOfResults": K}}
    if search_type:
        cfg["vectorSearchConfiguration"]["overrideSearchType"] = search_type
    for attempt in range(6):
        try:
            r = client.retrieve(knowledgeBaseId=kb, retrievalQuery={"text": question}, retrievalConfiguration=cfg)
            return r["retrievalResults"]
        except ClientError as e:
            if e.response["Error"]["Code"] in ("ThrottlingException", "TooManyRequestsException") and attempt < 5:
                time.sleep(2 ** attempt)
                continue
            raise
    return []


def first_hit(results: list[dict], q: dict, has_cards: bool) -> int | None:
    for rank, r in enumerate(results, 1):
        text = r["content"]["text"]
        meta = r.get("metadata", {}) or {}
        if "clause_id" in meta:  # a clause card: correct only when the id is exact
            if meta["clause_id"] == q["clause"]:
                return rank
        elif re.search(q["gold"], text, re.I | re.S):
            return rank
    return None


def score(ranks: list[int | None]) -> dict:
    n = len(ranks)
    r = lambda k: sum(1 for x in ranks if x is not None and x <= k) / n  # noqa: E731
    return {"recall@1": round(r(1), 3), "recall@3": round(r(3), 3), "recall@5": round(r(5), 3),
            "mrr@5": round(sum(1 / x for x in ranks if x) / n, 3)}


def main() -> None:
    o = outputs()
    client = boto3.client("bedrock-agent-runtime", region_name=REGION)
    report: dict = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "questions": sum(len(q["questions"]) for q in QUERIES), "variants": {}}
    for label, kb in variants(o).items():
        has_cards = "cards" in label
        ranks, misses, by_clause = [], [], {}
        for q in QUERIES:
            cr = []
            for question in q["questions"]:
                results = retrieve(client, kb, question)
                rk = first_hit(results, q, has_cards)
                ranks.append(rk)
                cr.append(rk)
                if rk is None:
                    misses.append({"clause": q["clause"], "question": question})
                time.sleep(0.25)
            by_clause[q["clause"]] = score(cr)["recall@5"]
        report["variants"][label] = {"kb": kb, **score(ranks), "by_clause_recall@5": by_clause, "misses": misses}
        print(f"{label:24} " + "  ".join(f"{k}={v}" for k, v in score(ranks).items()) + f"   ({len(misses)} questions with no correct passage)")
    # Does this store support hybrid (keyword plus vector) search? Report honestly either way.
    try:
        retrieve(client, report["variants"]["c300 (baseline)"]["kb"], "intoxicating liquor", "HYBRID")
        report["hybrid_search"] = "supported"
    except ClientError as e:
        report["hybrid_search"] = f"not supported on S3 Vectors: {e.response['Error']['Message'][:120]}"
    print("hybrid search:", report["hybrid_search"])
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "retrieval.json").write_text(json.dumps(report, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
