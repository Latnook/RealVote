# LR Backend & Local Platform — Implementation Plan (1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The complete voting API (items, votes, suggestions, admin) running and tested locally against DynamoDB Local, plus a local server that also serves the (future) static site.

**Architecture:** One Python Lambda handler with a tiny router; a `db.py` data layer over a single DynamoDB table; API Gateway HTTP API v2 event format everywhere (the local server synthesizes the same events, so local and AWS run identical code).

**Tech Stack:** Python 3.12+ (Lambda runtime `python3.13`; local 3.14 is fine), boto3 (only production dependency — already in the Lambda runtime), pytest, DynamoDB Local via docker compose.

**Related plans:** Plan 2 = frontend (`site/`), Plan 3 = Terraform/AWS. Spec: `docs/superpowers/specs/2026-08-06-lr-voting-site-design.md`.

## Global Constraints

- Single DynamoDB table; key attribute names exactly `PK` / `SK`; record shapes exactly as defined in Task 2–4 (spec §4).
- Vote choices are exactly the strings `left`, `right`, `neutral`; counter attributes exactly `votes_left`, `votes_right`, `votes_neutral`.
- Visitor cookie name exactly `lr_uid`; `Max-Age=31536000; Path=/; Secure; HttpOnly; SameSite=Lax`.
- Double-vote prevention MUST be a DynamoDB conditional write (never read-then-write).
- API responses: JSON, `ensure_ascii=False` (Hebrew must survive), `cache-control: no-store` everywhere except `GET /api/items` (`public, max-age=30`).
- Suggestion cap: 5 per visitor per UTC day; suggestion text trimmed to 120 chars.
- Admin routes: authorized when `ALLOW_ADMIN=1` (local) OR an API-Gateway-verified JWT is present in the event (`requestContext.authorizer.jwt`). No password logic anywhere in this codebase.
- No web framework; standard library + boto3 only in `backend/app/`.
- All shell commands below run from the repo root `/home/latnook/Documents/LR2026` unless stated.

## File Structure

```
backend/
├── app/
│   ├── __init__.py          # empty
│   ├── db.py                # DynamoDB data layer (items, votes, suggestions)
│   ├── http.py              # event/response helpers: cookies, JSON body, responses
│   └── handler.py           # lambda_handler: router + route functions
├── local_server.py          # local HTTP server: /api/* → handler, everything else → ../site
├── seed/items.json          # 24 draft seed items (Hebrew + emoji)
├── seed.py                  # creates table + loads seed items (+ optional demo votes)
├── tests/
│   ├── conftest.py          # DynamoDB-Local fixture (fresh table per test) + event builder
│   ├── test_db_items.py
│   ├── test_db_votes.py
│   ├── test_db_suggestions.py
│   ├── test_http.py
│   ├── test_routes_public.py
│   └── test_routes_admin.py
├── requirements-dev.txt     # pytest, boto3
docker-compose.yml           # dynamodb-local on :8000
scripts/
└── local-dev.sh             # compose up + seed + run local_server.py
```

---

### Task 1: Scaffold + DynamoDB Local + test harness

**Files:**
- Create: `docker-compose.yml`, `backend/app/__init__.py` (empty), `backend/requirements-dev.txt`, `backend/tests/conftest.py`, `backend/tests/test_db_items.py` (first test only), `backend/app/db.py` (connection + `ensure_table` only)

**Interfaces:**
- Produces: `db._resource()`, `db.table()` (reads env `TABLE_NAME`, optional `DDB_ENDPOINT`), `db.ensure_table(name)`; pytest fixture `fresh_table`; helper `apigw_event(...)` in conftest.

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  dynamodb:
    image: amazon/dynamodb-local:latest
    command: -jar DynamoDBLocal.jar -inMemory
    ports:
      - "8000:8000"
```

- [ ] **Step 2: Write `backend/requirements-dev.txt`**

```
boto3
pytest
```

- [ ] **Step 3: Create venv and install; start DynamoDB Local**

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
docker compose up -d dynamodb
```

Expected: `docker compose ps` shows dynamodb running on :8000.

- [ ] **Step 4: Write `backend/app/db.py` (connection layer only)**

```python
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
```

- [ ] **Step 5: Write `backend/tests/conftest.py`**

```python
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
```

- [ ] **Step 6: Write the first failing test in `backend/tests/test_db_items.py`**

```python
from app import db


def test_ensure_table_is_idempotent(fresh_table):
    db.ensure_table(fresh_table)  # second call must not raise
    assert db.table().item_count == 0
```

- [ ] **Step 7: Run it**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_items.py -v`
Expected: PASS (validates the whole harness: docker, boto3, fixtures).

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml backend/
git commit -m "feat: backend scaffold with DynamoDB Local test harness"
```

---

### Task 2: Data layer — items

