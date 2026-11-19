"""Generates every architecture diagram in the README. Run: python docs/diagrams/generate.py [aws_architecture release_path agent_graph]

Diagrams are code, so they stay in sync with the system and reviews can diff them. Each one is drawn from what the repository does, not from what it was meant to
do: the AWS diagram from infra/adjudication_infra, the release path from .github/workflows, the agent graph from backend/app/agents/graph.py and backend/app/runner.py.
No counts (tests, claims, attacks) are drawn into a picture, because a number in an image goes stale.
"""
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.analytics import Athena, Glue, Quicksight
from diagrams.aws.compute import ECR, Fargate
from diagrams.aws.database import Dynamodb
from diagrams.aws.devtools import Codebuild
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock, Sagemaker
from diagrams.aws.network import ALB, CloudFront
from diagrams.aws.security import WAF, Cognito, SecretsManager
from diagrams.aws.storage import S3
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Github
from diagrams.programming.framework import React
from diagrams.programming.language import Python

OUT = Path(__file__).resolve().parents[1] / "images"
OUT.mkdir(exist_ok=True)
LOGO = Path(__file__).resolve().parent / "assets" / "aws_logo.png"  # the AWS logo, for the corner of the AWS Cloud frame
GRAPH = {"fontsize": "15", "bgcolor": "white", "pad": "0.4", "nodesep": "0.55", "ranksep": "0.9", "fontname": "Helvetica", "splines": "ortho", "dpi": "200"}
NODE = {"fontsize": "15", "fontname": "Helvetica"}
EDGE = {"fontsize": "14", "fontname": "Helvetica", "color": "#5F6B76", "fontcolor": "#232F3E"}
BLUE = "#E5F5FD"


def group(label: str, colour: str = BLUE, margin: str = "24") -> Cluster:
    """A group inside a frame. The colour is set here because a nested group would otherwise take the next colour in the library's cycle."""
    return Cluster(label, graph_attr={"bgcolor": colour, "pencolor": "#9AA9B5", "fontsize": "15", "fontname": "Helvetica", "margin": margin})


def aws_cloud() -> Cluster:
    """The AWS Cloud frame that surrounds everything running on AWS, with the AWS logo, and no text, in its corner, in the style of AWS architecture diagrams."""
    label = f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="6"><TR><TD FIXEDSIZE="TRUE" WIDTH="68" HEIGHT="41"><IMG SRC="{LOGO}" SCALE="TRUE"/></TD></TR></TABLE>>'
    return Cluster(label, graph_attr={"pencolor": "#232F3E", "penwidth": "2", "style": "rounded", "bgcolor": "white", "labeljust": "r"})


def aws_architecture() -> None:
    """What the CDK app builds and what the API calls at run time. Dashed lines are not on the request path: deploy time, batch work, or a side check."""
    graph = GRAPH | {"rankdir": "LR", "compound": "true", "splines": "spline", "ranksep": "0.9", "nodesep": "0.4", "dpi": "150"}
    with Diagram("", filename=str(OUT / "aws_architecture"), show=False, direction="LR", graph_attr=graph, node_attr=NODE, edge_attr=EDGE, outformat="png"):
        adjuster = Users("Claims adjuster")
        operator = Python("Ingestion scripts\n(run by the operator)")
        with aws_cloud():
            with group("Edge and sign-in"):
                waf = WAF("AWS WAF\nrate limits")
                cdn = CloudFront("CloudFront")
                site = S3("React app")
                cognito = Cognito("Cognito\nmanaged login")
                secret = SecretsManager("Secrets Manager\norigin secret")
            with group("VPC"):
                with group("Isolated subnets\nno route to the internet"):
                    alb = ALB("Internal ALB")
                with group("Public subnets, no NAT\ninbound from the ALB only"):
                    with group("ECS Fargate task, one container"):
                        api = Fargate("FastAPI and\nStrands agents")
                        mcp_policy = Python("MCP policy_records\n(stdio)")
                        mcp_ops = Python("MCP claims_ops\n(stdio)")
            ecr = ECR("ECR\nimage")
            with group("Amazon Bedrock"):
                models = Bedrock("Models")
                Bedrock("Guardrails")
                Bedrock("AgentCore Memory")
                kb = Bedrock("Knowledge Base")
            vectors = S3("S3 Vectors\nclause index")
            ddb = Dynamodb("DynamoDB\nclaims, policies,\naudit, metrics")
            with group("Observability"):
                cw = Cloudwatch("CloudWatch\nlogs, metrics, alarms")
                lake = S3("Telemetry lake\n(one JSON per call)")
                glue = Glue("Glue catalog")
                athena = Athena("Athena")
                qs = Quicksight("QuickSight\ncost and latency")
            with group("Batch ingestion, before any run"):
                packets = S3("Claim packets")
                bda = Bedrock("Data Automation")
            with group("Offline experiment, not in the serving path"):
                Sagemaker("SageMaker\nQLoRA training")

        adjuster >> Edge(label="1 sign in\n(code flow, PKCE)") >> cognito
        adjuster >> Edge(label="2 request") >> waf >> cdn
        cdn >> Edge(label="app files") >> site
        cdn >> Edge(label="3 /api through\na VPC origin") >> alb >> Edge(label="4 to the task") >> api
        secret >> Edge(style="dashed", label="header value,\nset at deploy") >> cdn
        ecr >> Edge(style="dashed", label="image") >> api
        api >> Edge(style="dashed", label="token signing keys") >> cognito
        api >> mcp_policy
        api >> mcp_ops
        api >> Edge(label="5 models, guardrail,\nmemory", lhead="cluster_Amazon Bedrock") >> models
        mcp_policy >> Edge(label="retrieve clauses") >> kb >> vectors
        api >> Edge(label="6 records and audit,\nrun metrics") >> ddb
        api >> Edge(label="7 one record\nper model call") >> lake >> glue >> athena >> qs
        api >> Edge(label="logs, metrics") >> cw
        operator >> Edge(style="dashed", label="upload") >> packets >> Edge(style="dashed") >> bda >> Edge(style="dashed", label="extracted fields,\nloaded by script") >> ddb


