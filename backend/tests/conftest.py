import json
import os
import uuid

import pytest

os.environ.setdefault("DDB_ENDPOINT", "http://localhost:8000")

from app import db  # noqa: E402


@pytest.fixture()
def fresh_table(monkeypatch):
    name = f"lr-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("TABLE_NAME", name)
    db.ensure_table(name)
    yield name
    db._resource().Table(name).delete()


def apigw_event(method, path, body=None, cookies=None, admin=False):
    """Synthesize an API Gateway HTTP API v2 event — same shape local_server builds."""
    event = {
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "cookies": cookies or [],
    }
    if body is not None:
        event["body"] = json.dumps(body, ensure_ascii=False)
        event["isBase64Encoded"] = False
    if admin:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": "admin"}}}
    return event
