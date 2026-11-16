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
    return {k: v["Properties"] for k, v in template["Resources"].items() if v["Type"] == kind}


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
