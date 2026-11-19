"""What the README's diagrams say, checked against the code and the workflow files. A diagram is a claim about the system, so each statement drawn in docs/diagrams/generate.py
that can be tested is tested here (the AWS architecture is pinned the same way in infra/tests). If the system changes and the picture does not, one of these fails.

Agent graph: which MCP server holds each tool, which agent may use it, the collaboration limit, and where the decision is made.
Release path: which workflows run on which events, and that nothing makes deploy wait for CI."""
import asyncio
from pathlib import Path

import pytest
import yaml
from app.agents.graph import build_team
from app.config import settings
from app.mcp_servers import claims_ops, policy_records

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _server_tools(server) -> set[str]:
    return {t.name for t in asyncio.run(server.mcp.list_tools())}


# ---- the agent graph ------------------------------------------------------------------------------------------------------------------------------------

def test_each_mcp_server_holds_the_tools_the_diagram_gives_it():
    assert _server_tools(policy_records) == {"search_policy_wording", "get_policy_schedule", "get_claim_history"}
    assert _server_tools(claims_ops) == {"benchmark_repair_cost", "verify_police_fir", "check_garage"}


def test_coverage_uses_only_policy_records_and_the_investigator_uses_both_servers():
    team = build_team()
    policy_server, ops_server = _server_tools(policy_records), _server_tools(claims_ops)
    coverage, investigator = set(team.agents["policy"].tool_names), set(team.agents["fraud"].tool_names)
    assert coverage & policy_server == {"search_policy_wording", "get_policy_schedule"} and not coverage & ops_server
    assert investigator & policy_server == {"get_claim_history"}
    assert investigator & ops_server == ops_server
    assert not set(team.agents["intake"].tool_names) & (policy_server | ops_server), "the Intake agent reaches no MCP server"


def test_the_adjudicator_is_not_a_node_of_the_graph_and_the_graph_has_three_nodes():
    team = build_team()
    assert set(team.agents) == {"intake", "policy", "fraud"}
    assert "adjudicator" not in team.agents
    assert {n.node_id for n in team.graph.nodes.values()} == {"intake", "policy", "fraud"}


def test_agents_question_each_other_for_one_round_by_default():
    assert settings.collab_rounds == 1


def test_the_rules_engine_is_reached_by_coverage_and_by_the_adjudicator_and_by_no_other_agent():
    team = build_team()
    assert "calculate_payable" in team.agents["policy"].tool_names
    assert "finalize_decision" in team.adjudicator.tool_names
    for name in ("intake", "fraud"):
        assert not {"calculate_payable", "finalize_decision"} & set(team.agents[name].tool_names), name


# ---- the release path -----------------------------------------------------------------------------------------------------------------------------------

def _workflow(name: str) -> dict:
    wf = yaml.safe_load((WORKFLOWS / name).read_text())
    wf["triggers"] = wf.pop("on", None) or wf.pop(True, None)  # YAML reads a bare `on:` as the boolean True
    return wf


def _triggers(name: str) -> set[str]:
    t = _workflow(name)["triggers"]
    return {t} if isinstance(t, str) else set(t)


def test_ci_has_three_jobs_and_only_the_infrastructure_job_waits_for_the_frontend_build():
    ci = _workflow("ci.yml")
    assert _triggers("ci.yml") == {"push", "pull_request"}
    assert set(ci["jobs"]) == {"backend", "frontend", "infra"}
    waits = {j: body["needs"] for j, body in ci["jobs"].items() if "needs" in body}
    assert waits == {"infra": ["frontend"]}, "the diagram draws the backend and frontend side by side and the infrastructure job after the frontend"


def test_codeql_is_its_own_workflow_that_ci_does_not_start():
    assert _triggers("codeql.yml") >= {"push"}
    assert "codeql" not in (WORKFLOWS / "ci.yml").read_text().lower()


def test_the_pages_workflow_publishes_the_demo_on_every_push_to_main():
    pages = _workflow("pages.yml")
    assert "push" in _triggers("pages.yml") and pages["triggers"]["push"]["branches"] == ["main"]


@pytest.mark.parametrize("name, role_variable", [("deploy.yml", "AWS_DEPLOY_ROLE_ARN"), ("eval-live.yml", "AWS_EVAL_ROLE_ARN")])
def test_deploy_and_live_evaluation_are_started_by_hand_and_assume_their_own_role(name, role_variable):
    text = (WORKFLOWS / name).read_text()
    assert _triggers(name) == {"workflow_dispatch"}
    assert "aws-actions/configure-aws-credentials" in text and f"vars.{role_variable}" in text
    assert "AWS_ACCESS_KEY_ID" not in text and "secrets.AWS" not in text, "no long lived keys"


def test_deploy_runs_cdk_deploy_for_both_stacks():
    assert "cdk@2 deploy --all" in (WORKFLOWS / "deploy.yml").read_text()


def test_nothing_makes_deploy_wait_for_ci():
    """The release path draws CI and deploy as separate lanes. If a workflow starts to depend on CI, the picture is wrong and this fails."""
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text()
        assert "workflow_run" not in text, f"{path.name} waits for another workflow"
    deploy = _workflow("deploy.yml")
    assert not [j for j, body in deploy["jobs"].items() if "needs" in body]
