"""MCP server: policy wording and policy records.

A stand-in for the systems of record an insurer already runs (policy admin, claims history). Agents reach them only
through MCP, so each capability is separately testable, versioned and replaceable. Stateless by design.
Run standalone:  python -m app.mcp_servers.policy_records
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.services import data, policy_search

mcp = MCPServer("claims-adjudication-policy-records")


@lru_cache
def _claims_index() -> tuple[tuple[str, str, str, int], ...]:
    """(claim_id, policy_no, incident_date, claimed_amount) for every claim, built once. A real server would query a database."""
    rows = []
    for cid in data.list_claim_ids():
        ex = data.extract_claim(cid)
        rows.append((cid, ex["policy_no"], ex["incident_date"], ex["claimed_amount"]))
    return tuple(rows)


@mcp.tool()
def search_policy_wording(query: str, k: int = 3) -> list[dict]:
    """Search the motor policy wording for clauses relevant to a question. Always cite the clause id returned.

    Args:
        query: What you want to know, for example "exclusion for driving under the influence".
        k: How many passages to return (1 to 5).
    """
    return policy_search.search(query, max(1, min(k, 5)))


@mcp.tool()
def get_policy_schedule(policy_no: str) -> dict:
    """Return the policy schedule: IDV, deductible, vehicle, registration year and period of insurance.

    Args:
        policy_no: The policy number, for example MGI-MOT-1001.
    """
    pol = data.policies().get(policy_no)
    if not pol:
        return {"error": f"unknown policy {policy_no}"}
    return {k: pol[k] for k in ("policy_no", "holder", "vehicle_reg", "make", "model", "reg_year", "idv", "deductible", "use", "start", "end")}


@mcp.tool()
def get_claim_history(policy_no: str, exclude_claim_id: str = "") -> dict:
    """Return the other claims on this policy, newest first. Repeat claims in a short period are a fraud signal.

    Args:
        policy_no: The policy number.
        exclude_claim_id: The claim currently being assessed, which is left out of the history.
    """
    prior: list[dict[str, Any]] = [{"claim_id": cid, "incident_date": d, "claimed_amount": amt}
             for cid, pol, d, amt in _claims_index() if pol == policy_no and cid != exclude_claim_id]
    prior.sort(key=lambda r: r["incident_date"], reverse=True)
    days = None
    current = next((d for cid, _, d, _ in _claims_index() if cid == exclude_claim_id), None)
    if prior and current:
        days = min(abs((date.fromisoformat(current) - date.fromisoformat(p["incident_date"])).days) for p in prior)
    return {"policy_no": policy_no, "prior_claims": prior[:5], "count": len(prior), "nearest_other_claim_days": days}


if __name__ == "__main__":
    mcp.run()
