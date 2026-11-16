"""One place that records every model call: agent, model, tokens, cache use, latency, cost and error.

The metering happens inside the model class. Bedrock's stream ends each call with a metadata event holding that call's exact
usage and latency, so nothing is estimated or subtracted from running totals. Records go to the store, which writes local JSONL,
DynamoDB and S3 as configured.
"""
from __future__ import annotations

import logging
import time
import uuid

from strands.models import BedrockModel

from app import pricing
from app.runstate import state
from app.services import stores

log = logging.getLogger("adjudication.telemetry")


def log_call(agent: str, model_id: str, usage: dict, latency_ms: int, wall_ms: int, error: str = "") -> dict:
    i, o = usage.get("inputTokens", 0), usage.get("outputTokens", 0)
    cr, cw = usage.get("cacheReadInputTokens", 0), usage.get("cacheWriteInputTokens", 0)
    s = state()
    row = {"call_id": uuid.uuid4().hex[:12], "run_id": s.run_id, "claim_id": s.claim_id, "agent": agent, "model": model_id,
           "input_tokens": i, "output_tokens": o, "cache_read": cr, "cache_write": cw, "latency_ms": latency_ms or wall_ms,
           "wall_ms": wall_ms, "cost_usd": round(pricing.call_cost(model_id, i, o, cr, cw), 6), "error": error, "variant": s.variant}
    s.calls.append(row)
    stores.record_call(row)
    return row


class MeteredBedrockModel(BedrockModel):
    """A BedrockModel that logs every call it makes. One instance per agent, so each call is attributed to the right agent."""

    def __init__(self, *args, agent_name: str = "", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._agent_name = agent_name

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        t0 = time.perf_counter()
        usage: dict = {}
        latency = 0
        error = ""
        try:
            async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
                md = event.get("metadata") if isinstance(event, dict) else None
                if md:
                    usage = md.get("usage", usage)
                    latency = md.get("metrics", {}).get("latencyMs", latency)
                yield event
        except Exception as exc:
            error = str(exc)[:200]
            raise
        finally:
            try:
                log_call(self._agent_name, self.config.get("model_id", ""), usage, int(latency), round((time.perf_counter() - t0) * 1000), error)
            except Exception:  # telemetry must never break a claim, but a lost record is worth a warning
                log.warning("recording a model call failed", exc_info=True)
