"""Model prices and cost of one call. USD per million tokens.

Prices are the on-demand rates for the global Bedrock inference profiles in us-east-1, read from the AWS Price List API (scripts/check_prices.py reads them again
and compares) and last checked 16 November 2026. Cache reads and writes are priced separately by AWS. Nova 2 Lite has no cache write charge. Rates change:
rerun the script before quoting these as current.
"""
from __future__ import annotations

PRICES: dict[str, dict[str, float]] = {
    "global.amazon.nova-2-lite-v1:0": {"in": 0.30, "out": 2.50, "cache_read": 0.075, "cache_write": 0.0},
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": {"in": 1.00, "out": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "global.anthropic.claude-sonnet-4-6": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
}


def call_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    """Cost of one model call in USD. Bedrock reports cached tokens separately from inputTokens, so they are priced separately."""
    p = PRICES.get(model)
    if not p:
        return 0.0
    return (input_tokens * p["in"] + output_tokens * p["out"] + cache_read * p["cache_read"] + cache_write * p["cache_write"]) / 1e6
