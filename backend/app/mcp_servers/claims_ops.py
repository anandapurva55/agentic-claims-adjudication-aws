"""MCP server: claims operations (repair cost benchmarks, police FIR verification, garage reputation).

These are simulated enterprise services with fixed reference data, labelled as such in the README. The point is the
architecture: agents consume them through MCP, exactly as they would consume real internal services.
Run standalone:  python -m app.mcp_servers.claims_ops
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from app.services import data

mcp = MCPServer("claims-adjudication-claims-ops")

# Typical INR repair cost per part type with a plausible range. Reference data, not a market claim.
BENCHMARK = {
    "bumper": (9000, 6500, 13000), "bonnet": (14000, 10000, 19000), "door": (18000, 12000, 25000), "lamp": (8000, 3500, 14000),
    "windshield": (12500, 8000, 18000), "radiator": (8500, 6000, 12000), "fender": (9800, 7000, 14000), "tyre": (7000, 4500, 10000),
}
GARAGES = {
    "autocare works": {"rating": 4.1, "flagged_estimates_last_year": 0, "network": True},
    "speedfix motors": {"rating": 2.7, "flagged_estimates_last_year": 6, "network": False},
}


@mcp.tool()
def benchmark_repair_cost(part_name: str, quoted_cost: int) -> dict:
    """Compare a quoted repair cost with the typical cost range for that part. Large overruns are a fraud signal.

    Args:
        part_name: The part as written on the estimate, for example "Front bumper".
        quoted_cost: The cost quoted on the estimate, in INR.
    """
    key = next((k for k in BENCHMARK if k in part_name.lower()), None)
    if key is None:
        return {"part": part_name, "known": False, "note": "no benchmark for this part"}
    typical, low, high = BENCHMARK[key]
    return {"part": part_name, "known": True, "typical": typical, "range": [low, high], "quoted": quoted_cost,
            "verdict": "above range" if quoted_cost > high else "below range" if quoted_cost < low else "within range"}


@mcp.tool()
def verify_police_fir(claim_id: str) -> dict:
    """Check whether a police FIR is recorded for this claim. Required for theft and useful for serious accidents.

    Args:
        claim_id: The claim identifier.
    """
    fir = data.extract_claim(claim_id)["police_fir"]
    return {"claim_id": claim_id, "fir_recorded": fir, "status": "not applicable" if fir is None else "recorded" if fir else "missing"}


@mcp.tool()
def check_garage(garage_name: str) -> dict:
    """Return a garage's reputation: rating, network status and how many of its estimates were flagged last year.

    Args:
        garage_name: The garage named on the repair estimate.
    """
    g = GARAGES.get(garage_name.lower().strip())
    return {"garage": garage_name, **(g or {"rating": None, "flagged_estimates_last_year": None, "network": None}), "known": g is not None}


if __name__ == "__main__":
    mcp.run()
