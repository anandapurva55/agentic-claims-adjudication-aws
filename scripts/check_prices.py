"""Check backend/app/pricing.py against the AWS Price List API, the primary source for what Bedrock charges.

  python scripts/check_prices.py

Needs AWS credentials with pricing:GetProducts (the Price List API is read-only and free). Prints each rate next to AWS's, and exits 1 if any differ.
Prices are the global inference profile rates in us-east-1, because the code calls the "global." model ids.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.pricing import PRICES  # noqa: E402

# model id -> (service code, model name in the price list, {rate: (usage type, unit multiplier to reach USD per million tokens)})
SOURCES = {
    "global.amazon.nova-2-lite-v1:0": ("AmazonBedrock", "Nova 2.0 Lite", {
        "in": ("USE1-Nova2.0Lite-input-tokens-cross-region-global", 1000), "out": ("USE1-Nova2.0Lite-output-tokens-cross-region-global", 1000),
        "cache_read": ("USE1-Nova2.0Lite-cache-read-input-token-count-cross-region-global", 1000),
        "cache_write": ("USE1-Nova2.0Lite-cache-write-input-token-count-cross-region-global", 1000)}),
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": ("AmazonBedrockFoundationModels", "Claude Haiku 4.5", {
        "in": ("USE1-MP:USE1_InputTokenCount_Global-Units", 1), "out": ("USE1-MP:USE1_OutputTokenCount_Global-Units", 1),
        "cache_read": ("USE1-MP:USE1_CacheReadInputTokenCount_Global-Units", 1), "cache_write": ("USE1-MP:USE1_CacheWriteInputTokenCount_Global-Units", 1)}),
    "global.anthropic.claude-sonnet-4-6": ("AmazonBedrockFoundationModels", "Claude Sonnet 4.6", {
        "in": ("USE1-MP:USE1_InputTokenCount_Global-Units", 1), "out": ("USE1-MP:USE1_OutputTokenCount_Global-Units", 1),
        "cache_read": ("USE1-MP:USE1_CacheReadInputTokenCount_Global-Units", 1), "cache_write": ("USE1-MP:USE1_CacheWriteInputTokenCount_Global-Units", 1)}),
}


def usage_prices(client, service: str, model: str) -> dict[str, float]:
    found: dict[str, float] = {}
    token = None
    while True:
        kw = {"ServiceCode": service, "MaxResults": 100, "Filters": [{"Type": "TERM_MATCH", "Field": "model", "Value": model},
                                                                      {"Type": "TERM_MATCH", "Field": "regionCode", "Value": "us-east-1"}]}
        if token:
            kw["NextToken"] = token
        page = client.get_products(**kw)
        for item in page["PriceList"]:
            doc = json.loads(item)
            for term in doc["terms"].get("OnDemand", {}).values():
                for dim in term["priceDimensions"].values():
                    found[doc["product"]["attributes"].get("usagetype", "")] = float(dim["pricePerUnit"]["USD"])
        token = page.get("NextToken")
        if not token:
            return found


def main() -> int:
    client = boto3.client("pricing", region_name="us-east-1")  # the Price List API lives in us-east-1
    bad = 0
    for model, (service, name, rates) in SOURCES.items():
        aws = usage_prices(client, service, name)
        for rate, (usage, mult) in rates.items():
            theirs = round(aws[usage] * mult, 6) if usage in aws else None
            ours = PRICES[model][rate]
            ok = theirs is not None and abs(theirs - ours) < 1e-9
            bad += not ok
            print(f"{'ok  ' if ok else 'DIFF'} {name:18} {rate:12} ours ${ours:<8} AWS ${theirs}")
    print("\nAll prices match the AWS Price List." if not bad else f"\n{bad} price(s) differ from the AWS Price List: update backend/app/pricing.py.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
