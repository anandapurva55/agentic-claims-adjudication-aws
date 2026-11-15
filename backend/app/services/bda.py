"""Amazon Bedrock Data Automation client: turns a claim form PDF or a damage photo into structured fields.

BDA is asynchronous. A file is uploaded to S3, a job is started against the project, and the result is read back from S3. The project holds two
custom blueprints (claim form, vehicle damage photo), so one call returns both the standard output (text, summary) and the blueprint fields.
In production this runs when a document is uploaded, not when an adjuster opens a claim, so results are cached next to the claim
(`data/bda/<claim>.json`) and the agent run reads the cache.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import boto3

from app.config import settings

PARTS = {"headlamp", "front_bumper", "rear_bumper", "hood", "door"}


class BdaClient:
    def __init__(self, bucket: str | None = None, project_arn: str | None = None) -> None:
        self.bucket = bucket or settings.claims_bucket
        self.project = project_arn or settings.bda_project_arn
        self.s3 = boto3.client("s3", region_name=settings.region)
        self.runtime = boto3.client("bedrock-data-automation-runtime", region_name=settings.region)
        account = boto3.client("sts", region_name=settings.region).get_caller_identity()["Account"]
        self.profile = f"arn:aws:bedrock:{settings.region}:{account}:data-automation-profile/us.data-automation-v1"

    def process(self, path: Path, key_prefix: str, timeout: int = 600) -> dict:
        """Upload one file, run BDA on it, return {"custom": {...blueprint fields...}, "standard": {...}, "blueprint": name, "seconds": n}."""
        t0 = time.time()
        src = f"bda/input/{key_prefix}/{path.name}"
        self.s3.upload_file(str(path), self.bucket, src)
        out = f"s3://{self.bucket}/bda/output/{key_prefix}/{path.stem}"
        job = self.runtime.invoke_data_automation_async(
            inputConfiguration={"s3Uri": f"s3://{self.bucket}/{src}"}, outputConfiguration={"s3Uri": out},
            dataAutomationConfiguration={"dataAutomationProjectArn": self.project, "stage": "LIVE"}, dataAutomationProfileArn=self.profile)
        arn = job["invocationArn"]
        while True:
            st = self.runtime.get_data_automation_status(invocationArn=arn)
            if st["status"] in ("Success", "ServiceError", "ClientError"):
                break
            if time.time() - t0 > timeout:
                raise TimeoutError(f"BDA job {arn} still running after {timeout}s")
            time.sleep(3)
        if st["status"] != "Success":
            raise RuntimeError(f"BDA {st['status']}: {st.get('errorMessage')}")
        meta = json.loads(self._read(st["outputConfiguration"]["s3Uri"]))
        result: dict = {"custom": {}, "standard": {}, "blueprint": None, "seconds": round(time.time() - t0, 1)}
        for seg in meta["output_metadata"][0]["segment_metadata"]:
            if seg.get("custom_output_path"):
                c = json.loads(self._read(seg["custom_output_path"]))
                result["custom"], result["blueprint"] = c.get("inference_result", {}), (c.get("matched_blueprint") or {}).get("name")
            if seg.get("standard_output_path"):
                result["standard"] = json.loads(self._read(seg["standard_output_path"]))
        return result

    def _read(self, uri: str) -> bytes:
        bucket, key = uri.removeprefix("s3://").split("/", 1)
        return self.s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def photo_parts(result: dict) -> list[str]:
    """Normalise the blueprint's damaged_parts to the five known words."""
    raw = result.get("custom", {}).get("damaged_parts") or []
    return sorted({str(p).strip().lower().replace(" ", "_") for p in raw} & PARTS)
