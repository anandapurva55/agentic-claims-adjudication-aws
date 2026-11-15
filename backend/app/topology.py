"""The architecture the UI draws. Node ids are the same ids the runners emit events for."""

NODES = [
    {"id": "upload", "label": "Claim intake", "sub": "form, estimate, photo", "kind": "input", "col": 0, "row": 0},
    {"id": "bda", "label": "Data Automation", "sub": "Bedrock BDA", "kind": "service", "col": 0, "row": 1},
    {"id": "guardrail", "label": "Safety filter", "sub": "Bedrock Guardrails", "kind": "guard", "col": 0, "row": 2},
    {"id": "intake", "label": "Intake agent", "sub": "Strands", "kind": "agent", "col": 1, "row": 1},
    {"id": "policy", "label": "Coverage agent", "sub": "Strands", "kind": "agent", "col": 2, "row": 0},
    {"id": "fraud", "label": "Investigator agent", "sub": "Strands", "kind": "agent", "col": 2, "row": 2},
    {"id": "mcp_policy", "label": "Policy MCP server", "sub": "wording, schedule, history", "kind": "mcp", "col": 3, "row": 0},
    {"id": "mcp_ops", "label": "Claims ops MCP", "sub": "cost, FIR, garage", "kind": "mcp", "col": 3, "row": 2},
    {"id": "calc", "label": "Payable calculator", "sub": "Deterministic tool", "kind": "tool", "col": 3, "row": 1},
    {"id": "kb", "label": "Policy wording", "sub": "Knowledge Base + S3 Vectors", "kind": "service", "col": 4, "row": 0},
    {"id": "adjudicator", "label": "Adjudicator agent", "sub": "Strands", "kind": "agent", "col": 4, "row": 1},
    {"id": "ddb", "label": "Records + audit", "sub": "DynamoDB", "kind": "service", "col": 4, "row": 2},
    {"id": "memory", "label": "Memory", "sub": "short and long term", "kind": "memory", "col": 4, "row": 3},
    {"id": "human", "label": "Human adjuster", "sub": "Approves or overrides", "kind": "human", "col": 5, "row": 1},
]

EDGES = [
    ("upload", "bda"), ("bda", "guardrail"), ("guardrail", "intake"), ("intake", "policy"), ("intake", "fraud"),
    ("intake", "memory"), ("policy", "mcp_policy"), ("mcp_policy", "kb"), ("policy", "calc"),
    ("fraud", "mcp_ops"), ("fraud", "mcp_policy"), ("policy", "adjudicator"), ("fraud", "adjudicator"), ("calc", "adjudicator"),
    ("adjudicator", "human"), ("adjudicator", "ddb"), ("human", "ddb"), ("human", "memory"),
]


def topology() -> dict:
    return {"nodes": NODES, "edges": [{"src": a, "dst": b} for a, b in EDGES]}
