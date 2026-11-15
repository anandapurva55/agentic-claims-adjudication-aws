"""Load the policy schedules and each claim's Bedrock Data Automation record into the DynamoDB tables the app reads in AWS.

  AWS_PROFILE=default python scripts/seed_dynamodb.py <policies_table> <claims_table>
Table names come from the ClaimsAdjudicationData stack outputs (PoliciesTableName, ClaimsTableName).
"""
import json
import sys
from decimal import Decimal
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def main(policies_table: str, claims_table: str) -> None:
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    fix = lambda o: json.loads(json.dumps(o), parse_float=Decimal)  # noqa: E731
    pol = json.loads((ROOT / "data" / "policies.json").read_text())
    with ddb.Table(policies_table).batch_writer() as w:
        for p in pol:
            w.put_item(Item=fix(p))
    n = 0
    with ddb.Table(claims_table).batch_writer() as w:
        for f in sorted((ROOT / "data" / "bda").glob("CLM-*.json")):
            b = json.loads(f.read_text())
            w.put_item(Item=fix({"claim_id": b["claim_id"], "bda": b}))
            n += 1
    print(f"{len(pol)} policies and {n} claim records written")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
