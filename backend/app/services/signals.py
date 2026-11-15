"""Advisory risk signals from the claims operations and policy records servers.

Replay mode calls the server functions in process. In live mode the Investigator agent reaches the same functions over MCP
and records signals itself. Signals inform the human adjuster. They never change the decision by themselves.
"""
from __future__ import annotations

from app.mcp_servers import claims_ops, policy_records

ESTIMATE_PART = {"Front bumper": "front_bumper", "Bonnet": "hood", "Left front door panel": "door", "Headlamp assembly": "headlamp", "Rear bumper": "rear_bumper"}


def photo_signals(ex: dict) -> list[dict]:
    """Compare the parts Bedrock Data Automation sees damaged in the photo with the parts on the repair estimate.

    Only the five parts the photo blueprint can name are compared. Advisory: a photo shows one angle, so a mismatch is a question for a person.
    """
    photo = ex.get("photo")
    if not photo:
        return []
    listed = {ESTIMATE_PART[ln["name"]] for ln in ex["lines"] if ln["name"] in ESTIMATE_PART}
    seen = set(photo.get("parts") or [])
    out = []
    if seen - listed:
        out.append({"kind": "photo_vs_estimate", "severity": "medium",
                    "detail": f"The photo shows damage to {', '.join(sorted(seen - listed)).replace('_', ' ')}, which is not on the repair estimate."})
    if listed - seen:
        out.append({"kind": "photo_vs_estimate", "severity": "low",
                    "detail": f"The estimate lists {', '.join(sorted(listed - seen)).replace('_', ' ')}, which the photo does not clearly show (one angle may miss it)."})
    return out


def extraction_signals(ex: dict) -> list[dict]:
    """Two independent readers of the same form (Bedrock Data Automation and the deterministic parser) must agree. A disagreement is worth a look."""
    check = ex.get("extraction_check")
    out = []
    for m in (check or {}).get("mismatches", []):
        sev = "low" if m["field"] == "holder" else "medium"
        out.append({"kind": "extraction_check", "severity": sev,
                    "detail": f"Bedrock Data Automation read {m['field'].replace('_', ' ')} as '{m['bda']}' and the parser read '{m['parser']}'. Check the form."})
    return out


def document_signals(ex: dict) -> list[dict]:
    return extraction_signals(ex) + photo_signals(ex)


def investigate(ex: dict) -> list[dict]:
    signals: list[dict] = []
    for ln in ex["lines"]:
        b = claims_ops.benchmark_repair_cost(ln["name"], ln["cost"])
        if b.get("verdict") == "above range":
            sev = "high" if ln["cost"] > 2 * b["typical"] else "medium"
            signals.append({"kind": "repair_cost", "severity": sev,
                            "detail": f"{ln['name']} quoted at INR {ln['cost']:,}, typical range INR {b['range'][0]:,} to {b['range'][1]:,}."})
    g = claims_ops.check_garage(ex.get("garage", ""))
    if g.get("known") and g["flagged_estimates_last_year"] >= 3:
        signals.append({"kind": "garage", "severity": "high",
                        "detail": f"{g['garage']} had {g['flagged_estimates_last_year']} flagged estimates last year (rating {g['rating']})."})
    elif g.get("known") and not g["network"]:
        signals.append({"kind": "garage", "severity": "low", "detail": f"{g['garage']} is outside the preferred network."})
    h = policy_records.get_claim_history(ex["policy_no"], ex["claim_id"])
    if h["nearest_other_claim_days"] is not None and h["nearest_other_claim_days"] <= 5:
        sev = "high" if h["nearest_other_claim_days"] <= 2 else "medium"
        signals.append({"kind": "repeat_claim", "severity": sev,
                        "detail": f"Another claim on this policy was filed {'on the same day' if h['nearest_other_claim_days'] == 0 else str(h['nearest_other_claim_days']) + ' days away'} ({h['count']} other claims on file)."})
    signals += document_signals(ex)
    fir = claims_ops.verify_police_fir(ex["claim_id"])
    if fir["status"] == "missing":
        signals.append({"kind": "police_fir", "severity": "medium", "detail": "No police FIR is recorded for this claim."})
    return signals
