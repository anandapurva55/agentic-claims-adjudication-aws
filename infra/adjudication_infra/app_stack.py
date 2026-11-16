"""Serving layer: ECS Fargate API behind a private ALB that only CloudFront can reach through a VPC origin, plus the React site on S3."""
from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Fn, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_wafv2 as wafv2
from aws_cdk import custom_resources as cr
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

        production = str(self.node.try_get_context("production")).lower() == "true"  # see data_stack.py: -c production=true keeps data and logs
        log_group = logs.LogGroup(self, "ApiLogs", retention=logs.RetentionDays.THREE_MONTHS if production else logs.RetentionDays.ONE_WEEK,
                                  removal_policy=RemovalPolicy.RETAIN if production else RemovalPolicy.DESTROY)
        task = ecs.FargateTaskDefinition(self, "Task", cpu=1024, memory_limit_mib=2048, task_role=task_role,
                                         runtime_platform=ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.ARM64,
                                                                              operating_system_family=ecs.OperatingSystemFamily.LINUX))
        container = task.add_container("api", image=image, port_mappings=[ecs.PortMapping(container_port=8000)],
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
        # crosses the public internet and the ALB has no public address. Its security group admits only the security group CloudFront attaches to those
        # interfaces (added below, once the distribution exists). A secret header, generated by Secrets Manager at deploy time and never written in this
        # repository, is a second check for any other source inside the VPC.
        origin_secret = secretsmanager.Secret(self, "OriginSecret", description="Header value CloudFront sends to the API load balancer",
                                              generate_secret_string=secretsmanager.SecretStringGenerator(exclude_punctuation=True, password_length=40))
        origin_secret_value = origin_secret.secret_value.unsafe_unwrap()  # a dynamic reference resolved by CloudFormation, not a literal
        origin_selection = ec2.SubnetSelection(subnet_group_name="origin")
        alb = elbv2.ApplicationLoadBalancer(self, "Alb", vpc=vpc, internet_facing=False, vpc_subnets=origin_selection, idle_timeout=Duration.seconds(120))
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
        # Rate limiting at the edge, per client IP. Starting a run is the expensive call, so it gets a much lower limit than everything else. A web ACL for
        # CloudFront must live in us-east-1, so any other region fails at synthesis instead of at deploy.
        if self.region != "us-east-1" and not self.region.startswith("${Token"):
            raise ValueError("the CloudFront web ACL must be created in us-east-1")

        def rate_rule(name: str, priority: int, limit: int, window: int, only_runs: bool) -> wafv2.CfnWebACL.RuleProperty:
            statement = wafv2.CfnWebACL.RateBasedStatementProperty(
                limit=limit, aggregate_key_type="IP", evaluation_window_sec=window,
                scope_down_statement=wafv2.CfnWebACL.StatementProperty(byte_match_statement=wafv2.CfnWebACL.ByteMatchStatementProperty(
                    search_string="/run", positional_constraint="ENDS_WITH", field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(uri_path={}),
                    text_transformations=[wafv2.CfnWebACL.TextTransformationProperty(priority=0, type="NONE")])) if only_runs else None)
            return wafv2.CfnWebACL.RuleProperty(
                name=name, priority=priority, action=wafv2.CfnWebACL.RuleActionProperty(block={}), statement=wafv2.CfnWebACL.StatementProperty(rate_based_statement=statement),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(cloud_watch_metrics_enabled=True, sampled_requests_enabled=True, metric_name=name))

        web_acl = wafv2.CfnWebACL(
            self, "WebAcl", scope="CLOUDFRONT", default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            rules=[rate_rule("RunsPerIp", 1, limit=20, window=300, only_runs=True),  # at most 20 agent runs in 5 minutes from one address
                   rate_rule("RequestsPerIp", 2, limit=600, window=300, only_runs=False)],
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(cloud_watch_metrics_enabled=True, sampled_requests_enabled=True, metric_name="ClaimsAdjudicationWaf"))

        dist = cf.Distribution(
            self, "Cdn", default_root_object="index.html", web_acl_id=web_acl.attr_arn,
            default_behavior=cf.BehaviorOptions(origin=origins.S3BucketOrigin.with_origin_access_control(site),
                                                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS),
            additional_behaviors={"/api/*": cf.BehaviorOptions(
                origin=api_origin, allowed_methods=cf.AllowedMethods.ALLOW_ALL, compress=False,  # no compression keeps SSE streaming
                cache_policy=cf.CachePolicy.CACHING_DISABLED, origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                viewer_protocol_policy=cf.ViewerProtocolPolicy.HTTPS_ONLY)})  # no SPA fallback: it rewrote API 404s into the HTML page with status 200. The app only uses / and query strings.
        # CloudFront attaches a security group named CloudFront-VPCOrigins-Service-SG to the VPC origin's interfaces. Admitting the interfaces' subnet address
        # ranges does NOT work (found in the first deployment: every API call timed out with a 504); the load balancer must admit that group. CloudFormation
        # does not return its id, so a small custom resource looks it up after the distribution exists, as the CDK documentation describes. Its only permission
        # is ec2:DescribeSecurityGroups, which AWS does not allow to be limited to a resource.
        find_origin_sg = cr.AwsCustomResource(
            self, "FindVpcOriginSecurityGroup",
            on_create=cr.AwsSdkCall(service="ec2", action="describeSecurityGroups", physical_resource_id=cr.PhysicalResourceId.of("CloudFront-VPCOrigins-Service-SG"),
                                    parameters={"Filters": [{"Name": "vpc-id", "Values": [vpc.vpc_id]}, {"Name": "group-name", "Values": ["CloudFront-VPCOrigins-Service-SG"]}]}),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE))
        find_origin_sg.node.add_dependency(dist)
        alb.connections.allow_from(ec2.SecurityGroup.from_security_group_id(self, "VpcOriginServiceSg", find_origin_sg.get_response_field("SecurityGroups.0.GroupId")),
                                   ec2.Port.tcp(80), "CloudFront VPC origin")

        # Sign-in. Only people an administrator creates can sign in (no self sign-up). Role is the group: adjuster or senior. The site signs in through Cognito's
        # hosted page with the authorization code flow and PKCE, so no password ever passes through this application. The pool is created after the
        # distribution because the app client's callback URL is the distribution's address; the distribution does not depend on the service, so there is no cycle.
        pool = cognito.UserPool(
            self, "Users", self_sign_up_enabled=False, sign_in_aliases=cognito.SignInAliases(username=True, email=True), mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False), account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            password_policy=cognito.PasswordPolicy(min_length=12, require_lowercase=True, require_uppercase=True, require_digits=True, require_symbols=True),
            removal_policy=RemovalPolicy.DESTROY)
        for group, description in (("adjuster", "Can review claims up to the authority limit"), ("senior", "Can also approve payouts above the authority limit")):
            cognito.CfnUserPoolGroup(self, f"Group{group.title()}", user_pool_id=pool.user_pool_id, group_name=group, description=description)
        site_url = f"https://{dist.distribution_domain_name}/"
        web_client = pool.add_client(
            "Web", generate_secret=False, prevent_user_existence_errors=True, auth_flows=cognito.AuthFlow(admin_user_password=True),  # IAM-signed admin calls only: scripts/verify_deployment.py signs in a test user. Browsers cannot use it.
            o_auth=cognito.OAuthSettings(flows=cognito.OAuthFlows(authorization_code_grant=True), scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
                                         callback_urls=[site_url], logout_urls=[site_url]),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            id_token_validity=Duration.hours(1), access_token_validity=Duration.hours(1), refresh_token_validity=Duration.days(1))
        # The domain prefix must be unique across AWS. The first part of the stack's id is, and it does not put the account number in a public name.
        prefix = Fn.join("", ["claimsadj-", Fn.select(0, Fn.split("-", Fn.select(2, Fn.split("/", self.stack_id))))])
        hosted = pool.add_domain("Domain", cognito_domain=cognito.CognitoDomainOptions(domain_prefix=prefix))
        container.add_environment("CLAIMS_COGNITO_USER_POOL_ID", pool.user_pool_id)
        container.add_environment("CLAIMS_COGNITO_CLIENT_ID", web_client.user_pool_client_id)

        # The page reads this at start-up to know where to sign in. Written at deploy time, so no identifier is ever committed to the repository.
        site_config = s3deploy.Source.json_data("config.json", {"region": self.region, "userPoolId": pool.user_pool_id, "clientId": web_client.user_pool_client_id,
                                                                  "hostedUi": hosted.base_url()})
        s3deploy.BucketDeployment(self, "DeploySite", sources=[s3deploy.Source.asset(str(ROOT / "frontend" / "dist")), site_config],
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
        CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=web_client.user_pool_client_id)