**Files:**
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_db_items.py`

**Interfaces:**
- Produces: `create_item(item_id, name, emoji, image_key=None)`, `get_item(item_id) -> dict|None`, `list_active_items() -> list[dict]`, `update_item(item_id, **fields)` (accepted fields: `name`, `emoji`, `image_key`, `status`). Item dict keys: `id, name, emoji, image_key(optional), status, votes_left, votes_right, votes_neutral` (counters as `int`).

- [ ] **Step 1: Write failing tests (append to `test_db_items.py`)**

```python
import pytest


def test_create_and_get_item(fresh_table):
    db.create_item("keter-chairs", "כיסאות כתר בגינה", "🪑")
    item = db.get_item("keter-chairs")
    assert item["name"] == "כיסאות כתר בגינה"
    assert item["status"] == "active"
    assert item["votes_left"] == 0 and item["votes_right"] == 0 and item["votes_neutral"] == 0


def test_get_missing_item_returns_none(fresh_table):
    assert db.get_item("nope") is None


def test_create_duplicate_raises(fresh_table):
    db.create_item("x", "א", "🅰️")
    with pytest.raises(Exception):
        db.create_item("x", "ב", "🅱️")


def test_list_active_excludes_archived(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.create_item("b", "ב", "🅱️")
    db.update_item("b", status="archived")
    ids = [i["id"] for i in db.list_active_items()]
    assert ids == ["a"]


def test_update_item_fields(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.update_item("a", name="אלף", image_key="img/a.webp")
    item = db.get_item("a")
    assert item["name"] == "אלף" and item["image_key"] == "img/a.webp"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_items.py -v`
Expected: FAIL — `AttributeError: module 'app.db' has no attribute 'create_item'`.

- [ ] **Step 3: Implement in `db.py` (append)**

```python
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
```

Note: a `Scan` is acceptable here **only because** the item catalog stays in the low hundreds; visitors hit the CDN-cached response, not DynamoDB. Do not "optimize" this with a GSI.

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_items.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/ && git commit -m "feat: item data layer (create/get/list/update)"
```

---

### Task 3: Data layer — votes

**Files:**
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_db_votes.py`

**Interfaces:**
- Consumes: `create_item`, `get_item` from Task 2.
- Produces: `record_vote(uid, item_id, choice) -> dict` (returns the updated item dict; raises `NotFound` for missing/archived item, `AlreadyVoted` on repeat, `KeyError` on bad choice), `get_user_votes(uid) -> dict[item_id, choice]`.

- [ ] **Step 1: Write failing tests in `test_db_votes.py`**

```python
import pytest

from app import db


@pytest.fixture()
def item(fresh_table):
    db.create_item("soy-coffee", "קפה עם חלב סויה", "🥛")
    return "soy-coffee"


def test_vote_increments_counter_and_returns_counts(item):
    result = db.record_vote("uid1", item, "left")
    assert result["votes_left"] == 1 and result["votes_right"] == 0


def test_three_uids_three_choices(item):
    db.record_vote("u1", item, "left")
    db.record_vote("u2", item, "right")
    db.record_vote("u3", item, "neutral")
    got = db.get_item(item)
    assert (got["votes_left"], got["votes_right"], got["votes_neutral"]) == (1, 1, 1)


def test_double_vote_rejected_and_not_counted(item):
    db.record_vote("u1", item, "left")
    with pytest.raises(db.AlreadyVoted):
        db.record_vote("u1", item, "right")
    assert db.get_item(item)["votes_right"] == 0


def test_vote_on_missing_or_archived_item(fresh_table):
    with pytest.raises(db.NotFound):
        db.record_vote("u1", "ghost", "left")
    db.create_item("old", "ישן", "🗿")
    db.update_item("old", status="archived")
    with pytest.raises(db.NotFound):
        db.record_vote("u1", "old", "left")


def test_bad_choice_raises_keyerror(item):
    with pytest.raises(KeyError):
        db.record_vote("u1", item, "center")


def test_get_user_votes(item):
    db.create_item("magnets", "מגנטים על המקרר", "🧲")
    db.record_vote("u9", item, "left")
    db.record_vote("u9", "magnets", "right")
    assert db.get_user_votes("u9") == {item: "left", "magnets": "right"}
    assert db.get_user_votes("stranger") == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_votes.py -v`
Expected: FAIL — `record_vote` not defined.

- [ ] **Step 3: Implement in `db.py` (append)**

```python
def record_vote(uid, item_id, choice):
    counter = CHOICES[choice]  # KeyError on invalid choice — router turns it into 400
    item = get_item(item_id)
    if item is None or item["status"] != "active":
        raise NotFound(item_id)
    try:
        table().put_item(
            Item={
                "PK": f"USER#{uid}",
                "SK": f"VOTE#{item_id}",
                "choice": choice,
                "ts": int(time.time()),
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise AlreadyVoted(item_id) from e
        raise
    resp = table().update_item(
        Key={"PK": f"ITEM#{item_id}", "SK": "META"},
        UpdateExpression=f"ADD {counter} :one",
        ExpressionAttributeValues={":one": 1},
        ReturnValues="ALL_NEW",
    )
    return _to_item_dict(resp["Attributes"])


def get_user_votes(uid):
    votes, kwargs = {}, {}
    while True:
        resp = table().query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :v)",
            ExpressionAttributeValues={":pk": f"USER#{uid}", ":v": "VOTE#"},
            **kwargs,
        )
        for r in resp["Items"]:
            votes[r["SK"].removeprefix("VOTE#")] = r["choice"]
        if "LastEvaluatedKey" not in resp:
            return votes
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
```

(`attribute_not_exists(PK)` is evaluated against the record at the full `PK+SK` key being written — the standard DynamoDB uniqueness idiom.)

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_votes.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/ && git commit -m "feat: vote recording with conditional dedup and atomic counters"
```

---

### Task 4: Data layer — suggestions

**Files:**
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_db_suggestions.py`

**Interfaces:**
- Produces: `add_suggestion(uid, text) -> sid` (raises `RateLimited` past 5/day/uid), `list_suggestions(status) -> list[dict]` (dict keys: `sid, text, uid, status, ts`; sorted oldest-first), `set_suggestion_status(sid, status)` (raises `NotFound` for unknown sid).

- [ ] **Step 1: Write failing tests in `test_db_suggestions.py`**

```python
import pytest

from app import db


def test_add_and_list_pending(fresh_table):
    sid = db.add_suggestion("u1", "  פיצה עם תירס  ")
    pending = db.list_suggestions("pending")
    assert [s["sid"] for s in pending] == [sid]
    assert pending[0]["text"] == "פיצה עם תירס"


def test_daily_cap_five(fresh_table):
    for n in range(5):
        db.add_suggestion("u1", f"הצעה {n}")
    with pytest.raises(db.RateLimited):
        db.add_suggestion("u1", "אחת יותר מדי")
    db.add_suggestion("u2", "משתמש אחר בסדר")


def test_text_trimmed_to_120_chars(fresh_table):
    db.add_suggestion("u1", "א" * 300)
    assert len(db.list_suggestions("pending")[0]["text"]) == 120


def test_status_transitions(fresh_table):
    sid = db.add_suggestion("u1", "משהו")
    db.set_suggestion_status(sid, "approved")
    assert db.list_suggestions("pending") == []
    assert db.list_suggestions("approved")[0]["sid"] == sid


def test_set_status_unknown_sid_raises(fresh_table):
    with pytest.raises(db.NotFound):
        db.set_suggestion_status("nope", "rejected")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_suggestions.py -v`
Expected: FAIL — `add_suggestion` not defined.

- [ ] **Step 3: Implement in `db.py` (append)**

```python
SUGGEST_DAILY_CAP = 5


def add_suggestion(uid, text):
    day = time.strftime("%Y%m%d", time.gmtime())
    resp = table().update_item(
        Key={"PK": f"RATE#{uid}", "SK": f"SUGGEST#{day}"},
        UpdateExpression="ADD n :one",
        ExpressionAttributeValues={":one": 1},
        ReturnValues="ALL_NEW",
    )
    if int(resp["Attributes"]["n"]) > SUGGEST_DAILY_CAP:
        raise RateLimited(uid)
    sid = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}"
    table().put_item(
        Item={
            "PK": "SUGG",
            "SK": sid,
            "text": text.strip()[:120],
            "uid": uid,
            "status": "pending",
            "ts": int(time.time()),
        }
    )
    return sid


def list_suggestions(status):
    out, kwargs = [], {}
    while True:
        resp = table().query(
            KeyConditionExpression="PK = :pk",
            FilterExpression="#s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":pk": "SUGG", ":status": status},
            **kwargs,
        )
        out.extend(
            {"sid": r["SK"], "text": r["text"], "uid": r["uid"],
             "status": r["status"], "ts": int(r["ts"])}
            for r in resp["Items"]
        )
        if "LastEvaluatedKey" not in resp:
            return out  # SK is time-prefixed → query order is oldest-first already
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def set_suggestion_status(sid, status):
    try:
        table().update_item(
            Key={"PK": "SUGG", "SK": sid},
            UpdateExpression="SET #s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": status},
            ConditionExpression="attribute_exists(PK)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise NotFound(sid) from e
        raise
```

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_suggestions.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/ && git commit -m "feat: suggestion queue with daily rate cap"
```

---

### Task 5: HTTP helpers

**Files:**
- Create: `backend/app/http.py`
- Test: `backend/tests/test_http.py`

**Interfaces:**
- Produces: `get_cookie(event, name) -> str|None`, `new_uid() -> str`, `uid_set_cookie(uid) -> str`, `read_json(event) -> dict|None`, `response(status, body=None, cookies=None, cache=None) -> dict` (API GW v2 response; default `cache-control: no-store`; JSON with `ensure_ascii=False`).

- [ ] **Step 1: Write failing tests in `test_http.py`**

```python
import json

from app import http
from conftest import apigw_event


def test_get_cookie():
    e = apigw_event("GET", "/api/me", cookies=["a=1", "lr_uid=abc123"])
    assert http.get_cookie(e, "lr_uid") == "abc123"
    assert http.get_cookie(e, "missing") is None


def test_uid_set_cookie_attributes():
    c = http.uid_set_cookie("abc")
    assert c.startswith("lr_uid=abc;")
    for part in ("Max-Age=31536000", "Path=/", "Secure", "HttpOnly", "SameSite=Lax"):
        assert part in c


def test_read_json_valid_invalid_and_base64():
    import base64
    assert http.read_json(apigw_event("POST", "/x", body={"a": 1})) == {"a": 1}
    bad = apigw_event("POST", "/x")
    bad["body"] = "{not json"
    assert http.read_json(bad) is None
    b64 = apigw_event("POST", "/x")
    b64["body"] = base64.b64encode(b'{"b":2}').decode()
    b64["isBase64Encoded"] = True
    assert http.read_json(b64) == {"b": 2}


def test_response_defaults_and_hebrew():
    r = http.response(200, {"name": "שמאלני"})
    assert r["statusCode"] == 200
    assert r["headers"]["cache-control"] == "no-store"
    assert "שמאלני" in r["body"]  # not \u escaped


def test_response_cache_and_cookies():
    r = http.response(200, {}, cookies=["lr_uid=x; Path=/"], cache="public, max-age=30")
    assert r["headers"]["cache-control"] == "public, max-age=30"
    assert r["cookies"] == ["lr_uid=x; Path=/"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_http.py -v`
Expected: FAIL — `No module named 'app.http'` (via import error).

- [ ] **Step 3: Implement `backend/app/http.py`**

```python
import base64
import json
import uuid


def get_cookie(event, name):
    for c in event.get("cookies") or []:
        k, _, v = c.partition("=")
        if k == name:
            return v
    return None


def new_uid():
    return uuid.uuid4().hex


def uid_set_cookie(uid):
    return (
        f"lr_uid={uid}; Max-Age=31536000; Path=/; Secure; HttpOnly; SameSite=Lax"
    )


def read_json(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def response(status, body=None, cookies=None, cache=None):
    result = {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": cache or "no-store",
        },
        "body": json.dumps(body if body is not None else {}, ensure_ascii=False),
    }
    if cookies:
        result["cookies"] = cookies
    return result
```

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_http.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/ && git commit -m "feat: HTTP event/response helpers"
```

---

### Task 6: Router + public routes

**Files:**
- Create: `backend/app/handler.py`
- Test: `backend/tests/test_routes_public.py`

**Interfaces:**
- Consumes: everything from Tasks 2–5.
- Produces: `lambda_handler(event, context) -> dict`; route functions `get_items`, `get_me`, `post_vote`, `post_suggest`; `is_admin(event) -> bool`. Response bodies: items → `{"items": [...]}`; me → `{"votes": {...}}`; vote → `{"item": <item dict>, "your_choice": <choice>}`; suggest → `{"ok": true}`.

- [ ] **Step 1: Write failing tests in `test_routes_public.py`**

```python
import json

from app import db
from app.handler import lambda_handler
from conftest import apigw_event


def call(event):
    resp = lambda_handler(event, None)
    return resp, json.loads(resp["body"])


def seeded(fresh_table):
    db.create_item("keter", "כיסאות כתר", "🪑")
    db.create_item("soy", "חלב סויה", "🥛")


def test_get_items_lists_active_with_cache(fresh_table):
    seeded(fresh_table)
    resp, body = call(apigw_event("GET", "/api/items"))
    assert resp["statusCode"] == 200
    assert resp["headers"]["cache-control"] == "public, max-age=30"
    assert [i["id"] for i in body["items"]] == ["keter", "soy"]


def test_me_without_cookie_sets_one(fresh_table):
    resp, body = call(apigw_event("GET", "/api/me"))
    assert body == {"votes": {}}
    assert resp["cookies"][0].startswith("lr_uid=")
    assert resp["headers"]["cache-control"] == "no-store"


def test_vote_flow_and_dedup(fresh_table):
    seeded(fresh_table)
    resp, body = call(apigw_event("POST", "/api/vote",
                                  body={"item_id": "keter", "choice": "right"}))
    assert resp["statusCode"] == 200
    assert body["item"]["votes_right"] == 1 and body["your_choice"] == "right"
    uid_cookie = resp["cookies"][0].split(";")[0]  # lr_uid=<uid>
    resp2, _ = call(apigw_event("POST", "/api/vote", cookies=[uid_cookie],
                                body={"item_id": "keter", "choice": "left"}))
    assert resp2["statusCode"] == 409
    resp3, body3 = call(apigw_event("GET", "/api/me", cookies=[uid_cookie]))
    assert body3["votes"] == {"keter": "right"}


def test_vote_validation_errors(fresh_table):
    seeded(fresh_table)
    assert call(apigw_event("POST", "/api/vote", body={"item_id": "keter", "choice": "center"}))[0]["statusCode"] == 400
    assert call(apigw_event("POST", "/api/vote", body={"choice": "left"}))[0]["statusCode"] == 400
    assert call(apigw_event("POST", "/api/vote", body={"item_id": "ghost", "choice": "left"}))[0]["statusCode"] == 404
    bad = apigw_event("POST", "/api/vote")
    bad["body"] = "{oops"
    assert call(bad)[0]["statusCode"] == 400


def test_suggest_and_rate_limit(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/suggest", body={"text": "פיצה עם תירס"}))
    assert resp["statusCode"] == 202
    uid_cookie = resp["cookies"][0].split(";")[0]
    for _ in range(4):
        call(apigw_event("POST", "/api/suggest", cookies=[uid_cookie], body={"text": "עוד"}))
    resp429, _ = call(apigw_event("POST", "/api/suggest", cookies=[uid_cookie], body={"text": "עוד"}))
    assert resp429["statusCode"] == 429
    assert call(apigw_event("POST", "/api/suggest", body={"text": "  "}))[0]["statusCode"] == 400


def test_unknown_route_404(fresh_table):
    assert call(apigw_event("GET", "/api/nope"))[0]["statusCode"] == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_routes_public.py -v`
Expected: FAIL — no module `app.handler`.

- [ ] **Step 3: Implement `backend/app/handler.py`**

```python
import os

from app import db, http


def is_admin(event):
    if os.environ.get("ALLOW_ADMIN") == "1":
        return True
    return "jwt" in (event.get("requestContext", {}).get("authorizer") or {})


def _uid(event):
    """Returns (uid, new_cookie_or_None)."""
    uid = http.get_cookie(event, "lr_uid")
    if uid:
        return uid, None
    uid = http.new_uid()
    return uid, http.uid_set_cookie(uid)


def get_items(event):
    return http.response(200, {"items": db.list_active_items()},
                         cache="public, max-age=30")


def get_me(event):
    uid, cookie = _uid(event)
    votes = {} if cookie else db.get_user_votes(uid)
    return http.response(200, {"votes": votes},
                         cookies=[cookie] if cookie else None)


def post_vote(event):
    body = http.read_json(event)
    if body is None or not isinstance(body.get("item_id"), str):
        return http.response(400, {"error": "bad_request"})
    uid, cookie = _uid(event)
    cookies = [cookie] if cookie else None
    try:
        item = db.record_vote(uid, body["item_id"], body.get("choice"))
    except KeyError:
        return http.response(400, {"error": "bad_choice"}, cookies=cookies)
    except db.NotFound:
        return http.response(404, {"error": "unknown_item"}, cookies=cookies)
    except db.AlreadyVoted:
        return http.response(409, {"error": "already_voted"}, cookies=cookies)
    return http.response(200, {"item": item, "your_choice": body["choice"]},
                         cookies=cookies)


def post_suggest(event):
    body = http.read_json(event)
    text = (body or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        return http.response(400, {"error": "empty_text"})
    uid, cookie = _uid(event)
    cookies = [cookie] if cookie else None
    try:
        db.add_suggestion(uid, text)
    except db.RateLimited:
        return http.response(429, {"error": "rate_limited"}, cookies=cookies)
    return http.response(202, {"ok": True}, cookies=cookies)


PUBLIC_ROUTES = {
    ("GET", "/api/items"): get_items,
    ("GET", "/api/me"): get_me,
    ("POST", "/api/vote"): post_vote,
    ("POST", "/api/suggest"): post_suggest,
}


def lambda_handler(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"].rstrip("/") or "/"
    route = PUBLIC_ROUTES.get((method, path))
    if route:
        return route(event)
    if path.startswith("/api/admin/"):
        from app import admin_routes  # imported lazily; added in Task 7
        return admin_routes.dispatch(event, method, path, is_admin(event))
    return http.response(404, {"error": "not_found"})
```

- [ ] **Step 4: Run tests** (admin import is lazy, so public tests pass without Task 7)

Run: `cd backend && ../.venv/bin/pytest tests/test_routes_public.py -v`
Expected: all PASS.

- [ ] **Step 5: Run whole suite, commit**

```bash
cd backend && ../.venv/bin/pytest -q && cd ..
git add backend/ && git commit -m "feat: lambda router and public API routes"
```

---

### Task 7: Admin routes

**Files:**
- Create: `backend/app/admin_routes.py`
- Test: `backend/tests/test_routes_admin.py`

**Interfaces:**
- Consumes: `db.*` (Tasks 2–4), `http.*` (Task 5), called from `handler.lambda_handler` via `dispatch(event, method, path, authorized)`.
- Produces routes:
  - `GET  /api/admin/suggestions` → `{"suggestions": [...]}` (pending, oldest first)
  - `POST /api/admin/suggestions/{sid}/approve` body `{"item_id","name","emoji"}` → creates item, marks approved → `{"ok": true}`
  - `POST /api/admin/suggestions/{sid}/reject` → `{"ok": true}`
  - `POST /api/admin/items` body `{"item_id","name","emoji","want_image":bool}` → `{"ok":true, "upload_url":str|null, "image_key":str|null}`
  - `PATCH /api/admin/items/{item_id}` body subset of `{"name","emoji","status","image_key"}` → `{"ok": true}`
  - All → `401 {"error":"unauthorized"}` when not authorized. Presigned URL uses env `IMG_BUCKET` (returns `upload_url: null` when unset — local mode without S3).

- [ ] **Step 1: Write failing tests in `test_routes_admin.py`**

```python
import json

from app import db
from app.handler import lambda_handler
from conftest import apigw_event


def call(event):
    resp = lambda_handler(event, None)
    return resp, json.loads(resp["body"])


def test_admin_routes_require_auth(fresh_table):
    resp, body = call(apigw_event("GET", "/api/admin/suggestions"))
    assert resp["statusCode"] == 401


def test_env_flag_authorizes(fresh_table, monkeypatch):
    monkeypatch.setenv("ALLOW_ADMIN", "1")
    resp, _ = call(apigw_event("GET", "/api/admin/suggestions"))
    assert resp["statusCode"] == 200


def test_list_approve_reject_flow(fresh_table):
    s1 = db.add_suggestion("u1", "פיצה עם תירס")
    s2 = db.add_suggestion("u1", "משהו גרוע")
    resp, body = call(apigw_event("GET", "/api/admin/suggestions", admin=True))
    assert [s["sid"] for s in body["suggestions"]] == [s1, s2]

    resp, _ = call(apigw_event("POST", f"/api/admin/suggestions/{s1}/approve", admin=True,
                               body={"item_id": "corn-pizza", "name": "פיצה עם תירס", "emoji": "🌽"}))
    assert resp["statusCode"] == 200
    assert db.get_item("corn-pizza")["status"] == "active"

    call(apigw_event("POST", f"/api/admin/suggestions/{s2}/reject", admin=True))
    assert call(apigw_event("GET", "/api/admin/suggestions", admin=True))[1]["suggestions"] == []


def test_approve_unknown_sid_404(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/suggestions/nope/approve", admin=True,
                               body={"item_id": "x", "name": "א", "emoji": "🅰️"}))
    assert resp["statusCode"] == 404


def test_create_item_without_image(fresh_table):
    resp, body = call(apigw_event("POST", "/api/admin/items", admin=True,
                                  body={"item_id": "sup", "name": "סאפ בכנרת", "emoji": "🏄"}))
    assert resp["statusCode"] == 200 and body["upload_url"] is None
    assert db.get_item("sup")["name"] == "סאפ בכנרת"


def test_create_item_with_image_returns_presigned(fresh_table, monkeypatch):
    monkeypatch.setenv("IMG_BUCKET", "lr-fake-bucket")
    resp, body = call(apigw_event("POST", "/api/admin/items", admin=True,
                                  body={"item_id": "bbq", "name": "מנגל", "emoji": "🍖",
                                        "want_image": True}))
    assert body["image_key"] == "img/bbq.webp"
    assert "lr-fake-bucket" in body["upload_url"] and "img/bbq.webp" in body["upload_url"]


def test_patch_item(fresh_table):
    db.create_item("a", "א", "🅰️")
    resp, _ = call(apigw_event("PATCH", "/api/admin/items/a", admin=True,
                               body={"status": "archived"}))
    assert resp["statusCode"] == 200
    assert db.get_item("a")["status"] == "archived"


def test_duplicate_item_id_409(fresh_table):
    db.create_item("a", "א", "🅰️")
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True,
                               body={"item_id": "a", "name": "ב", "emoji": "🅱️"}))
    assert resp["statusCode"] == 409
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_routes_admin.py -v`
Expected: FAIL — `No module named 'app.admin_routes'`.

- [ ] **Step 3: Implement `backend/app/admin_routes.py`**

```python
import os
import re

import boto3
from botocore.exceptions import ClientError

from app import db, http

_SLUG = re.compile(r"^[a-z0-9-]{1,64}$")


def _presign(image_key):
    bucket = os.environ.get("IMG_BUCKET")
    if not bucket:
        return None
    s3 = boto3.client("s3")
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": image_key, "ContentType": "image/webp"},
        ExpiresIn=300,
    )


