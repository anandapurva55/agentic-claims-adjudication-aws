"""Builds the world the investigation cases live in: real claim PDFs (the same layout the product reads), policy schedules and a history of other claims.

The investigator's tools and the MCP servers read this folder through CLAIMS_DATA_DIR, so nothing about the product is stubbed: only the records differ.
`filler` adds that many unrelated claims on other policies, which is how the scale test grows the claims history.
"""
from __future__ import annotations

import json
import random
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from cases import CASES, INJECTION, Case  # noqa: E402
from generate_data import S, pdf  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Paragraph, Spacer, Table  # noqa: E402

INCIDENT = date(2026, 6, 15)
NARRATIVES = ["Rear ended at a traffic signal by another vehicle.", "Hit a stationary truck while reversing in a parking lot.",
              "A scooter cut across at a junction and I could not stop in time."]
THEFT_NARRATIVE = "The vehicle was parked outside my home overnight and was gone in the morning."


def policy_no(i: int) -> str:
    return f"INV-{i:05d}"


def reg_of(i: int) -> str:
    return f"KA01AB{1000 + i:04d}"


def policy(i: int, idv: int = 650000) -> dict:
    return {"policy_no": policy_no(i), "holder": f"Policy Holder {i}", "vehicle_reg": reg_of(i), "make": "Maruti Suzuki", "model": "Swift", "reg_year": 2024,
            "idv": idv, "deductible": 2000, "use": "private", "start": "2026-01-01", "end": "2026-12-31"}


def write_claim(root: Path, cid: str, pol: dict, incident: date, lines: list, labour: int, claimed: int, total: int, garage: str, narrative: str,
                fir: bool | None, form_reg: str | None = None, estimate_reg: str | None = None) -> None:
    folder = root / "claims" / cid
    gross = total
    pdf(folder / "claim_form.pdf", f"Claim {cid}", [
        Paragraph("Motor Insurance Claim Form", S["Title"]),
        Table([["Claim ID", cid], ["Policy number", pol["policy_no"]], ["Policy holder", pol["holder"]], ["Vehicle", f"{pol['make']} {pol['model']}"],
               ["Registration", form_reg or pol["vehicle_reg"]], ["Date of incident", incident.isoformat()],
               ["Date reported", (incident + timedelta(days=2)).isoformat()], ["Place", "Bengaluru"],
               ["Police FIR filed", "Yes" if fir else ("No" if fir is False else "Not applicable")], ["Claimed amount (INR)", f"{claimed:,}"]],
              colWidths=[55 * mm, 100 * mm]),
        Spacer(1, 8), Paragraph("<b>Description of incident</b>", S["Heading3"]), Paragraph(narrative, S["BodyText"])])
    rows = [["Item", "Part type", "Cost (INR)"]] + [[n, c, f"{v:,}"] for n, c, v in lines] + [["Labour and paint", "", f"{labour:,}"], ["TOTAL", "", f"{gross:,}"]]
    pdf(folder / "repair_estimate.pdf", f"Estimate {cid}", [
        Paragraph("Repair Estimate", S["Title"]),
        Paragraph(f"Garage: {garage}, Bengaluru. Vehicle registration {estimate_reg or pol['vehicle_reg']}.", S["Normal"]),
        Spacer(1, 6), Table(rows, colWidths=[85 * mm, 35 * mm, 40 * mm])])


def case_claim_id(i: int) -> str:
    return f"INVCASE-{i + 1:03d}"


def build(root: Path, filler: int = 0, seed: int = 11) -> dict[str, str]:
    """Write the world under root. Returns {case id: claim id}."""
    if root.exists():
        shutil.rmtree(root)
    (root / "claims").mkdir(parents=True)
    shutil.copy(ROOT / "data" / "rules.json", root / "rules.json")
    rng, policies, ids = random.Random(seed), [], {}
    for i, c in enumerate(CASES):
        pol = policy(i)
        policies.append(pol)
        labour = 0 if c.theft else 3000
        total = sum(v for _, _, v in c.lines) + labour
        narrative = (THEFT_NARRATIVE if c.theft else NARRATIVES[i % len(NARRATIVES)]) + (INJECTION if c.injection else "")
        cid = case_claim_id(i)
        ids[c.id] = cid
        write_claim(root, cid, pol, INCIDENT, c.lines, labour, c.claimed if c.claimed is not None else total, total, c.garage, narrative, c.fir,
                    form_reg=c.form_reg, estimate_reg=c.estimate_reg)
        for k, days in enumerate(c.history_days):  # other claims on the same policy
            write_claim(root, f"INVHIST-{i + 1:03d}-{k + 1}", pol, INCIDENT - timedelta(days=days), [("Front bumper", "plastic", 9000)], 3000, 12000, 12000,
                        "AutoCare Works", NARRATIVES[0], None)
    for j in range(filler):  # unrelated claims on other policies: the claims history grows, the answers do not change
        n = len(CASES) + j
        pol = policy(n)
        policies.append(pol)
        day = INCIDENT - timedelta(days=rng.randint(30, 400))
        write_claim(root, f"INVFILL-{j + 1:05d}", pol, day, [("Front bumper", "plastic", 9000)], 3000, 12000, 12000, "AutoCare Works", NARRATIVES[0], None)
    (root / "policies.json").write_text(json.dumps(policies))
    return ids


def case_by_id(cid: str) -> Case:
    return next(c for c in CASES if c.id == cid)