def release_path() -> None:
    """The workflows that run on GitHub, as .github/workflows defines them. CI does not gate the deploy: deploy is started by hand.
    The three lanes stand side by side and each one reads from top to bottom."""
    graph = GRAPH | {"rankdir": "TB", "splines": "spline", "ranksep": "0.5", "nodesep": "0.35"}
    with Diagram("", filename=str(OUT / "release_path"), show=False, direction="TB", graph_attr=graph, node_attr=NODE, edge_attr=EDGE, outformat="png"):
        with group("On every push and pull request", margin="44"):
            GithubActions("CodeQL workflow\n(code scanning)")
            ci = GithubActions("CI workflow")
            backend = Codebuild("Backend\nlint, types, tests,\neval gate, red team")
            frontend = Codebuild("Frontend\ntests, audit, build")
            infra = Codebuild("Infrastructure\nsecurity tests, CDK synth\n(after the frontend build)")
            ci >> [backend, frontend]
            frontend >> infra
        with group("On every push to main", margin="44"):
            pages = GithubActions("Pages workflow")
            demo = Github("GitHub Pages\ninteractive demo")
            pages >> Edge(label="records data\nfrom the backend,\nbuilds the site") >> demo
        with group("Started by hand", margin="44"):
            deploy = GithubActions("Deploy workflow")
            live = GithubActions("Live eval and\nred team workflow")
            cdk = Codebuild("cdk deploy\nboth stacks")
            ecr = ECR("Image in ECR")
            ecs = Fargate("ECS rolling update,\nrollback on failure")
            site = S3("React app\nin S3")
            oidc = Edge(style="dashed", label="OIDC role,\nno long lived keys")
            deploy >> oidc >> cdk
            live >> oidc >> cdk
            cdk >> ecr >> ecs
            cdk >> site


def agent_graph() -> None:
    """One claim, in the order backend/app/runner.py runs it. The graph has three nodes (Intake, then Coverage and Investigator in parallel). The Adjudicator runs
    after the graph and the rule checks, and the rules engine, not a model, produces the decision."""
    curved = GRAPH | {"splines": "spline", "ranksep": "1.3", "nodesep": "0.7", "rankdir": "LR"}
    with Diagram("", filename=str(OUT / "agent_graph"), show=False, direction="LR", graph_attr=curved, node_attr=NODE, edge_attr=EDGE, outformat="png"):
        packet = S3("Claim packet")
        bda = Bedrock("Data Automation\n(read at ingestion)")
        guard = Bedrock("Guardrails\n(narrative is untrusted)")
        mem = Bedrock("AgentCore Memory")
        with group("Strands graph\n(each node is a Strands agent)"):
            intake = Python("Intake agent")
            coverage = Python("Coverage agent")
            investigator = Python("Investigator agent")
        with group("MCP servers (stdio)"):
            mcp_policy = Python("policy_records")
            mcp_ops = Python("claims_ops")
        kb = Bedrock("Knowledge Base")
        checks = Python("Rule and photo checks\n(add findings the\nagents missed)")
        adjudicator = Python("Adjudicator agent\n(writes the memo)")
        engine = Python("Rules engine\n(decides and calculates)")
        human = React("Human adjuster")
        audit = Dynamodb("Audit log")
        packet >> bda >> Edge(label="narrative") >> guard >> Edge(label="sanitised text") >> intake
        mem >> Edge(label="recall lessons") >> intake
        mem >> Edge(label="recall lessons") >> investigator
        intake >> Edge(label="flags") >> [coverage, investigator]
        coverage >> Edge(label="clauses, schedule") >> mcp_policy >> kb
        coverage >> Edge(label="calculate_payable") >> engine
        investigator >> Edge(label="claim history") >> mcp_policy
        investigator >> Edge(label="garage, cost,\npolice report") >> mcp_ops
        [coverage, investigator] >> checks >> adjudicator
        adjudicator >> Edge(label="finalize_decision") >> engine
        adjudicator >> Edge(label="decision, memo") >> human
        adjudicator >> Edge(label="audit record") >> audit
        human >> Edge(label="review") >> audit
        human >> Edge(label="lessons\n(guardrail scanned)") >> mem


if __name__ == "__main__":
    import sys
    chosen = sys.argv[1:] or ["aws_architecture", "release_path", "agent_graph"]  # name the diagrams to redraw only those
    for name in chosen:
        {"aws_architecture": aws_architecture, "release_path": release_path, "agent_graph": agent_graph}[name]()
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))
