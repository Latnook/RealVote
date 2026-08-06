import os
import time
import uuid

import boto3
from botocore.exceptions import ClientError

CHOICES = {"left": "votes_left", "right": "votes_right", "neutral": "votes_neutral"}


class AlreadyVoted(Exception):
    pass


class NotFound(Exception):
    pass


class RateLimited(Exception):
    pass


def _resource():
    kwargs = {}
    if os.environ.get("DDB_ENDPOINT"):
        kwargs.update(
            endpoint_url=os.environ["DDB_ENDPOINT"],
            region_name="us-east-1",
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
    return boto3.resource("dynamodb", **kwargs)


def table():
    return _resource().Table(os.environ["TABLE_NAME"])


def ensure_table(name):
    """Create the table if missing. Local/test/seed use only — AWS table comes from Terraform."""
    res = _resource()
    try:
        t = res.create_table(
            TableName=name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        t.wait_until_exists()
    except res.meta.client.exceptions.ResourceInUseException:
        pass


def _to_item_dict(record):
    d = {
        "id": record["PK"].removeprefix("ITEM#"),
        "name": record["name"],
        "emoji": record.get("emoji", ""),
        "status": record["status"],
        "votes_left": int(record["votes_left"]),
        "votes_right": int(record["votes_right"]),
        "votes_neutral": int(record["votes_neutral"]),
    }
    if record.get("image_key"):
        d["image_key"] = record["image_key"]
    return d


def create_item(item_id, name, emoji, image_key=None):
    record = {
        "PK": f"ITEM#{item_id}",
        "SK": "META",
        "name": name,
        "emoji": emoji,
        "status": "active",
        "votes_left": 0,
        "votes_right": 0,
        "votes_neutral": 0,
        "created_at": int(time.time()),
    }
    if image_key:
        record["image_key"] = image_key
    table().put_item(Item=record, ConditionExpression="attribute_not_exists(PK)")


def get_item(item_id):
    resp = table().get_item(Key={"PK": f"ITEM#{item_id}", "SK": "META"})
    record = resp.get("Item")
    return _to_item_dict(record) if record else None


def list_active_items():
    items, kwargs = [], {}
    while True:
        resp = table().scan(
            FilterExpression="SK = :meta AND #s = :active",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":meta": "META", ":active": "active"},
            **kwargs,
        )
        items.extend(_to_item_dict(r) for r in resp["Items"])
        if "LastEvaluatedKey" not in resp:
            return sorted(items, key=lambda i: i["id"])
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def update_item(item_id, **fields):
    allowed = {"name", "emoji", "image_key", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    expr = ", ".join(f"#f{i} = :v{i}" for i in range(len(updates)))
    names = {f"#f{i}": k for i, k in enumerate(updates)}
    values = {f":v{i}": v for i, v in enumerate(updates.values())}
    table().update_item(
        Key={"PK": f"ITEM#{item_id}", "SK": "META"},
        UpdateExpression=f"SET {expr}",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression="attribute_exists(PK)",
    )
