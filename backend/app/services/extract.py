"""Claim packet extraction.

LocalPdfExtractor reads the generated claim form and repair estimate with pypdf. It needs no cloud, so it serves development, CI and offline replay, and at run
time it is the reader the rules engine uses for form fields. Amazon Bedrock Data Automation (services/bda.py) reads the same forms independently at ingestion.
services/data.py compares the two readers, and a disagreement becomes an advisory signal (services/signals.py).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.CRITICAL)

FORM_LABELS = {
    "Claim ID": "claim_id", "Policy number": "policy_no", "Policy holder": "holder", "Registration": "vehicle_reg",
    "Date of incident": "incident_date", "Date reported": "report_date", "Police FIR filed": "police_fir_raw",
    "Claimed amount (INR)": "claimed_amount",
}


def _lines(path: Path) -> list[str]:
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _num(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s))


class LocalPdfExtractor:
    name = "local-pdf"

    def extract(self, folder: Path) -> dict:
        form = _lines(folder / "claim_form.pdf")
        out: dict = {}
        for i, line in enumerate(form):
            if line in FORM_LABELS and i + 1 < len(form):
                out[FORM_LABELS[line]] = form[i + 1]
        if "Description of incident" in form:
            out["narrative"] = " ".join(form[form.index("Description of incident") + 1:])
        out["claimed_amount"] = _num(out["claimed_amount"])
        raw = out.pop("police_fir_raw", "Not applicable")
        out["police_fir"] = True if raw == "Yes" else False if raw == "No" else None

        est = _lines(folder / "repair_estimate.pdf")
        reg = re.search(r"registration ([A-Z0-9]+)\.", " ".join(est))
        out["estimate_reg"] = reg.group(1) if reg else ""
        garage = re.search(r"Garage: ([^,.]+)", " ".join(est))
        out["garage"] = garage.group(1).strip() if garage else ""
        body = est[est.index("Cost (INR)") + 1:]
        lines, labour, total, salvage, i = [], 0, 0, 0, 0
        while i < len(body):
            name = body[i]
            if name == "Labour and paint":
                labour = _num(body[i + 1])
                i += 2
            elif name == "TOTAL":
                total = _num(body[i + 1])
                i += 2
            elif name.startswith("Assessed salvage"):
                salvage = _num(body[i + 1])
                i += 2
            else:
                lines.append({"name": name, "category": body[i + 1], "cost": _num(body[i + 2])})
                i += 3
        out.update(lines=lines, labour=labour, estimate_total=total, salvage=salvage)
        return out
