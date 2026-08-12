#!/usr/bin/env python3
"""Write a backup.py export back into the table.

The other half of destroy.sh's export, which for a long time had none: the teardown
wrote backups/…json and announced "Data export kept at …", but nothing in the repo could
read it. An export nothing can restore is not a backup.

    ./scripts/restore.py --table realvote --region il-central-1 --in backups/x/table.json

Refuses to run against a table that already holds rows unless --force is given, so a
routine deploy cannot quietly overwrite live votes with a stale snapshot.
"""

import argparse
import json
import sys
import time

import boto3

BATCH = 25          # DynamoDB's hard cap for batch_write_item
MAX_RETRIES = 8


def _client(region, endpoint):
    kwargs = {}
    if endpoint:
        # Must match backend/app/db.py._conn_kwargs exactly — DynamoDB Local partitions
        # tables by access key and region, so different dummy credentials mean a
        # different, empty namespace.
        kwargs.update(
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
    elif region:
        kwargs["region_name"] = region
    return boto3.client("dynamodb", **kwargs)


def row_count(client, table):
    """Exact count, not the table's hourly-updated ItemCount estimate."""
    n, kwargs = 0, {}
    while True:
        resp = client.scan(TableName=table, ProjectionExpression="PK", **kwargs)
        n += len(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            return n
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def restore(client, table, items, progress=None):
    """Batch-write every row, retrying whatever DynamoDB declines to take."""
    written = 0
    for start in range(0, len(items), BATCH):
        chunk = items[start:start + BATCH]
        request = {table: [{"PutRequest": {"Item": it}} for it in chunk]}
        for attempt in range(MAX_RETRIES):
            resp = client.batch_write_item(RequestItems=request)
            unprocessed = resp.get("UnprocessedItems") or {}
            if not unprocessed.get(table):
                break
            # Throttled: hand back only what was refused, with a widening pause.
            request = unprocessed
            time.sleep(2 ** attempt * 0.1)
        else:
            raise RuntimeError(
                f"DynamoDB kept refusing {len(request.get(table, []))} rows after "
                f"{MAX_RETRIES} attempts — restore is INCOMPLETE, do not delete the backup"
            )
        written += len(chunk)
        if progress:
            progress(written, len(items))
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--region")
    ap.add_argument("--endpoint", help="DynamoDB Local, for rehearsing the cycle")
    ap.add_argument("--in", dest="path", required=True)
    ap.add_argument("--force", action="store_true",
                    help="write even if the table already holds rows")
    args = ap.parse_args()

    with open(args.path, encoding="utf-8") as fh:
        payload = json.load(fh)
    items = payload["items"]
    expected = payload.get("count", len(items))
    if len(items) != expected:
        sys.exit(f"backup is inconsistent: header says {expected} rows, file holds {len(items)}")

    client = _client(args.region, args.endpoint)
    existing = row_count(client, args.table)
    if existing and not args.force:
        print(f"    table already holds {existing} rows — skipping restore (--force to override)")
        return 0

    written = restore(client, args.table, items)
    after = row_count(client, args.table)
    print(f"    wrote {written} rows; table now holds {after}")
    if after < len(items):
        sys.exit(f"RESTORE INCOMPLETE: expected at least {len(items)} rows, found {after}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
