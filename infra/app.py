import os

import aws_cdk as cdk
from adjudication_infra.app_stack import AppStack
from adjudication_infra.data_stack import DataStack

app = cdk.App()
# The region is explicit on purpose: the CDK CLI otherwise takes it from the AWS profile, which once sent a deploy to the wrong region.
region = app.node.try_get_context("region") or "us-east-1"
# CI passes -c account=000000000000 so synthesis needs no credentials. Real deploys use the caller's account.
account = app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT")
env = cdk.Environment(account=account, region=region)
synth = cdk.DefaultStackSynthesizer(qualifier="claimsadj")
mode = app.node.try_get_context("mode") or "replay"  # deploy with -c mode=live once Bedrock access works

data = DataStack(app, "ClaimsAdjudicationData", env=env, synthesizer=synth)
AppStack(app, "ClaimsAdjudicationApp", data=data, mode=mode, env=env, synthesizer=synth)
cdk.Tags.of(app).add("project", "agentic-claims-adjudication-aws")
app.synth()
