"""The MCP servers are exercised over a real stdio MCP connection, exactly as the agents use them."""
import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PARAMS = lambda module: StdioServerParameters(command=sys.executable, args=["-m", module], env={"PYTHONPATH": "backend", "CLAIMS_MODE": "replay"})  # noqa: E731


async def call(module: str, tool: str, args: dict):
    async with stdio_client(PARAMS(module)) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        res = await s.call_tool(tool, args)
        if res.structured_content is not None:  # list results are wrapped as {"result": [...]}
            sc = res.structured_content
            return sc["result"] if set(sc) == {"result"} else sc
        parsed = [json.loads(c.text) for c in res.content]
        return parsed[0] if len(parsed) == 1 else parsed


async def names(module: str) -> set[str]:
    async with stdio_client(PARAMS(module)) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        return {t.name for t in (await s.list_tools()).tools}


@pytest.mark.asyncio
async def test_servers_advertise_their_tools():
    assert await names("app.mcp_servers.policy_records") == {"search_policy_wording", "get_policy_schedule", "get_claim_history"}
    assert await names("app.mcp_servers.claims_ops") == {"benchmark_repair_cost", "verify_police_fir", "check_garage"}


@pytest.mark.asyncio
async def test_policy_search_returns_cited_clauses():
    hits = await call("app.mcp_servers.policy_records", "search_policy_wording", {"query": "driver under the influence of intoxicating liquor"})
    assert any(h["clause"] == "SEC1.EXCL.1c" for h in hits)


@pytest.mark.asyncio
async def test_schedule_and_unknown_policy():
    ok = await call("app.mcp_servers.policy_records", "get_policy_schedule", {"policy_no": "MGI-MOT-1001"})
    assert ok["deductible"] in (1000, 2000) and ok["idv"] > 0
    assert "error" in await call("app.mcp_servers.policy_records", "get_policy_schedule", {"policy_no": "NOPE"})


@pytest.mark.asyncio
async def test_repair_cost_benchmark_flags_inflated_quotes():
    inflated = await call("app.mcp_servers.claims_ops", "benchmark_repair_cost", {"part_name": "Front bumper", "quoted_cost": 40000})
    assert inflated["verdict"] == "above range"
    normal = await call("app.mcp_servers.claims_ops", "benchmark_repair_cost", {"part_name": "Front bumper", "quoted_cost": 9500})
    assert normal["verdict"] == "within range"


@pytest.mark.asyncio
async def test_garage_reputation():
    assert (await call("app.mcp_servers.claims_ops", "check_garage", {"garage_name": "SpeedFix Motors"}))["flagged_estimates_last_year"] == 6
    assert (await call("app.mcp_servers.claims_ops", "check_garage", {"garage_name": "Nobody"}))["known"] is False


def test_an_unreachable_knowledge_base_returns_no_clauses_instead_of_failing(monkeypatch):
    from app.config import settings
    from app.services import policy_search
    monkeypatch.setattr(settings, "mode", "live")
    monkeypatch.setattr(settings, "knowledge_base_id", "KB123")
    monkeypatch.setattr(policy_search, "kb_search", lambda q, k=3: (_ for _ in ()).throw(RuntimeError("bedrock down")))
    assert policy_search.search("is drunk driving covered") == []