def list_pending(event):
    return http.response(200, {"suggestions": db.list_suggestions("pending")})


def approve(event, sid):
    body = http.read_json(event) or {}
    item_id, name = body.get("item_id"), body.get("name")
    if not (isinstance(item_id, str) and _SLUG.match(item_id) and name):
        return http.response(400, {"error": "bad_request"})
    try:
        db.set_suggestion_status(sid, "approved")
    except db.NotFound:
        return http.response(404, {"error": "unknown_suggestion"})
    try:
        db.create_item(item_id, name, body.get("emoji", ""))
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return http.response(409, {"error": "item_exists"})
        raise
    return http.response(200, {"ok": True})


def reject(event, sid):
    try:
        db.set_suggestion_status(sid, "rejected")
    except db.NotFound:
        return http.response(404, {"error": "unknown_suggestion"})
    return http.response(200, {"ok": True})


def create_item(event):
    body = http.read_json(event) or {}
    item_id, name = body.get("item_id"), body.get("name")
    if not (isinstance(item_id, str) and _SLUG.match(item_id) and name):
        return http.response(400, {"error": "bad_request"})
    image_key = f"img/{item_id}.webp" if body.get("want_image") else None
    try:
        db.create_item(item_id, name, body.get("emoji", ""), image_key=image_key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return http.response(409, {"error": "item_exists"})
        raise
    return http.response(200, {"ok": True, "image_key": image_key,
                               "upload_url": _presign(image_key) if image_key else None})


def patch_item(event, item_id):
    body = http.read_json(event) or {}
    fields = {k: v for k, v in body.items()
              if k in {"name", "emoji", "status", "image_key"}}
    if not fields or ("status" in fields and fields["status"] not in {"active", "archived"}):
        return http.response(400, {"error": "bad_request"})
    try:
        db.update_item(item_id, **fields)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return http.response(404, {"error": "unknown_item"})
        raise
    return http.response(200, {"ok": True})


def dispatch(event, method, path, authorized):
    if not authorized:
        return http.response(401, {"error": "unauthorized"})
    parts = path.split("/")  # ['', 'api', 'admin', ...]
    if (method, path) == ("GET", "/api/admin/suggestions"):
        return list_pending(event)
    if method == "POST" and len(parts) == 6 and parts[3] == "suggestions":
        if parts[5] == "approve":
            return approve(event, parts[4])
        if parts[5] == "reject":
            return reject(event, parts[4])
    if (method, path) == ("POST", "/api/admin/items"):
        return create_item(event)
    if method == "PATCH" and len(parts) == 5 and parts[3] == "items":
        return patch_item(event, parts[4])
    return http.response(404, {"error": "not_found"})
```

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_routes_admin.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + commit**

```bash
cd backend && ../.venv/bin/pytest -q && cd ..
git add backend/ && git commit -m "feat: admin routes (queue, item CRUD, presigned uploads)"
```

---

### Task 8: Seed data, local server, dev script

**Files:**
- Create: `backend/seed/items.json`, `backend/seed.py`, `backend/local_server.py`, `scripts/local-dev.sh`

**Interfaces:**
- Consumes: `db.*`, `handler.lambda_handler`.
- Produces: `./scripts/local-dev.sh` → site + API on `http://localhost:8080` (API under `/api/*`, static files from `site/`, which Plan 2 fills). `python backend/seed.py --votes 200` adds demo votes.

- [ ] **Step 1: Write `backend/seed/items.json`** (draft content — Ariel edits freely later)

```json
[
  {"id": "friday-noon-wedding", "name": "חתונת שישי בצהריים", "emoji": "💍"},
  {"id": "soy-milk-coffee", "name": "קפה עם חלב סויה", "emoji": "🥛"},
  {"id": "going-to-theatre", "name": "ללכת לתיאטרון", "emoji": "🎭"},
  {"id": "fridge-magnets", "name": "מלא מגנטים על המקרר", "emoji": "🧲"},
  {"id": "keter-chairs", "name": "כיסאות כתר בגינה", "emoji": "🪑"},
  {"id": "home-sign", "name": "שלט HOME בכניסה לבית", "emoji": "🏠"},
  {"id": "kitchen-sign", "name": "שלט KITCHEN במטבח", "emoji": "🍳"},
  {"id": "stepup-competition", "name": "לנסות לנצח בסטפ־אפ", "emoji": "👟"},
  {"id": "zimmer-jacuzzi", "name": "צימר עם ג׳קוזי", "emoji": "🛁"},
  {"id": "homemade-kombucha", "name": "קומבוצ׳ה ביתית", "emoji": "🫙"},
  {"id": "friday-night-party", "name": "מסיבה בשישי בערב", "emoji": "🪩"},
  {"id": "park-bbq", "name": "מנגל בפארק הלאומי", "emoji": "🍖"},
  {"id": "berlin-vacation", "name": "חופשה בברלין", "emoji": "✈️"},
  {"id": "dubai-vacation", "name": "חופשה בדובאי", "emoji": "🏙️"},
  {"id": "vegan-food", "name": "אוכל טבעוני", "emoji": "🥦"},
  {"id": "focaccia-everywhere", "name": "פוקצ׳ה בכל מסעדה", "emoji": "🥖"},
  {"id": "shoresh-sandals", "name": "סנדלי שורש", "emoji": "🩴"},
  {"id": "car-trade-in", "name": "טרייד־אין כל שנתיים", "emoji": "🚗"},
  {"id": "sup-kinneret", "name": "סאפ בכנרת", "emoji": "🏄"},
  {"id": "adopted-dog", "name": "כלב מעורב מאומץ", "emoji": "🐕"},
  {"id": "pedigree-cat", "name": "חתול גזעי", "emoji": "🐈"},
  {"id": "black-coffee-glass", "name": "קפה שחור בכוס זכוכית", "emoji": "☕"},
  {"id": "corn-pizza", "name": "פיצה עם תירס", "emoji": "🌽"},
  {"id": "6am-workout", "name": "אימון כושר בשש בבוקר", "emoji": "🏋️"}
]
```

- [ ] **Step 2: Write `backend/seed.py`**

```python
"""Create the local table and load seed items. Optionally add demo votes.

Usage: TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 python seed.py [--votes N]
"""
import argparse
import json
import pathlib
import random
import sys

from app import db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--votes", type=int, default=0)
    args = parser.parse_args()

    import os
    db.ensure_table(os.environ["TABLE_NAME"])
    items = json.loads((pathlib.Path(__file__).parent / "seed" / "items.json").read_text())
    created = 0
    for it in items:
        try:
            db.create_item(it["id"], it["name"], it["emoji"])
            created += 1
        except Exception:
            pass  # already seeded — idempotent
    print(f"items: {created} created, {len(items) - created} already existed")

    for n in range(args.votes):
        uid = f"demo-{n}"
        for it in random.sample(items, k=random.randint(3, len(items))):
            choice = random.choices(["left", "right", "neutral"], weights=[45, 45, 10])[0]
            try:
                db.record_vote(uid, it["id"], choice)
            except db.AlreadyVoted:
                pass
    if args.votes:
        print(f"demo votes: {args.votes} visitors")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Write `backend/local_server.py`**

```python
"""Local dev server: /api/* → lambda_handler (synthesized API GW v2 events),
everything else → static files from ../site. NOT for production."""
import json
import os
import pathlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from app.handler import lambda_handler

SITE_DIR = pathlib.Path(__file__).resolve().parent.parent / "site"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def _api(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length).decode() if length else None
        cookies = []
        if self.headers.get("cookie"):
            cookies = [c.strip() for c in self.headers["cookie"].split(";")]
        event = {
            "rawPath": self.path.split("?")[0],
            "requestContext": {"http": {"method": self.command}},
            "cookies": cookies,
        }
        if body is not None:
            event["body"] = body
            event["isBase64Encoded"] = False
        resp = lambda_handler(event, None)
        payload = resp["body"].encode()
        self.send_response(resp["statusCode"])
        for k, v in resp.get("headers", {}).items():
            self.send_header(k, v)
        for c in resp.get("cookies", []):
            # local http:// can't set Secure cookies — strip the flag for dev only
            self.send_header("Set-Cookie", c.replace("; Secure", ""))
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _maybe_api(self, fallback):
        if self.path.split("?")[0].startswith("/api/"):
            self._api()
        else:
            fallback()

    def do_GET(self):
        self._maybe_api(super().do_GET)

    def do_POST(self):
        self._maybe_api(lambda: self.send_error(405))

    def do_PATCH(self):
        self._maybe_api(lambda: self.send_error(405))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"http://localhost:{port}  (site from {SITE_DIR}, /api/* → lambda_handler)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
```

- [ ] **Step 4: Write `scripts/local-dev.sh`**

```bash
#!/usr/bin/env bash
# Run the whole app locally: DynamoDB Local + seed + API/site server on :8080.
set -euo pipefail
cd "$(dirname "$0")/.."

export TABLE_NAME="${TABLE_NAME:-lr-local}"
export DDB_ENDPOINT="${DDB_ENDPOINT:-http://localhost:8000}"
export ALLOW_ADMIN="${ALLOW_ADMIN:-1}"   # local admin needs no login

docker compose up -d dynamodb
mkdir -p site
(cd backend && ../.venv/bin/python seed.py "$@")
exec .venv/bin/python backend/local_server.py
```

Then: `chmod +x scripts/local-dev.sh`

- [ ] **Step 5: Verify end-to-end with curl**

```bash
./scripts/local-dev.sh --votes 50 &   # leave running
sleep 3
curl -s localhost:8080/api/items | python3 -m json.tool | head -20
curl -si -X POST localhost:8080/api/vote \
  -d '{"item_id":"keter-chairs","choice":"right"}' | head -12
curl -s localhost:8080/api/admin/suggestions | python3 -m json.tool
```

Expected: items list with Hebrew names and non-zero counts; vote returns 200 + `set-cookie: lr_uid=...` + updated counts; admin list returns 200 (ALLOW_ADMIN=1). Then stop the server (`kill %1`).

- [ ] **Step 6: Full test suite + commit**

```bash
cd backend && ../.venv/bin/pytest -q && cd ..
git add backend/ scripts/ && git commit -m "feat: seed data, local dev server, dev script"
```

---

## Self-review notes

- Spec coverage (backend scope): items/votes/suggestions model ✓ (T2–4), conditional dedup ✓ (T3), atomic counters ✓ (T3), cookie contract ✓ (T5/T6), all public routes + caching header ✓ (T6), admin queue/CRUD/presign + auth gate ✓ (T7), rate caps ✓ (T4/T6), local-first platform + seed ✓ (T8). Cognito itself, CloudFront caching behavior, and WAF-alternatives are Plan 3 (infra); frontend consumption is Plan 2.
- `handler.py` imports `admin_routes` lazily so Task 6 tests pass before Task 7 exists — intentional ordering aid.
- Types/names cross-checked: `CHOICES`, exceptions, `apigw_event(admin=)`, response body shapes match between tasks.
