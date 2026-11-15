"""Structure of the live agent team: topology, least privilege tools, memory safety, and that MCP servers really connect."""
from app.agents.graph import build_team
from app.topology import topology


def _team():
    return build_team()


def test_first_pass_graph_shape():
    edges = {(e.from_node.node_id, e.to_node.node_id) for e in _team().graph.edges}
    assert edges == {("intake", "policy"), ("intake", "fraud")}


def test_each_agent_has_only_the_tools_it_needs():
    t = _team()
    tools = {n: set(a.tool_names) for n, a in t.agents.items()}
    talk = {"read_notes", "post_note"}
    assert tools["intake"] == {"get_claim_packet", "record_judgement", "recall_lessons"} | talk
    assert tools["policy"] == {"get_claim_packet", "calculate_payable", "search_policy_wording", "get_policy_schedule"} | talk
    assert tools["fraud"] == {"get_claim_packet", "check_consistency", "record_risk_signal", "recall_lessons", "get_claim_history",
                              "benchmark_repair_cost", "verify_police_fir", "check_garage"} | talk
    assert set(t.adjudicator.tool_names) == {"finalize_decision"}
    # No agent that reads untrusted text can finalise a payout.
    assert "finalize_decision" not in tools["intake"] | tools["policy"] | tools["fraud"]


def test_agents_can_read_long_term_memory_but_never_write_it():
    """Memory poisoning defence: customer text reaches agents, so agents must have no path into long term memory."""
    t = _team()
    every_tool = set(t.adjudicator.tool_names).union(*(set(a.tool_names) for a in t.agents.values()))
    assert "recall_lessons" in every_tool
    assert not [n for n in every_tool if "lesson" in n and n != "recall_lessons"]
    assert not [n for n in every_tool if n.startswith(("store", "write", "save", "remember"))]


def test_topology_references_only_known_nodes():
    tp = topology()
    ids = {n["id"] for n in tp["nodes"]}
    assert {"mcp_policy", "mcp_ops", "memory", "intake", "policy", "fraud", "adjudicator", "human"} <= ids
    assert all(e["src"] in ids and e["dst"] in ids for e in tp["edges"])
