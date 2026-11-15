"""Generates every architecture diagram in the README. Run: python docs/diagrams/generate.py

Diagrams are code, so they stay in sync with the system and reviews can diff them.
"""
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.analytics import Athena, Quicksight
from diagrams.aws.compute import ECR, Fargate
from diagrams.aws.database import Dynamodb
from diagrams.aws.devtools import Codebuild
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock, Sagemaker
from diagrams.aws.network import ALB, CloudFront
from diagrams.aws.security import IAM
from diagrams.aws.storage import S3
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import Users
from diagrams.programming.framework import Fastapi, React
from diagrams.programming.language import Python

OUT = Path(__file__).resolve().parents[1] / "images"
OUT.mkdir(exist_ok=True)
GRAPH = {"fontsize": "15", "bgcolor": "white", "pad": "0.4", "nodesep": "0.55", "ranksep": "0.9", "fontname": "Helvetica", "splines": "ortho"}
NODE = {"fontsize": "12", "fontname": "Helvetica"}


def aws_architecture() -> None:
    with Diagram("", filename=str(OUT / "aws_architecture"), show=False, direction="TB", graph_attr=GRAPH, node_attr=NODE, outformat="png"):
        adjuster = Users("Claims adjuster")
        with Cluster("Edge"):
            cdn = CloudFront("CloudFront")
            site = S3("React app")
        with Cluster("Serving path (ECS Fargate)"):
            alb = ALB("ALB")
            api = Fargate("FastAPI + Strands\nagent graph")
        with Cluster("Amazon Bedrock"):
            models = Bedrock("Claude and\nNova models")
            guard = Bedrock("Guardrails")
            kb = Bedrock("Knowledge Base\n(S3 Vectors)")
            bda = Bedrock("Bedrock Data\nAutomation")
            mem = Bedrock("AgentCore Memory\n(notes and lessons)")
        with Cluster("MCP servers (stdio)"):
            mcp1 = Fastapi("Policy and\nrecords")
            mcp2 = Fastapi("Claims\noperations")
        with Cluster("Data"):
            claims = S3("Claim packets")
            ddb = Dynamodb("Claims, audit,\nmetrics")
        with Cluster("Observability and analytics"):
            logs = Cloudwatch("Logs, metrics,\nalarms")
            lake = S3("Telemetry lake\n(per call JSON)")
            athena = Athena("Athena")
            qs = Quicksight("QuickSight\ncost and latency")
        with Cluster("Model adaptation"):
            sm = Sagemaker("SageMaker QLoRA\ntraining job")
        adjuster >> cdn >> site
        cdn >> Edge(label="/api") >> alb >> api
        api >> Edge(label="reason") >> models
        api >> Edge(label="scan text") >> guard
        api >> Edge(label="retrieve clauses") >> mcp1 >> kb
        api >> mcp2
        api >> Edge(label="recall, notes") >> mem
        claims >> Edge(label="extract") >> bda >> api
        api >> ddb
        api >> logs
        api >> Edge(label="every call") >> lake >> athena >> qs
        claims >> Edge(style="dashed", label="adapter and results") >> sm


def release_path() -> None:
    with Diagram("", filename=str(OUT / "release_path"), show=False, direction="LR", graph_attr=GRAPH, node_attr=NODE, outformat="png"):
        gh = GithubActions("GitHub Actions")
        with Cluster("Quality gates"):
            lint = Codebuild("Lint and\n184 tests")
            gate = Codebuild("Eval gate\n(63 golden claims)")
            red = Codebuild("Red team\n(30 attacks)")
        ecr = ECR("ECR image")
        deploy = Fargate("ECS rolling\nupdate")
        gh >> lint >> gate >> red >> ecr >> deploy
        IAM("OIDC role,\nno long lived keys") >> Edge(style="dashed") >> gh


def agent_graph() -> None:
    curved = GRAPH | {"splines": "spline", "ranksep": "1.1", "nodesep": "0.6"}
    with Diagram("", filename=str(OUT / "agent_graph"), show=False, direction="LR", graph_attr=curved, node_attr=NODE, outformat="png"):
        pk = S3("Claim packet")
        bda = Bedrock("Bedrock Data\nAutomation")
        g = Bedrock("Guardrails\n(untrusted text)")
        mem = Bedrock("AgentCore Memory")
        with Cluster("Strands agent team"):
            intake = Fastapi("Intake agent")
            cov = Fastapi("Coverage agent")
            inv = Fastapi("Investigator agent")
            adj = Fastapi("Adjudicator agent")
        with Cluster("MCP servers"):
            m1 = Fastapi("Policy and records")
            m2 = Fastapi("Claims operations")
        kb = Bedrock("Knowledge Base")
        engine = Python("Rules engine\n(decides)")
        human = React("Human adjuster")
        db = Dynamodb("Audit log")
        pk >> bda >> g >> intake
        mem >> Edge(label="recall lessons") >> intake
        intake >> [cov, inv]
        cov >> m1 >> kb
        inv >> m1
        inv >> m2
        inv >> Edge(label="questions", style="dashed") >> intake
        [cov, inv] >> engine >> adj >> human
        human >> Edge(label="lessons, guardrail scanned") >> mem
        human >> db


if __name__ == "__main__":
    aws_architecture()
    release_path()
    agent_graph()
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))
