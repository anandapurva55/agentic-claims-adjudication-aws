"""The architecture the UI draws must match what the agents actually do. Every tool call lights a node and pulses an edge (TOOL_NODE, TOOL_EDGE in agents/graph.py), so
each of those has to exist in the drawn topology, or the animation shows traffic along a line the architecture tab never drew."""
from app.agents.graph import TOOL_EDGE, TOOL_NODE
from app.topology import EDGES, NODES

IDS = [n["id"] for n in NODES]


def test_node_ids_are_unique_and_every_edge_joins_two_drawn_nodes():
    assert len(IDS) == len(set(IDS))
    for a, b in EDGES:
        assert a in IDS and b in IDS, (a, b)
    assert len(EDGES) == len(set(EDGES)), "an edge is drawn twice"


def test_every_tool_pulse_runs_along_a_drawn_edge():
    for tool, edge in TOOL_EDGE.items():
        assert edge in EDGES, f"{tool} pulses {edge}, which the architecture tab does not draw"


def test_every_tool_lights_a_drawn_node_and_belongs_to_one_of_its_edge_ends():
    for tool, node in TOOL_NODE.items():
        assert node in IDS, f"{tool} lights {node}, which is not a node"
        assert node in TOOL_EDGE[tool], f"{tool} lights {node} but its pulse is on {TOOL_EDGE[tool]}"
