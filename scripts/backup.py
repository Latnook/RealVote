#!/usr/bin/env python3
"""Export every row of the DynamoDB table to a JSON file.

Written for destroy.sh, which must capture the whole table before Terraform deletes it.
Point-in-time recovery is enabled on the table but is NOT a safety net here: PITR dies
with the table it protects, so a deliberate teardown needs an export that outlives it.

The output is DynamoDB's own typed attribute format ({"S": "..."} and friends), exactly
what restore.py feeds back to batch_write_item — no lossy round-trip through Python
types, so a number stays a number and a set stays a set.

    ./scripts/backup.py --table realvote --region il-central-1 --out backups/x/table.json

Pagination is explicit rather than left to the AWS CLI: `aws dynamodb scan` merges pages
for you, but the item count it prints is per-page, which makes "did I get everything?"
unanswerable at exactly the moment it matters most.
"""

import argparse
import json
import pathlib
import sys

import boto3


def _client(region, endpoint):
    kwargs = {}
    if endpoint:
        # Must match backend/app/db.py._conn_kwargs exactly. DynamoDB Local partitions
        # its tables by access key and region, so connecting with different dummy
        # credentials than the app used lands in an empty namespace where the table
        # simply does not exist.
        kwargs.update(
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
    elif region:
        kwargs["region_name"] = region
    return boto3.client("dynamodb", **kwargs)


def export(table, region=None, endpoint=None):
    """Every item in the table, as typed DynamoDB JSON."""
    client = _client(region, endpoint)
    items, kwargs, pages = [], {}, 0
    while True:
        resp = client.scan(TableName=table, **kwargs)
        items.extend(resp["Items"])
        pages += 1
        if "LastEvaluatedKey" not in resp:
            return items, pages
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def summarise(items):
    """Counts by row kind, so a restore can be checked against something meaningful."""
    kinds = {"items": 0, "votes": 0, "profiles": 0, "suggestions": 0, "rate": 0, "stats": 0}
    for it in items:
        pk, sk = it["PK"]["S"], it["SK"]["S"]
        if pk.startswith("ITEM#"):
            kinds["items"] += 1
        elif pk.startswith("USER#"):
            kinds["profiles" if sk == "PROFILE" else "votes"] += 1
        elif pk == "SUGG":
            kinds["suggestions"] += 1
        elif pk.startswith("RATE#"):
            kinds["rate"] += 1
        elif pk == "STATS":
            kinds["stats"] += 1
    return kinds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--region")
    ap.add_argument("--endpoint", help="DynamoDB Local, for rehearsing the cycle")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    items, pages = export(args.table, args.region, args.endpoint)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # The row count is written into the file so restore.py can verify it read back
    # everything the export believed it wrote.
    payload = {"table": args.table, "count": len(items), "items": items}
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    kinds = summarise(items)
    print(f"    {len(items)} rows in {pages} page(s) -> {out}")
    print("    " + " · ".join(f"{v} {k}" for k, v in kinds.items() if v))
    if not items:
        print("    WARNING: the table was empty — nothing to restore later", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
