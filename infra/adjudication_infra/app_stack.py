"""Serving layer: ECS Fargate API behind a private ALB that only CloudFront can reach through a VPC origin, plus the React site on S3."""
from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from .data_stack import DataStack

ROOT = Path(__file__).resolve().parents[2]
# The only models the API calls (settings.orchestrator_model, fast_model, policy_model). Each is reached through a global inference profile.
MODEL_IDS = ["anthropic.claude-sonnet-4-6", "amazon.nova-2-lite-v1:0", "anthropic.claude-haiku-4-5-20251001-v1:0"]


class AppStack(Stack):
    def __init__(self, scope: Construct, cid: str, data: DataStack, mode: str, **kw) -> None:
        super().__init__(scope, cid, **kw)

        # No NAT gateway (about $1 a day). The tasks sit in public subnets because they call AWS APIs. The load balancer sits in isolated subnets with no
        # route to the internet at all: the only way to reach it is the CloudFront VPC origin.
        vpc = ec2.Vpc(self, "Vpc", availability_zones=[f"{self.region}a", f"{self.region}b"], nat_gateways=0,
                      subnet_configuration=[ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                                            ec2.SubnetConfiguration(name="origin", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24)])
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights_v2=ecs.ContainerInsights.ENABLED)

        image = ecs.ContainerImage.from_docker_image_asset(ecr_assets.DockerImageAsset(
            self, "ApiImage", directory=str(ROOT), file="backend/Dockerfile", platform=ecr_assets.Platform.LINUX_ARM64,
            exclude=["frontend/node_modules", ".venv", "cdk.out", "data/real", "infra/cdk.out"]))

        task_role = iam.Role(self, "TaskRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
                             description="Least privilege role for the Claims Adjudication API")
        # Only the three models the code uses: their global inference profiles in this account, and the foundation models behind them (any region,
        # because a global profile routes anywhere). Guardrail scans are limited to this stack's guardrail.
        task_role.add_to_policy(iam.PolicyStatement(
            sid="InvokeModels", actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/global.{m}" for m in MODEL_IDS]
                      + [f"arn:aws:bedrock:*::foundation-model/{m}" for m in MODEL_IDS]))
        task_role.add_to_policy(iam.PolicyStatement(sid="ApplyGuardrail", actions=["bedrock:ApplyGuardrail"], resources=[data.guardrail.attr_guardrail_arn]))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="RetrievePolicyWording", actions=["bedrock:Retrieve"],
            resources=[f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/{data.kb_cards.attr_knowledge_base_id}"]))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="DataAutomation", actions=["bedrock:InvokeDataAutomationAsync", "bedrock:GetDataAutomationStatus"],
            resources=[f"arn:aws:bedrock:*:{self.account}:data-automation-{kind}/*" for kind in ("project", "profile", "invocation")]))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="AgentMemory", actions=["bedrock-agentcore:CreateEvent", "bedrock-agentcore:ListEvents", "bedrock-agentcore:RetrieveMemoryRecords",
                                        "bedrock-agentcore:BatchCreateMemoryRecords", "bedrock-agentcore:ListMemoryRecords", "bedrock-agentcore:GetMemory"],
            resources=[data.memory.attr_memory_arn]))
        for t in (data.claims_table, data.audit_table, data.policies_table, data.metrics_table):
            t.grant_read_write_data(task_role)
        data.claims_bucket.grant_read_write(task_role)
        data.telemetry_bucket.grant_put(task_role)
        task_role.add_to_policy(iam.PolicyStatement(sid="PublishMetrics", actions=["cloudwatch:PutMetricData"], resources=["*"],
                                                    conditions={"StringEquals": {"cloudwatch:namespace": "ClaimsAdjudication"}}))

        log_group = logs.LogGroup(self, "ApiLogs", retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY)
        task = ecs.FargateTaskDefinition(self, "Task", cpu=1024, memory_limit_mib=2048, task_role=task_role,
                                         runtime_platform=ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.ARM64,
                                                                              operating_system_family=ecs.OperatingSystemFamily.LINUX))
        task.add_container("api", image=image, port_mappings=[ecs.PortMapping(container_port=8000)],
                           logging=ecs.LogDrivers.aws_logs(stream_prefix="api", log_group=log_group),
                           environment={
                               "CLAIMS_MODE": mode, "CLAIMS_REGION": self.region,
                               "CLAIMS_GUARDRAIL_ID": data.guardrail.attr_guardrail_id,
                               "CLAIMS_GUARDRAIL_VERSION": data.guardrail_version.attr_version,
                               "CLAIMS_KNOWLEDGE_BASE_ID": data.kb_cards.attr_knowledge_base_id, "CLAIMS_MEMORY_ID": data.memory.attr_memory_id,
                               "CLAIMS_CLAIMS_TABLE": data.claims_table.table_name, "CLAIMS_POLICIES_TABLE": data.policies_table.table_name, "CLAIMS_AUDIT_TABLE": data.audit_table.table_name,
                               "CLAIMS_METRICS_TABLE": data.metrics_table.table_name, "CLAIMS_CALLS_BUCKET": data.telemetry_bucket.bucket_name,
                           },
                           health_check=ecs.HealthCheck(command=["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')\""],
                                                        interval=Duration.seconds(15), start_period=Duration.seconds(20)))

        service = ecs.FargateService(self, "Service", cluster=cluster, task_definition=task, desired_count=1,
                                     assign_public_ip=True, min_healthy_percent=100, max_healthy_percent=200,
                                     circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True))

        # The ALB is internal. CloudFront reaches it through a VPC origin, which puts network interfaces in the ALB's own isolated subnets, so traffic never
        # crosses the public internet and the ALB has no public address. Its security group admits only those subnets. A secret header, generated by Secrets
        # Manager at deploy time and never written in this repository, is a second check for any other source inside the VPC.
        origin_secret = secretsmanager.Secret(self, "OriginSecret", description="Header value CloudFront sends to the API load balancer",
                                              generate_secret_string=secretsmanager.SecretStringGenerator(exclude_punctuation=True, password_length=40))
        origin_secret_value = origin_secret.secret_value.unsafe_unwrap()  # a dynamic reference resolved by CloudFormation, not a literal
        origin_selection = ec2.SubnetSelection(subnet_group_name="origin")
        alb = elbv2.ApplicationLoadBalancer(self, "Alb", vpc=vpc, internet_facing=False, vpc_subnets=origin_selection, idle_timeout=Duration.seconds(120))
        for subnet in vpc.select_subnets(subnet_group_name="origin").subnets:
            alb.connections.allow_from(ec2.Peer.ipv4(subnet.ipv4_cidr_block), ec2.Port.tcp(80), "CloudFront VPC origin interfaces")
        listener = alb.add_listener("Http", port=80, open=False,
                                    default_action=elbv2.ListenerAction.fixed_response(403, content_type="text/plain", message_body="Forbidden"))
        listener.add_targets("Api", priority=10, port=8000, protocol=elbv2.ApplicationProtocol.HTTP, targets=[service],
                             conditions=[elbv2.ListenerCondition.http_header("X-Origin-Verify", [origin_secret_value])],
                             health_check=elbv2.HealthCheck(path="/api/health", interval=Duration.seconds(20)),
                             deregistration_delay=Duration.seconds(10))
        service.connections.allow_from(alb, ec2.Port.tcp(8000))

        site = s3.Bucket(self, "SiteBucket", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True,
                         encryption=s3.BucketEncryption.S3_MANAGED, removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True)
        api_origin = origins.VpcOrigin.with_application_load_balancer(alb, protocol_policy=cf.OriginProtocolPolicy.HTTP_ONLY, read_timeout=Duration.seconds(60),
                                                                      custom_headers={"X-Origin-Verify": origin_secret_value})
        dist = cf.Distribution(
            self, "Cdn", default_root_object="index.html",
            default_behavior=cf.BehaviorOptions(origin=origins.S3BucketOrigin.with_origin_access_control(site),
                                                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS),
            additional_behaviors={"/api/*": cf.BehaviorOptions(
                origin=api_origin, allowed_methods=cf.AllowedMethods.ALLOW_ALL, compress=False,  # no compression keeps SSE streaming
                cache_policy=cf.CachePolicy.CACHING_DISABLED, origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                viewer_protocol_policy=cf.ViewerProtocolPolicy.HTTPS_ONLY)})  # no SPA fallback: it rewrote API 404s into the HTML page with status 200. The app only uses / and query strings.
        s3deploy.BucketDeployment(self, "DeploySite", sources=[s3deploy.Source.asset(str(ROOT / "frontend" / "dist"))],
                                  destination_bucket=site, distribution=dist, distribution_paths=["/*"])

        # Observability: one dashboard and the alarms an on-call engineer would want.
        five_xx = alb.metrics.http_code_target(elbv2.HttpCodeTarget.TARGET_5XX_COUNT, period=Duration.minutes(1))
        latency = alb.metrics.target_response_time(period=Duration.minutes(1), statistic="p95")
        cw.Alarm(self, "Api5xx", metric=five_xx, threshold=5, evaluation_periods=2, alarm_description="API returning 5xx")
        run_cost = cw.Metric(namespace="ClaimsAdjudication", metric_name="RunCostUSD", statistic="Maximum", period=Duration.minutes(5))
        cw.Alarm(self, "RunCostSpike", metric=run_cost, threshold=0.15, evaluation_periods=1, treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                 alarm_description="A single claim run cost more than $0.15 (about 4x the measured average)")
        cw.Alarm(self, "ApiSlow", metric=latency, threshold=30, evaluation_periods=3, alarm_description="p95 latency above 30 s")
        board = cw.Dashboard(self, "Board", dashboard_name="ClaimsAdjudication")
        board.add_widgets(
            cw.GraphWidget(title="Requests", left=[alb.metrics.request_count(period=Duration.minutes(1))], width=8),
            cw.GraphWidget(title="p95 latency (s)", left=[latency], width=8),
            cw.GraphWidget(title="5xx", left=[five_xx], width=8),
            cw.GraphWidget(title="API CPU and memory", left=[service.metric_cpu_utilization(), service.metric_memory_utilization()], width=12))

        CfnOutput(self, "SiteUrl", value=f"https://{dist.distribution_domain_name}")
        CfnOutput(self, "DashboardName", value="ClaimsAdjudication")
