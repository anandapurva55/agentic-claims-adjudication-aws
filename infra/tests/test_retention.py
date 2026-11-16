"""What happens to the data when the stack is deleted. The demo is torn down on purpose, so the default deletes everything. A real deployment passes
-c production=true, and then the audit log and the buckets must survive a stack delete and the tables must refuse deletion."""
import pytest


def synth(production: bool) -> dict:
    import aws_cdk as cdk
    from adjudication_infra.data_stack import DataStack
    from aws_cdk import assertions
    app = cdk.App(context={"account": "000000000000", **({"production": "true"} if production else {})})
    return assertions.Template.from_stack(DataStack(app, "Data", env=cdk.Environment(account="000000000000", region="us-east-1"))).to_json()


def resources(template: dict, kind: str) -> dict:
    return {k: v for k, v in template["Resources"].items() if v["Type"] == kind}


@pytest.fixture(scope="module")
def demo():
    return synth(False)


@pytest.fixture(scope="module")
def production():
    return synth(True)


def test_the_demo_deletes_everything_with_the_stack(demo):
    tables, buckets = resources(demo, "AWS::DynamoDB::Table"), resources(demo, "AWS::S3::Bucket")
    assert tables and buckets
    assert all(t["DeletionPolicy"] == "Delete" and not t["Properties"].get("DeletionProtectionEnabled") for t in tables.values())
    assert all(b["DeletionPolicy"] == "Delete" for b in buckets.values())


def test_production_keeps_the_tables_and_blocks_their_deletion(production):
    tables = resources(production, "AWS::DynamoDB::Table")
    assert len(tables) == 4
    for t in tables.values():
        assert t["DeletionPolicy"] == "Retain" and t["Properties"]["DeletionProtectionEnabled"] is True
        assert t["Properties"]["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True


def test_production_keeps_the_buckets_and_does_not_empty_them_on_delete(production):
    buckets = resources(production, "AWS::S3::Bucket")
    assert buckets and all(b["DeletionPolicy"] == "Retain" for b in buckets.values())
    assert not resources(production, "Custom::S3AutoDeleteObjects"), "auto-delete would empty a bucket the stack is meant to keep"


def test_the_audit_table_is_among_the_retained_data(production):
    names = {k for k in resources(production, "AWS::DynamoDB::Table")}
    assert any(k.startswith("AuditTable") for k in names)
