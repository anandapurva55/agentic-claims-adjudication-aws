"""Local data access (dev, CI, replay). In AWS, DynamoDB serves the same shapes."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.rules import Facts, Line, Schedule
from app.services import stores
from app.services.extract import LocalPdfExtractor

log = logging.getLogger(__name__)


@lru_cache
def policies() -> dict[str, dict]:
    """Policy schedules: from DynamoDB when a table is configured (AWS), else the bundled file (local, CI)."""
    if settings.policies_table:
        try:
            rows = stores._scan(settings.policies_table)
            if rows:
                return {p["policy_no"]: p for p in rows}
        except Exception as exc:  # noqa: BLE001
            log.warning("policies table unreadable, using the bundled file: %s", exc)
    return {p["policy_no"]: p for p in json.loads((Path(settings.data_dir) / "policies.json").read_text())}


def schedule_for(policy_no: str) -> Schedule:
    p = policies()[policy_no]
    return Schedule(p["policy_no"], p["idv"], p["deductible"], p["reg_year"], p["start"], p["end"], p["vehicle_reg"])


def claim_dir(claim_id: str) -> Path:
    return Path(settings.data_dir) / "claims" / claim_id


def list_claim_ids() -> list[str]:
    return sorted(p.name for p in (Path(settings.data_dir) / "claims").iterdir() if p.is_dir())


def bda_result(claim_id: str) -> dict | None:
    """What Amazon Bedrock Data Automation produced for this claim at ingestion time (scripts/run_bda_ingest.py), cached beside the data."""
    if settings.claims_table:
        try:
            import boto3
            item = boto3.resource("dynamodb", region_name=settings.region).Table(settings.claims_table).get_item(Key={"claim_id": claim_id}).get("Item")
            if item and item.get("bda"):
                return json.loads(json.dumps(item["bda"], default=lambda d: int(d) if d == int(d) else float(d)))
        except Exception as exc:  # noqa: BLE001
            log.warning("claims table unreadable, using the bundled file: %s", exc)
    f = settings.data_dir / "bda" / f"{claim_id}.json"
    return json.loads(f.read_text()) if f.exists() else None


FORM_FIELDS = ("claim_id", "policy_no", "holder", "vehicle_reg", "incident_date", "report_date", "claimed_amount")


def _norm(v: object) -> str:
    return "".join(ch for ch in str(v).lower() if ch.isalnum())


def compare_form(parser: dict, bda_form: dict) -> list[dict]:
    """Fields where Amazon Bedrock Data Automation and the deterministic parser read different values from the same form."""
    return [{"field": f, "bda": bda_form.get(f), "parser": parser.get(f)} for f in FORM_FIELDS
            if f in bda_form and _norm(bda_form[f]) != _norm(parser.get(f, ""))]


def extract_claim(claim_id: str) -> dict:
    out = LocalPdfExtractor().extract(claim_dir(claim_id))
    b = bda_result(claim_id)
    out["extraction_check"] = {"engine": "bedrock-data-automation", "mismatches": compare_form(out, b["form"])} if b and b.get("form") else None
    out["photo"] = ({**b["photo"], "engine": "bedrock-data-automation + claude-haiku-4.5"} if b and b.get("photo") else None)
    return out


def facts_from(extracted: dict, flags: dict[str, bool]) -> Facts:
    return Facts(
        claim_id=extracted["claim_id"], policy_no=extracted["policy_no"], vehicle_reg=extracted["vehicle_reg"],
        estimate_reg=extracted["estimate_reg"], incident_date=extracted["incident_date"], report_date=extracted["report_date"],
        claimed_amount=extracted["claimed_amount"], estimate_total=extracted["estimate_total"],
        lines=[Line(**ln) for ln in extracted["lines"]], labour=extracted["labour"], salvage=extracted["salvage"],
        police_fir=extracted["police_fir"], **{k: flags.get(k, False) for k in (
            "intoxicated", "commercial_use", "unlicensed_driver", "mechanical_failure", "tyre_only", "theft")})
