"""Security properties of the serving stack, checked on the synthesised CloudFormation template (no AWS access needed). These are the claims the README makes
about the network and the IAM role, so a change that loosens them fails here before it can be deployed."""
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / "frontend" / "dist").exists() or not shutil.which("node"),
                                reason="needs a built frontend (npm run build) and Node.js for the CDK")


@pytest.fixture(scope="module")
def template():
    import aws_cdk as cdk
    from adjudication_infra.app_stack import AppStack
    from adjudication_infra.data_stack import DataStack
    from aws_cdk import assertions
    env = cdk.Environment(account="000000000000", region="us-east-1")
    app = cdk.App(context={"account": "000000000000"})
    stack = AppStack(app, "App", data=DataStack(app, "Data", env=env), mode="replay", env=env)
    return assertions.Template.from_stack(stack).to_json()


def of_type(template, kind):
    return {k: v.get("Properties", {}) for k, v in template["Resources"].items() if v["Type"] == kind}


def test_the_load_balancer_is_internal_and_sits_in_isolated_subnets(template):
    (alb,) = of_type(template, "AWS::ElasticLoadBalancingV2::LoadBalancer").values()
    assert alb["Scheme"] == "internal"
    isolated = {k for k, v in of_type(template, "AWS::EC2::Subnet").items() if "origin" in json.dumps(v["Tags"])}
    assert isolated and {s["Ref"] for s in alb["Subnets"]} == isolated
    # the isolated subnets' route tables hold no routes at all, so there is no path to an internet gateway
    tables = {a["RouteTableId"]["Ref"] for a in of_type(template, "AWS::EC2::SubnetRouteTableAssociation").values() if a["SubnetId"]["Ref"] in isolated}
    assert tables
    assert not [r for r in of_type(template, "AWS::EC2::Route").values() if r["RouteTableId"].get("Ref") in tables]


def test_cloudfront_reaches_the_api_only_through_a_vpc_origin(template):
    (vpc_origin,) = of_type(template, "AWS::CloudFront::VpcOrigin").values()
    assert vpc_origin["VpcOriginEndpointConfig"]["OriginProtocolPolicy"] == "http-only"  # plain HTTP, but only inside the AWS network
    (dist,) = of_type(template, "AWS::CloudFront::Distribution").values()
    api = next(o for o in dist["DistributionConfig"]["Origins"] if "VpcOriginConfig" in o)
    assert "CustomOriginConfig" not in api


def test_no_security_group_rule_admits_the_whole_internet(template):
    rules = [r for kind in ("AWS::EC2::SecurityGroup", "AWS::EC2::SecurityGroupIngress") for r in of_type(template, kind).values()]
    for rule in rules:
        for ingress in rule.get("SecurityGroupIngress", [rule] if "IpProtocol" in rule else []):
            assert ingress.get("CidrIp") not in ("0.0.0.0/0",) and ingress.get("CidrIpv6") != "::/0"


def test_the_origin_secret_is_generated_not_written_in_the_repository(template):
    assert len(of_type(template, "AWS::SecretsManager::Secret")) == 1
    text = json.dumps(template)
    assert text.count("{{resolve:secretsmanager:") >= 2  # the listener rule and the CloudFront custom header both read it
    assert "ClaimsAdjudicationApp" not in text  # the old secret was the stack's name, which is public


def test_the_task_role_names_its_resources(template):
    statements = [(k, s) for k, p in of_type(template, "AWS::IAM::Policy").items() if k.startswith("TaskRole") for s in p["PolicyDocument"]["Statement"]]
    assert statements
    for _, s in statements:
        resources = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
        if "*" in resources:
            assert s["Action"] == "cloudwatch:PutMetricData" and s["Condition"]["StringEquals"]["cloudwatch:namespace"] == "ClaimsAdjudication"
    by_sid = {s.get("Sid"): s for _, s in statements}
    invoke = json.dumps(by_sid["InvokeModels"]["Resource"])
    assert invoke.count("inference-profile/global.") == 3 and invoke.count("foundation-model/") == 3
    assert "Converse" not in json.dumps(by_sid["InvokeModels"]["Action"])  # Converse is authorised by InvokeModel
    assert by_sid["ApplyGuardrail"]["Action"] == "bedrock:ApplyGuardrail" and by_sid["ApplyGuardrail"]["Resource"] != "*"
    assert all(a in ("bedrock:InvokeDataAutomationAsync", "bedrock:GetDataAutomationStatus") for a in by_sid["DataAutomation"]["Action"])


def test_only_administrators_can_create_users_and_passwords_are_strong(template):
    (pool,) = of_type(template, "AWS::Cognito::UserPool").values()
    assert pool["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True
    policy = pool["Policies"]["PasswordPolicy"]
    assert policy["MinimumLength"] >= 12 and all(policy[k] for k in ("RequireLowercase", "RequireUppercase", "RequireNumbers", "RequireSymbols"))
    assert pool["MfaConfiguration"] in ("OPTIONAL", "ON")


def test_the_two_roles_exist_as_groups(template):
    assert {g["GroupName"] for g in of_type(template, "AWS::Cognito::UserPoolGroup").values()} == {"adjuster", "senior"}


def test_the_app_client_uses_the_code_flow_with_no_secret_and_returns_only_to_the_site(template):
    (client,) = of_type(template, "AWS::Cognito::UserPoolClient").values()
    assert client["AllowedOAuthFlows"] == ["code"] and client["GenerateSecret"] is False  # no implicit flow: tokens never travel in the URL
    assert client["SupportedIdentityProviders"] == ["COGNITO"]
    # no password flow a browser or script could call without AWS credentials: only the admin flow (IAM signed) and token refresh
    assert sorted(client["ExplicitAuthFlows"]) == ["ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
    for urls in (client["CallbackURLs"], client["LogoutURLs"]):
        assert len(urls) == 1 and "GetAtt" in json.dumps(urls) and "localhost" not in json.dumps(urls) and "http://" not in json.dumps(urls)


def test_the_api_is_told_which_pool_to_trust(template):
    (task,) = of_type(template, "AWS::ECS::TaskDefinition").values()
    env = {e["Name"] for e in task["ContainerDefinitions"][0]["Environment"]}
    assert {"CLAIMS_COGNITO_USER_POOL_ID", "CLAIMS_COGNITO_CLIENT_ID"} <= env  # without them the API would be open


def test_cloudfront_sits_behind_a_web_acl_that_rate_limits_each_address(template):
    (acl,) = of_type(template, "AWS::WAFv2::WebACL").values()
    assert acl["Scope"] == "CLOUDFRONT" and acl["DefaultAction"] == {"Allow": {}}
    rules = {r["Name"]: r for r in acl["Rules"]}
    runs, everything = rules["RunsPerIp"]["Statement"]["RateBasedStatement"], rules["RequestsPerIp"]["Statement"]["RateBasedStatement"]
    assert runs["AggregateKeyType"] == everything["AggregateKeyType"] == "IP"
    assert runs["Limit"] < everything["Limit"], "starting a run costs money, so it is limited harder than ordinary requests"
    assert runs["ScopeDownStatement"]["ByteMatchStatement"]["SearchString"] == "/run"
    assert all("Block" in r["Action"] for r in acl["Rules"])
    (dist,) = of_type(template, "AWS::CloudFront::Distribution").values()
    assert "WebACLId" in dist["DistributionConfig"]


def test_the_load_balancer_admits_only_the_cloudfront_vpc_origin_group_never_an_address_range(template):
    """Found in the first deployment: admitting the interfaces' subnet ranges left every API call timing out (504). CloudFront attaches a managed security
    group to the VPC origin's interfaces, and the load balancer has to admit that group."""
    alb_sgs = {k for k, v in template["Resources"].items() if v["Type"] == "AWS::EC2::SecurityGroup" and "Alb" in k}
    assert alb_sgs
    ingress = [r for r in of_type(template, "AWS::EC2::SecurityGroupIngress").values() if json.dumps(r["GroupId"]).count("Alb") and r.get("FromPort") == 80]
    assert ingress, "the ALB must admit CloudFront on port 80"
    for rule in ingress:
        assert "CidrIp" not in rule and "CidrIpv6" not in rule, "no address range may admit traffic to the ALB"
        assert "FindVpcOriginSecurityGroup" in json.dumps(rule["SourceSecurityGroupId"]), "the source is the group the lookup returns"


def test_the_lookup_of_the_cloudfront_group_has_one_narrow_permission_and_waits_for_the_distribution(template):
    custom = [(k, v) for k, v in template["Resources"].items() if v["Type"] == "Custom::AWS" and k.startswith("FindVpcOriginSecurityGroup")]
    assert len(custom) == 1
    key, res = custom[0]
    assert any(d.startswith("Cdn") for d in res["DependsOn"]), "the group only exists once the distribution is deployed"
    policies = [p for k, p in of_type(template, "AWS::IAM::Policy").items() if k.startswith("FindVpcOriginSecurityGroup")]
    assert policies, "the lookup needs a policy"
    actions = {a for p in policies for s in p["PolicyDocument"]["Statement"] for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    assert actions == {"ec2:DescribeSecurityGroups"}  # the only wildcard resource besides metrics and image pull, and the action is read-only


def test_the_sign_in_page_is_the_styled_managed_login_page_for_the_apps_client(template):
    (domain,) = of_type(template, "AWS::Cognito::UserPoolDomain").values()
    assert domain["ManagedLoginVersion"] == 2  # the newer page: the classic one cannot be styled this far
    (pool,) = of_type(template, "AWS::Cognito::UserPool").values()
    assert pool["UserPoolTier"] == "ESSENTIALS"  # managed login needs it
    (client_id,) = [k for k in of_type(template, "AWS::Cognito::UserPoolClient")]
    (branding,) = of_type(template, "AWS::Cognito::ManagedLoginBranding").values()
    assert branding["ClientId"] == {"Ref": client_id} and branding["UseCognitoProvidedValues"] is False
    assert branding["Settings"]["categories"]["global"]["colorSchemeMode"] == "DARK"
    assets = {(a["Category"], a["ColorMode"], a["Extension"]) for a in branding["Assets"]}
    assert assets == {("PAGE_BACKGROUND", "DARK", "PNG"), ("FORM_LOGO", "DARK", "PNG")}
    assert all(len(a["Bytes"]) > 1000 for a in branding["Assets"])  # real images, not empty placeholders


def test_sign_up_stays_off_so_only_an_administrator_creates_accounts(template):
    (pool,) = of_type(template, "AWS::Cognito::UserPool").values()
    assert pool["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True


# ---- what the README's AWS architecture diagram draws ---------------------------------------------------------------------------------------------------
# The diagram is a claim about the deployed system, so each thing it shows that can be read from the template is pinned here.

@pytest.fixture(scope="module")
def data_template():
    import aws_cdk as cdk
    from adjudication_infra.data_stack import DataStack
    from aws_cdk import assertions
    env = cdk.Environment(account="000000000000", region="us-east-1")
    return assertions.Template.from_stack(DataStack(cdk.App(context={"account": "000000000000"}), "Data", env=env)).to_json()


def _subnets_named(template, name):
    return {k for k, v in of_type(template, "AWS::EC2::Subnet").items() if any(t["Key"] == "aws-cdk:subnet-name" and t["Value"] == name for t in v["Tags"])}


def test_there_is_no_nat_gateway_and_the_task_runs_in_public_subnets_with_a_public_address_while_only_the_load_balancer_is_isolated(template):
    assert not of_type(template, "AWS::EC2::NatGateway")
    (service,) = of_type(template, "AWS::ECS::Service").values()
    network = service["NetworkConfiguration"]["AwsvpcConfiguration"]
    assert network["AssignPublicIp"] == "ENABLED"
    assert {s["Ref"] for s in network["Subnets"]} == _subnets_named(template, "public")
    assert service["DeploymentConfiguration"]["DeploymentCircuitBreaker"] == {"Enable": True, "Rollback": True}  # the release path says a failed update rolls back
    (alb,) = of_type(template, "AWS::ElasticLoadBalancingV2::LoadBalancer").values()
    assert {s["Ref"] for s in alb["Subnets"]} == _subnets_named(template, "origin")


def test_the_task_admits_only_the_load_balancer_and_the_load_balancer_admits_only_the_cloudfront_origin_group(template):
    rules = list(of_type(template, "AWS::EC2::SecurityGroupIngress").values())
    assert all("SourceSecurityGroupId" in r and "CidrIp" not in r for r in rules), "every inbound rule names a security group, never an address"
    assert sorted(r["FromPort"] for r in rules) == [80, 8000]
    to_task = next(r for r in rules if r["FromPort"] == 8000)
    to_alb = next(r for r in rules if r["FromPort"] == 80)
    assert "AlbSecurityGroup" in json.dumps(to_task["SourceSecurityGroupId"]) and "ServiceSecurityGroup" in json.dumps(to_task["GroupId"])
    assert "FindVpcOriginSecurityGroup" in json.dumps(to_alb["SourceSecurityGroupId"]) and "AlbSecurityGroup" in json.dumps(to_alb["GroupId"])


def test_the_task_is_a_single_container_and_the_listener_refuses_requests_without_the_origin_secret_header(template):
    (task,) = of_type(template, "AWS::ECS::TaskDefinition").values()
    assert [c["Name"] for c in task["ContainerDefinitions"]] == ["api"]  # the MCP servers are subprocesses of this container, not services
    (listener,) = of_type(template, "AWS::ElasticLoadBalancingV2::Listener").values()
    assert listener["DefaultActions"][0]["FixedResponseConfig"]["StatusCode"] == "403"
    (rule,) = of_type(template, "AWS::ElasticLoadBalancingV2::ListenerRule").values()
    assert rule["Conditions"][0]["HttpHeaderConfig"]["HttpHeaderName"] == "X-Origin-Verify"
    assert "secretsmanager" in json.dumps(rule["Conditions"][0]["HttpHeaderConfig"]["Values"])


def test_cloudwatch_has_a_dashboard_and_the_three_alarms_the_diagram_and_readme_name(template):
    assert len(of_type(template, "AWS::CloudWatch::Dashboard")) == 1
    names = " ".join(k for k in of_type(template, "AWS::CloudWatch::Alarm"))
    assert all(n in names for n in ("Api5xx", "ApiSlow", "RunCostSpike")) and len(of_type(template, "AWS::CloudWatch::Alarm")) == 3


def test_the_data_stack_holds_what_the_diagram_names(data_template):
    tables = sorted(tuple(k["AttributeName"] for k in t["KeySchema"]) for t in of_type(data_template, "AWS::DynamoDB::Table").values())
    assert tables == [("claim_id",), ("claim_id", "ts"), ("policy_no",), ("request_id",)]  # claims, audit, policies, metrics
    assert len(of_type(data_template, "AWS::S3::Bucket")) == 4  # claim packets, policy documents, telemetry lake, fine-tuning
    assert len(of_type(data_template, "AWS::S3Vectors::VectorBucket")) == 1
    assert sorted(t["TableInput"]["Name"] for t in of_type(data_template, "AWS::Glue::Table").values()) == ["calls", "runs"]
    assert len(of_type(data_template, "AWS::Athena::WorkGroup")) == 1
    for kind in ("AWS::Bedrock::Guardrail", "AWS::BedrockAgentCore::Memory", "AWS::Bedrock::DataAutomationProject"):
        assert len(of_type(data_template, kind)) == 1, kind
    assert len(of_type(data_template, "AWS::Bedrock::Blueprint")) == 2  # the claim form and the damage photo
    assert of_type(data_template, "AWS::Bedrock::KnowledgeBase")


def test_the_task_can_add_to_the_audit_log_but_never_change_or_delete_a_row(template, data_template):
    audit = next(k for k, v in of_type(data_template, "AWS::DynamoDB::Table").items() if "audit" in k.lower())
    actions = set()
    for key, policy in of_type(template, "AWS::IAM::Policy").items():
        if not key.startswith("TaskRole"):
            continue
        for s in policy["PolicyDocument"]["Statement"]:
            if audit in json.dumps(s.get("Resource", "")):
                actions |= {s["Action"]} if isinstance(s["Action"], str) else set(s["Action"])
    assert "dynamodb:PutItem" in actions and "dynamodb:Query" in actions
    assert not actions & {"dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"}
