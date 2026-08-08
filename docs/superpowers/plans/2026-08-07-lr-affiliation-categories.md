# LR — Self-identification & Categories — Implementation Plan (3 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the one-time "האם אתה ימני או שמאלני?" card with cross-attribution stats, per-item categories with visitor filters, and a genuinely usable admin item manager — all running locally.

**Architecture:** Extends the merged Plan-1 backend (single DynamoDB table, one Python Lambda handler) and Plan-2 frontend (vanilla ES modules, no build step). New profile record per visitor, nine cross-tab counters per item, one new public endpoint and two new admin endpoints; frontend gains a special card type, a pure cross-attribution rule, and a category filter.

**Tech Stack:** Python 3.12+/boto3/pytest against DynamoDB Local; HTML/CSS/vanilla ES modules; headless Chromium for visual verification.

**Spec:** `docs/superpowers/specs/2026-08-07-lr-affiliation-categories-design.md`. Base design: `docs/superpowers/specs/2026-08-06-lr-voting-site-design.md`.

## Global Constraints

- Hebrew copy EXACT: question title `האם אתה ימני או שמאלני?`; neutral strip on that card `מרכז משעמם ↓`; cross-attribution lines `NN% מהימנים חושבים שזה שמאלני` and `NN% מהשמאלנים חושבים שזה ימני`; empty-filter message `בחרו לפחות קטגוריה אחת`; admin archive toggle labels `ארכוב` / `שחזור`; admin archived-visibility checkbox `הצג בארכיון`.
- Affiliation values exactly `right` | `left` | `center`. Vote choices remain `left` | `right` | `neutral`.
- Cross-tab counter attribute names exactly `xt_<affiliation>_<choice>` (9 per item), all ints defaulting to 0.
- Profile record exactly `PK=USER#<uid>`, `SK=PROFILE`, attrs `affiliation`, `ts`. Global tallies exactly `PK=STATS`, `SK=AFFILIATION`, attrs `affil_right` / `affil_left` / `affil_center`.
- Category slugs exactly: `events travel food home consumer social sport movies tv conspiracy other`; labels exactly: אירועים, חופשות וטיולים, אוכל, בית, צרכנות, חברתי, ספורט, סרטים, תוכניות טלוויזיה, תיאוריות קונספירציה, אחר. Default `other`.
- Cross-attribution rule: per camp, `decisive = xt_<camp>_left + xt_<camp>_right`; show when `decisive >= 25` AND opposite-share `> 0.70`. Constants `XT_MIN_CAMP_VOTES = 25`, `XT_CROSS_THRESHOLD = 0.70`. Neutral excluded from the percentage. Viewer must have an affiliation. Both lines may show at once. Never show a camp claiming an item as its own.
- Image keys are `img/<item_id>-<epoch>.webp` (timestamped), never the un-suffixed form.
- Existing behaviour that must not regress: `esc()` on every user-controlled interpolation; `submitting` in-flight guard on votes; the `hidden` class contract that `gestures.js` relies on; `GET /api/items` cache header `public, max-age=30` and everything else `no-store`.
- Backend: stdlib + boto3 only. Frontend: no frameworks, no build step, no external requests.
- All commands run from repo root `/home/latnook/Documents/LR2026` unless stated. Tests: `cd backend && ../.venv/bin/pytest -q` (DynamoDB Local: `docker compose up -d dynamodb`).
- Local run for visual checks: `TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ALLOW_ADMIN=1 .venv/bin/python backend/local_server.py` (PORT=8081 if 8080 busy). Screenshots to `/tmp/claude-1000/-home-latnook-Documents-LR2026/7a82793f-40ca-41f0-9458-345ed55ad528/scratchpad/`.

## File Structure

```
backend/app/
├── categories.py     # NEW: canonical slug→label list + validation helper
├── db.py             # MOD: category on items, xt_ counters, profile record, backfill, admin listing
├── handler.py        # MOD: /api/affiliation route; affiliation in /api/me; categories in /api/items
└── admin_routes.py   # MOD: category on create/approve/patch; GET admin items; image endpoint
backend/seed/items.json   # MOD: category per seeded item
backend/tests/
├── test_db_profile.py    # NEW: affiliation + backfill + xt counters
├── test_categories.py    # NEW: category validation/defaults
├── test_routes_public.py # MOD: /api/affiliation, /api/me affiliation, /api/items shape
└── test_routes_admin.py  # MOD: category fields, admin item listing, image endpoint, restore
site/js/
├── crosstab.js       # NEW: pure cross-attribution rule (single exported function)
├── affiliation.js    # NEW: the 🫵 card — render, submit, its own reveal
├── deck.js           # MOD: category filter, question interleaving, cross-attribution line
├── panels.js         # MOD: קטגוריות filter section in the ☰ panel
└── app.js            # MOD: wire the new modules
site/css/app.css      # MOD: styles for the filter list and the cross-attribution line
site/admin/admin.js   # MOD: category selects, grouped+editable item rows, image replace, restore
site/admin/admin.css  # MOD: row-edit layout, group headers, dimmed archived rows
site/admin/index.html # MOD: category select in create form, הצג בארכיון checkbox
```

---

### Task 1: Categories module + item category field

**Files:**
- Create: `backend/app/categories.py`, `backend/tests/test_categories.py`
- Modify: `backend/app/db.py` (`_to_item_dict`, `create_item`, `update_item` whitelist)

**Interfaces:**
- Produces: `categories.CATEGORIES` (ordered list of `{"slug","label"}` dicts), `categories.SLUGS` (set), `categories.DEFAULT = "other"`, `categories.is_valid(slug) -> bool`. `create_item(item_id, name, emoji, image_key=None, category="other")`; item dicts gain `"category"`; `update_item` accepts `category`.

- [ ] **Step 1: Write `backend/app/categories.py`**

```python
"""Canonical category list. Single source of truth — the frontend renders whatever this serves."""

CATEGORIES = [
    {"slug": "events", "label": "אירועים"},
    {"slug": "travel", "label": "חופשות וטיולים"},
    {"slug": "food", "label": "אוכל"},
    {"slug": "home", "label": "בית"},
    {"slug": "consumer", "label": "צרכנות"},
    {"slug": "social", "label": "חברתי"},
    {"slug": "sport", "label": "ספורט"},
    {"slug": "movies", "label": "סרטים"},
    {"slug": "tv", "label": "תוכניות טלוויזיה"},
    {"slug": "conspiracy", "label": "תיאוריות קונספירציה"},
    {"slug": "other", "label": "אחר"},
]

SLUGS = {c["slug"] for c in CATEGORIES}
DEFAULT = "other"


def is_valid(slug):
    return isinstance(slug, str) and slug in SLUGS
```

- [ ] **Step 2: Write failing tests in `backend/tests/test_categories.py`**

```python
from app import categories, db


def test_category_list_shape():
    assert categories.DEFAULT == "other"
    assert len(categories.CATEGORIES) == 11
    assert categories.CATEGORIES[0] == {"slug": "events", "label": "אירועים"}
    assert {c["slug"] for c in categories.CATEGORIES} == categories.SLUGS
    assert all(c["label"].strip() for c in categories.CATEGORIES)


def test_is_valid():
    assert categories.is_valid("food")
    assert categories.is_valid("other")
    assert not categories.is_valid("nope")
    assert not categories.is_valid(None)
    assert not categories.is_valid(123)


def test_create_item_defaults_to_other(fresh_table):
    db.create_item("a", "א", "🅰️")
    assert db.get_item("a")["category"] == "other"


def test_create_item_with_category(fresh_table):
    db.create_item("bbq", "מנגל", "🍖", category="food")
    assert db.get_item("bbq")["category"] == "food"


def test_update_item_can_refile(fresh_table):
    db.create_item("bbq", "מנגל", "🍖", category="food")
    db.update_item("bbq", category="events")
    assert db.get_item("bbq")["category"] == "events"


def test_legacy_record_without_category_reads_as_other(fresh_table):
    db.table().put_item(
        Item={
            "PK": "ITEM#legacy", "SK": "META", "name": "ישן", "emoji": "🗿",
            "status": "active", "votes_left": 0, "votes_right": 0, "votes_neutral": 0,
        }
    )
    assert db.get_item("legacy")["category"] == "other"
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_categories.py -v`
Expected: FAIL — `create_item() got an unexpected keyword argument 'category'` / missing `"category"` key.

- [ ] **Step 4: Implement in `backend/app/db.py`**

Add the import at the top with the other app imports:

```python
from app import categories
```

In `_to_item_dict`, add the category line (defensive default so legacy records never fall out of the deck):

```python
        "category": record.get("category", categories.DEFAULT),
```

Change the `create_item` signature and record:

```python
def create_item(item_id, name, emoji, image_key=None, category=categories.DEFAULT):
```

and inside the record literal add:

```python
        "category": category if categories.is_valid(category) else categories.DEFAULT,
```

In `update_item`, extend the whitelist:

```python
    allowed = {"name", "emoji", "image_key", "status", "category"}
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_categories.py -v`
Expected: all PASS.

- [ ] **Step 6: Full suite + commit**

```bash
cd backend && ../.venv/bin/pytest -q && cd ..
git add backend/ && git commit -m "feat(api): item categories with canonical list and safe defaults"
```

---

### Task 2: Profile record, cross-tab counters, back-fill

**Files:**
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_db_profile.py` (create)

**Interfaces:**
- Consumes: `create_item`, `get_item`, `record_vote`, `get_user_votes` (existing).
- Produces:
  - `db.AFFILIATIONS = {"right", "left", "center"}`
  - `db.get_affiliation(uid) -> str|None`
  - `db.set_affiliation(uid, affiliation) -> dict` — conditional; raises `AlreadyVoted` if already set, `KeyError` for an invalid value; back-fills the visitor's existing votes into `xt_*`; returns global tallies `{"right": int, "left": int, "center": int}`
  - `db.get_affiliation_stats() -> dict` — same shape
  - `record_vote` now also increments `xt_<aff>_<choice>` when the voter has an affiliation
  - item dicts gain all nine `xt_*` keys as ints

- [ ] **Step 1: Write failing tests in `backend/tests/test_db_profile.py`**

```python
import pytest

from app import db


def test_affiliation_absent_by_default(fresh_table):
    assert db.get_affiliation("u1") is None


def test_set_and_get_affiliation(fresh_table):
    stats = db.set_affiliation("u1", "right")
    assert db.get_affiliation("u1") == "right"
    assert stats == {"right": 1, "left": 0, "center": 0}


def test_set_affiliation_is_once_only(fresh_table):
    db.set_affiliation("u1", "right")
    with pytest.raises(db.AlreadyVoted):
        db.set_affiliation("u1", "left")
    assert db.get_affiliation("u1") == "right"


def test_invalid_affiliation_raises(fresh_table):
    with pytest.raises(KeyError):
        db.set_affiliation("u1", "centrist")


def test_global_stats_tally(fresh_table):
    db.set_affiliation("u1", "right")
    db.set_affiliation("u2", "right")
    db.set_affiliation("u3", "center")
    assert db.get_affiliation_stats() == {"right": 2, "left": 0, "center": 1}


def test_item_exposes_zeroed_crosstab_counters(fresh_table):
    db.create_item("a", "א", "🅰️")
    item = db.get_item("a")
    for aff in ("right", "left", "center"):
        for choice in ("left", "right", "neutral"):
            assert item[f"xt_{aff}_{choice}"] == 0


def test_vote_with_affiliation_increments_crosstab(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.set_affiliation("u1", "right")
    item = db.record_vote("u1", "a", "left")
    assert item["votes_left"] == 1
    assert item["xt_right_left"] == 1
    assert item["xt_left_left"] == 0


def test_vote_without_affiliation_touches_only_main_counters(fresh_table):
    db.create_item("a", "א", "🅰️")
    item = db.record_vote("anon", "a", "left")
    assert item["votes_left"] == 1
    assert all(item[f"xt_{a}_left"] == 0 for a in ("right", "left", "center"))


def test_answering_backfills_earlier_votes(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.create_item("b", "ב", "🅱️")
    db.create_item("c", "ג", "🅲")
    db.record_vote("u1", "a", "left")
    db.record_vote("u1", "b", "right")
    db.record_vote("u1", "c", "neutral")
    db.set_affiliation("u1", "right")
    assert db.get_item("a")["xt_right_left"] == 1
    assert db.get_item("b")["xt_right_right"] == 1
    assert db.get_item("c")["xt_right_neutral"] == 1
    assert db.get_item("a")["xt_left_left"] == 0


def test_backfill_does_not_touch_other_voters_counters(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.record_vote("other", "a", "left")
    db.record_vote("u1", "a", "left")
    db.set_affiliation("u1", "left")
    assert db.get_item("a")["xt_left_left"] == 1
    assert db.get_item("a")["votes_left"] == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_profile.py -v`
Expected: FAIL — `module 'app.db' has no attribute 'get_affiliation'`.

- [ ] **Step 3: Implement in `backend/app/db.py`**

Add near `CHOICES` at the top:

```python
AFFILIATIONS = ("right", "left", "center")


def _xt_attr(affiliation, choice):
    """Cross-tab counter name, e.g. xt_right_left = ימנים who voted שמאלני."""
    if affiliation not in AFFILIATIONS or choice not in CHOICES:
        raise KeyError((affiliation, choice))
    return f"xt_{affiliation}_{choice}"
```

In `_to_item_dict`, after the existing counters, add the nine:

```python
    for aff in AFFILIATIONS:
        for choice in CHOICES:
            key = f"xt_{aff}_{choice}"
            d[key] = int(record.get(key, 0))
```

Append the profile functions:

```python
def get_affiliation(uid):
    resp = table().get_item(Key={"PK": f"USER#{uid}", "SK": "PROFILE"})
    record = resp.get("Item")
    return record["affiliation"] if record else None


def get_affiliation_stats():
    resp = table().get_item(Key={"PK": "STATS", "SK": "AFFILIATION"})
    record = resp.get("Item") or {}
    return {aff: int(record.get(f"affil_{aff}", 0)) for aff in AFFILIATIONS}


def set_affiliation(uid, affiliation):
    """Claim the visitor's affiliation (once only), then back-fill their earlier votes."""
    if affiliation not in AFFILIATIONS:
        raise KeyError(affiliation)
    try:
        table().put_item(
            Item={
                "PK": f"USER#{uid}",
                "SK": "PROFILE",
                "affiliation": affiliation,
                "ts": int(time.time()),
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise AlreadyVoted(uid) from e
        raise

    table().update_item(
        Key={"PK": "STATS", "SK": "AFFILIATION"},
        UpdateExpression=f"ADD affil_{affiliation} :one",
        ExpressionAttributeValues={":one": 1},
    )

    # Back-fill: attribute votes cast before the visitor identified themselves.
    for item_id, choice in get_user_votes(uid).items():
        try:
            table().update_item(
                Key={"PK": f"ITEM#{item_id}", "SK": "META"},
                UpdateExpression=f"ADD {_xt_attr(affiliation, choice)} :one",
                ExpressionAttributeValues={":one": 1},
                ConditionExpression="attribute_exists(PK)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise  # item vanished mid-backfill: skip it, stats are approximate

    return get_affiliation_stats()
```

In `record_vote`, add the affiliation read and extend the counter update. Replace the counter line

```python
    counter = CHOICES[choice]  # KeyError on invalid choice, before any write
```

with

```python
    counter = CHOICES[choice]  # KeyError on invalid choice, before any write
    affiliation = get_affiliation(uid)
    add_expr = f"ADD {counter} :one"
    if affiliation:
        add_expr += f", {_xt_attr(affiliation, choice)} :one"
```

and in the transaction's `Update` entry replace `"UpdateExpression": f"ADD {counter} :one",` with

```python
                    "UpdateExpression": add_expr,
```

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_db_profile.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + commit**

```bash
cd backend && ../.venv/bin/pytest -q && cd ..
git add backend/ && git commit -m "feat(api): visitor affiliation, cross-tab counters, retroactive back-fill"
```

---

### Task 3: Public API — affiliation endpoint, /api/me, /api/items shape

**Files:**
- Modify: `backend/app/handler.py`
- Test: `backend/tests/test_routes_public.py` (append)

**Interfaces:**
- Consumes: Task 1 (`categories`), Task 2 (`db.set_affiliation`, `db.get_affiliation`).
- Produces:
  - `GET /api/items` → `{"items": [...], "categories": [{"slug","label"}, ...]}`, cache `public, max-age=30`
  - `GET /api/me` → `{"votes": {...}, "affiliation": "right"|"left"|"center"|null}`
  - `POST /api/affiliation` `{choice}` → `200 {"affiliation": c, "stats": {right,left,center}}` | `400 {"error":"bad_choice"}` | `409 {"error":"already_answered"}`

- [ ] **Step 1: Write failing tests (append to `backend/tests/test_routes_public.py`)**

```python
def test_items_includes_categories_and_crosstabs(fresh_table):
    db.create_item("bbq", "מנגל", "🍖", category="food")
    resp, body = call(apigw_event("GET", "/api/items"))
    assert resp["statusCode"] == 200
    assert body["items"][0]["category"] == "food"
    assert body["items"][0]["xt_right_left"] == 0
    assert {"slug": "food", "label": "אוכל"} in body["categories"]
    assert len(body["categories"]) == 11


def test_me_reports_affiliation(fresh_table):
    resp, body = call(apigw_event("GET", "/api/me"))
    assert body["affiliation"] is None
    uid_cookie = resp["cookies"][0].split(";")[0]
    call(apigw_event("POST", "/api/affiliation", cookies=[uid_cookie], body={"choice": "left"}))
    _, body2 = call(apigw_event("GET", "/api/me", cookies=[uid_cookie]))
    assert body2["affiliation"] == "left"


def test_affiliation_post_returns_stats_and_sets_cookie(fresh_table):
    resp, body = call(apigw_event("POST", "/api/affiliation", body={"choice": "center"}))
    assert resp["statusCode"] == 200
    assert body["affiliation"] == "center"
    assert body["stats"] == {"right": 0, "left": 0, "center": 1}
    assert resp["cookies"][0].startswith("lr_uid=")
    assert resp["headers"]["cache-control"] == "no-store"


def test_affiliation_second_answer_409(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/affiliation", body={"choice": "right"}))
    uid_cookie = resp["cookies"][0].split(";")[0]
    resp2, body2 = call(apigw_event("POST", "/api/affiliation", cookies=[uid_cookie],
                                    body={"choice": "left"}))
    assert resp2["statusCode"] == 409 and body2["error"] == "already_answered"


def test_affiliation_bad_input_400(fresh_table):
    assert call(apigw_event("POST", "/api/affiliation", body={"choice": "centrist"}))[0]["statusCode"] == 400
    assert call(apigw_event("POST", "/api/affiliation", body={"choice": ["left"]}))[0]["statusCode"] == 400
    assert call(apigw_event("POST", "/api/affiliation", body={}))[0]["statusCode"] == 400


def test_vote_after_affiliation_feeds_crosstab_through_api(fresh_table):
    db.create_item("bbq", "מנגל", "🍖", category="food")
    resp, _ = call(apigw_event("POST", "/api/affiliation", body={"choice": "right"}))
    uid_cookie = resp["cookies"][0].split(";")[0]
    _, body = call(apigw_event("POST", "/api/vote", cookies=[uid_cookie],
                               body={"item_id": "bbq", "choice": "left"}))
    assert body["item"]["xt_right_left"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_routes_public.py -v -k "categories or affiliation or crosstab"`
Expected: FAIL — 404 for `/api/affiliation`, missing `categories` key.

- [ ] **Step 3: Implement in `backend/app/handler.py`**

Extend the imports:

```python
from app import categories, db, http
```

Replace `get_items` and `get_me` with:

```python
def get_items(event):
    return http.response(
        200,
        {"items": db.list_active_items(), "categories": categories.CATEGORIES},
        cache="public, max-age=30",
    )


def get_me(event):
    uid, cookie = _uid(event)
    votes = {} if cookie else db.get_user_votes(uid)
    affiliation = None if cookie else db.get_affiliation(uid)
    return http.response(
        200,
        {"votes": votes, "affiliation": affiliation},
        cookies=[cookie] if cookie else None,
    )
```

Add the new route function after `post_suggest`:

```python
def post_affiliation(event):
    body = http.read_json(event) or {}
    choice = body.get("choice")
    if not isinstance(choice, str) or choice not in db.AFFILIATIONS:
        return http.response(400, {"error": "bad_choice"})
    uid, cookie = _uid(event)
    cookies = [cookie] if cookie else None
    try:
        stats = db.set_affiliation(uid, choice)
    except db.AlreadyVoted:
        return http.response(409, {"error": "already_answered"}, cookies=cookies)
    return http.response(200, {"affiliation": choice, "stats": stats}, cookies=cookies)
```

Register it in `PUBLIC_ROUTES`:

```python
    ("POST", "/api/affiliation"): post_affiliation,
```

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_routes_public.py -v`
Expected: all PASS (existing tests included — `/api/me` gained a key but no existing assertion breaks).

- [ ] **Step 5: Full suite + commit**

```bash
cd backend && ../.venv/bin/pytest -q && cd ..
git add backend/ && git commit -m "feat(api): affiliation endpoint, categories in items, affiliation in me"
```

---

### Task 4: Admin API — categories, full listing, image endpoint, restore

**Files:**
- Modify: `backend/app/admin_routes.py`
- Test: `backend/tests/test_routes_admin.py` (append)

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `POST /api/admin/items` accepts `category`; image key `img/<id>-<epoch>.webp`
  - `POST /api/admin/suggestions/<sid>/approve` accepts `category`
  - `PATCH /api/admin/items/<id>` accepts `category`, and `status` in both directions
  - `GET /api/admin/items` → `{"items":[...]}` including archived, `no-store`
  - `POST /api/admin/items/<id>/image` → `{"image_key": str, "upload_url": str|null}`, `404` unknown item
- Also produces in `db.py`: `db.list_all_items() -> list[dict]` (active + archived, sorted by id).

- [ ] **Step 1: Write failing tests (append to `backend/tests/test_routes_admin.py`)**

```python
def test_create_item_with_category(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True,
                               body={"item_id": "bbq", "name": "מנגל", "emoji": "🍖",
                                     "category": "food"}))
    assert resp["statusCode"] == 200
    assert db.get_item("bbq")["category"] == "food"


def test_create_item_bad_category_400(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True,
                               body={"item_id": "x", "name": "א", "emoji": "🅰️",
                                     "category": "nope"}))
    assert resp["statusCode"] == 400


def test_create_item_without_category_defaults_other(fresh_table):
    call(apigw_event("POST", "/api/admin/items", admin=True,
                     body={"item_id": "x", "name": "א", "emoji": "🅰️"}))
    assert db.get_item("x")["category"] == "other"


def test_approve_with_category(fresh_table):
    sid = db.add_suggestion("u1", "פיצה עם תירס")
    resp, _ = call(apigw_event("POST", f"/api/admin/suggestions/{sid}/approve", admin=True,
                               body={"item_id": "corn-pizza", "name": "פיצה עם תירס",
                                     "emoji": "🌽", "category": "food"}))
    assert resp["statusCode"] == 200
    assert db.get_item("corn-pizza")["category"] == "food"


def test_patch_category_and_restore(fresh_table):
    db.create_item("a", "א", "🅰️", category="home")
    call(apigw_event("PATCH", "/api/admin/items/a", admin=True, body={"category": "food"}))
    assert db.get_item("a")["category"] == "food"
    call(apigw_event("PATCH", "/api/admin/items/a", admin=True, body={"status": "archived"}))
    assert db.get_item("a")["status"] == "archived"
    resp, _ = call(apigw_event("PATCH", "/api/admin/items/a", admin=True,
                               body={"status": "active"}))
    assert resp["statusCode"] == 200
    assert db.get_item("a")["status"] == "active"


def test_patch_bad_category_400(fresh_table):
    db.create_item("a", "א", "🅰️")
    assert call(apigw_event("PATCH", "/api/admin/items/a", admin=True,
                            body={"category": "nope"}))[0]["statusCode"] == 400


def test_admin_items_includes_archived(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.create_item("b", "ב", "🅱️")
    db.update_item("b", status="archived")
    resp, body = call(apigw_event("GET", "/api/admin/items", admin=True))
    assert resp["statusCode"] == 200
    assert resp["headers"]["cache-control"] == "no-store"
    assert [i["id"] for i in body["items"]] == ["a", "b"]
    _, public = call(apigw_event("GET", "/api/items"))
    assert [i["id"] for i in public["items"]] == ["a"]


def test_admin_items_requires_auth(fresh_table):
    assert call(apigw_event("GET", "/api/admin/items"))[0]["statusCode"] == 401


def test_image_endpoint_returns_timestamped_key(fresh_table, monkeypatch):
    monkeypatch.setenv("IMG_BUCKET", "lr-fake-bucket")
    db.create_item("bbq", "מנגל", "🍖")
    resp, body = call(apigw_event("POST", "/api/admin/items/bbq/image", admin=True))
    assert resp["statusCode"] == 200
    assert body["image_key"].startswith("img/bbq-") and body["image_key"].endswith(".webp")
    assert "lr-fake-bucket" in body["upload_url"]


def test_image_endpoint_without_bucket(fresh_table):
    db.create_item("bbq", "מנגל", "🍖")
    _, body = call(apigw_event("POST", "/api/admin/items/bbq/image", admin=True))
    assert body["upload_url"] is None
    assert body["image_key"].startswith("img/bbq-")


def test_image_endpoint_unknown_item_404(fresh_table):
    assert call(apigw_event("POST", "/api/admin/items/ghost/image", admin=True))[0]["statusCode"] == 404


def test_create_item_image_key_is_timestamped(fresh_table):
    _, body = call(apigw_event("POST", "/api/admin/items", admin=True,
                               body={"item_id": "bbq", "name": "מנגל", "emoji": "🍖",
                                     "want_image": True}))
    assert body["image_key"].startswith("img/bbq-") and body["image_key"].endswith(".webp")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ../.venv/bin/pytest tests/test_routes_admin.py -v -k "category or archived or image or restore"`
Expected: FAIL — 404 on the new routes, category ignored.

- [ ] **Step 3: Add `list_all_items` to `backend/app/db.py`**

```python
def list_all_items():
    """Every item including archived — admin listing only."""
    items, kwargs = [], {}
    while True:
        resp = table().scan(
            FilterExpression="SK = :meta",
            ExpressionAttributeValues={":meta": "META"},
            **kwargs,
        )
        items.extend(_to_item_dict(r) for r in resp["Items"])
        if "LastEvaluatedKey" not in resp:
            return sorted(items, key=lambda i: i["id"])
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
```

- [ ] **Step 4: Implement in `backend/app/admin_routes.py`**

Extend imports and add a key helper:

```python
import time

from app import categories, db, http
```

```python
def _image_key(item_id):
    """Timestamped so a replacement never collides with a cached object."""
    return f"img/{item_id}-{int(time.time())}.webp"
```

In `approve`, after the existing `item_id`/`name` validation, add category handling and pass it through:

```python
    category = body.get("category", categories.DEFAULT)
    if not categories.is_valid(category):
        return http.response(400, {"error": "bad_category"})
```

and change the create call to `db.create_item(item_id, name, body.get("emoji", ""), category=category)`.

In `create_item`, same validation after the id/name check:

```python
    category = body.get("category", categories.DEFAULT)
    if not categories.is_valid(category):
        return http.response(400, {"error": "bad_category"})
    image_key = _image_key(item_id) if body.get("want_image") else None
```

and change the create call to `db.create_item(item_id, name, body.get("emoji", ""), image_key=image_key, category=category)`.

In `patch_item`, validate category when present (the whitelist already accepts it via Task 1):

```python
    if "category" in fields and not categories.is_valid(fields["category"]):
        return http.response(400, {"error": "bad_category"})
```

Add the two new route functions:

```python
def list_items(event):
    return http.response(200, {"items": db.list_all_items()})


def item_image(event, item_id):
    if db.get_item(item_id) is None:
        return http.response(404, {"error": "unknown_item"})
    key = _image_key(item_id)
    return http.response(200, {"image_key": key, "upload_url": _presign(key)})
```

Wire them into `dispatch`, before the existing `PATCH` clause:

```python
    if (method, path) == ("GET", "/api/admin/items"):
        return list_items(event)
    if method == "POST" and len(parts) == 6 and parts[3] == "items" and parts[5] == "image":
        return item_image(event, parts[4])
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/test_routes_admin.py -v`
Expected: all PASS.

- [ ] **Step 6: Full suite + commit**

```bash
cd backend && ../.venv/bin/pytest -q && cd ..
git add backend/ && git commit -m "feat(api): admin categories, full item listing, image replace, restore"
```

---

### Task 5: Seed categories

**Files:**
- Modify: `backend/seed/items.json`, `backend/seed.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: every seeded item carries a `category`; `seed.py` passes it through.

- [ ] **Step 1: Rewrite `backend/seed/items.json` with categories**

```json
[
  {"id": "friday-noon-wedding", "name": "חתונת שישי בצהריים", "emoji": "💍", "category": "events"},
  {"id": "soy-milk-coffee", "name": "קפה עם חלב סויה", "emoji": "🥛", "category": "food"},
  {"id": "going-to-theatre", "name": "ללכת לתיאטרון", "emoji": "🎭", "category": "events"},
  {"id": "fridge-magnets", "name": "מלא מגנטים על המקרר", "emoji": "🧲", "category": "home"},
  {"id": "keter-chairs", "name": "כיסאות כתר בגינה", "emoji": "🪑", "category": "home"},
  {"id": "home-sign", "name": "שלט HOME בכניסה לבית", "emoji": "🏠", "category": "home"},
  {"id": "kitchen-sign", "name": "שלט KITCHEN במטבח", "emoji": "🍳", "category": "home"},
  {"id": "stepup-competition", "name": "לנסות לנצח בסטפ־אפ", "emoji": "👟", "category": "sport"},
  {"id": "zimmer-jacuzzi", "name": "צימר עם ג׳קוזי", "emoji": "🛁", "category": "travel"},
  {"id": "homemade-kombucha", "name": "קומבוצ׳ה ביתית", "emoji": "🫙", "category": "food"},
  {"id": "friday-night-party", "name": "מסיבה בשישי בערב", "emoji": "🪩", "category": "events"},
  {"id": "park-bbq", "name": "מנגל בפארק הלאומי", "emoji": "🍖", "category": "food"},
  {"id": "berlin-vacation", "name": "חופשה בברלין", "emoji": "✈️", "category": "travel"},
  {"id": "dubai-vacation", "name": "חופשה בדובאי", "emoji": "🏙️", "category": "travel"},
  {"id": "vegan-food", "name": "אוכל טבעוני", "emoji": "🥦", "category": "food"},
  {"id": "focaccia-everywhere", "name": "פוקצ׳ה בכל מסעדה", "emoji": "🥖", "category": "food"},
  {"id": "shoresh-sandals", "name": "סנדלי שורש", "emoji": "🩴", "category": "consumer"},
  {"id": "car-trade-in", "name": "טרייד־אין כל שנתיים", "emoji": "🚗", "category": "consumer"},
  {"id": "sup-kinneret", "name": "סאפ בכנרת", "emoji": "🏄", "category": "sport"},
  {"id": "adopted-dog", "name": "כלב מעורב מאומץ", "emoji": "🐕", "category": "social"},
  {"id": "pedigree-cat", "name": "חתול גזעי", "emoji": "🐈", "category": "social"},
  {"id": "black-coffee-glass", "name": "קפה שחור בכוס זכוכית", "emoji": "☕", "category": "food"},
  {"id": "corn-pizza", "name": "פיצה עם תירס", "emoji": "🌽", "category": "food"},
  {"id": "6am-workout", "name": "אימון כושר בשש בבוקר", "emoji": "🏋️", "category": "sport"}
]
```

- [ ] **Step 2: Pass the category through in `backend/seed.py`**

Change the create call inside the seeding loop to:

```python
            db.create_item(it["id"], it["name"], it["emoji"],
                           category=it.get("category", "other"))
```

- [ ] **Step 3: Verify against a fresh table**

```bash
docker compose up -d dynamodb
cd backend && TABLE_NAME=lr-seedcheck DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python seed.py && cd ..
```

Then confirm the categories landed and no item is uncategorised:

```bash
cd backend && TABLE_NAME=lr-seedcheck DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python -c "
from app import db
items = db.list_active_items()
from collections import Counter
print(Counter(i['category'] for i in items))
print('uncategorised:', [i['id'] for i in items if i['category'] == 'other'])
" && cd ..
```

Expected: 24 items across food/home/travel/events/sport/consumer/social, `uncategorised: []`.

- [ ] **Step 4: Commit**

```bash
git add backend/ && git commit -m "feat(seed): categorise the 24 seed items"
```

---

### Task 6: Frontend — cross-attribution rule + category-aware deck

**Files:**
- Create: `site/js/crosstab.js`
- Modify: `site/js/deck.js`, `site/css/app.css`

**Interfaces:**
- Produces: `crosstab.js` exports `crossAttributionLines(item) -> string[]` (0–2 Hebrew strings) and the constants `XT_MIN_CAMP_VOTES`, `XT_CROSS_THRESHOLD`.
- `deck.js` gains: `setCategories(slugs)` (array of selected slugs, rebuilds the queue), `getCategories() -> string[]`, `getAllCategories() -> [{slug,label}]`, and `getState()` additionally exposes `affiliation`.

- [ ] **Step 1: Write `site/js/crosstab.js`**

```javascript
// Cross-attribution: show a line only when a camp overwhelmingly assigns an item
// to the OPPOSITE camp. A camp claiming an item as its own carries no tension.
export const XT_MIN_CAMP_VOTES = 25;
export const XT_CROSS_THRESHOLD = 0.7;

function share(item, camp, choice) {
  const decisive = (item[`xt_${camp}_left`] || 0) + (item[`xt_${camp}_right`] || 0);
  if (decisive < XT_MIN_CAMP_VOTES) return null;
  return { pct: (item[`xt_${camp}_${choice}`] || 0) / decisive, decisive };
}

export function crossAttributionLines(item) {
  const lines = [];
  const rightSaysLeft = share(item, "right", "left");
  if (rightSaysLeft && rightSaysLeft.pct > XT_CROSS_THRESHOLD) {
    lines.push(`${Math.round(rightSaysLeft.pct * 100)}% מהימנים חושבים שזה שמאלני`);
  }
  const leftSaysRight = share(item, "left", "right");
  if (leftSaysRight && leftSaysRight.pct > XT_CROSS_THRESHOLD) {
    lines.push(`${Math.round(leftSaysRight.pct * 100)}% מהשמאלנים חושבים שזה ימני`);
  }
  return lines;
}
```

- [ ] **Step 2: Verify the rule against boundary inputs**

```bash
cd site && node --input-type=module -e "
import('./js/crosstab.js').then(({crossAttributionLines}) => {
  const mk = (o) => Object.assign(
    {xt_right_left:0,xt_right_right:0,xt_right_neutral:0,
     xt_left_left:0,xt_left_right:0,xt_left_neutral:0,
     xt_center_left:0,xt_center_right:0,xt_center_neutral:0}, o);
  console.log('24 decisive, 100%:', crossAttributionLines(mk({xt_right_left:24})));
  console.log('25 decisive, exactly 70%:', crossAttributionLines(mk({xt_right_left:70,xt_right_right:30})));
  console.log('25 decisive, 71%:', crossAttributionLines(mk({xt_right_left:71,xt_right_right:29})));
  console.log('camp claims own:', crossAttributionLines(mk({xt_right_right:30,xt_right_left:0})));
  console.log('both disown:', crossAttributionLines(mk({xt_right_left:30,xt_right_right:5,xt_left_right:30,xt_left_left:5})));
});
" && cd ..
```

Expected exactly: `[]` (below sample), `[]` (70% is not > 70%), one ימנים line, `[]` (own-camp claim shows nothing), two lines (both camps disown).

- [ ] **Step 3: Add the cross-attribution line to the reveal in `site/js/deck.js`**

Add the import at the top:

```javascript
import { crossAttributionLines } from "./crosstab.js";
```

In `revealHTML(item, myChoice)`, build the extra markup before the `return` and insert it after the neutral-count div:

```javascript
  const xtLines = state.affiliation ? crossAttributionLines(item) : [];
  const xtHTML = xtLines.map((l) => `<div class="xt-line">${esc(l)}</div>`).join("");
```

and inside the returned template, immediately after the `<div class="neutral-count">…</div>` line:

```javascript
    ${xtHTML}
```

- [ ] **Step 4: Add category filtering + affiliation to state in `site/js/deck.js`**

Extend the `state` object with:

```javascript
  affiliation: null,     // "right" | "left" | "center" | null
  allCategories: [],     // [{slug,label}] from the API
  selected: null,        // Set of selected slugs; null means "all"
```

Add the storage helpers and exports near the other exports:

```javascript
const CATS_KEY = "lr_cats";

function loadSelected() {
  try {
    const raw = localStorage.getItem(CATS_KEY);
    return raw ? new Set(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

export const getAllCategories = () => state.allCategories;
export const getCategories = () =>
  state.selected ? [...state.selected] : state.allCategories.map((c) => c.slug);

export function setCategories(slugs) {
  state.selected = new Set(slugs);
  try {
    localStorage.setItem(CATS_KEY, JSON.stringify([...state.selected]));
  } catch {
    /* private mode: filter still applies for this session */
  }
  rebuildQueue();
  showNextCard();
}

function inSelection(item) {
  return !state.selected || state.selected.has(item.category);
}

function rebuildQueue() {
  state.queue = shuffle(
    state.items.filter((i) => inSelection(i) && !(i.id in state.votes)).map((i) => i.id)
  );
}
```

In `initDeck`, after `state.byId` is built, set the new fields and use `rebuildQueue()` in place of the inline queue construction:

```javascript
  state.allCategories = itemsResp.body.categories || [];
  state.affiliation = meResp.body.affiliation || null;
  state.selected = loadSelected();
  rebuildQueue();
```

Update `updateChrome` so the denominator reflects the filter:

```javascript
function updateChrome() {
  const inScope = state.items.filter(inSelection);
  const total = inScope.length;
  const done = inScope.filter((i) => i.id in state.votes).length;
  const pos = Math.min(done + 1, total);
  document.getElementById("counter").textContent =
    `${String(pos).padStart(2, "0")}/${String(total).padStart(2, "0")}`;
  document.getElementById("ghost").textContent = String(pos).padStart(2, "0");
}
```

Add the empty-selection state at the top of `showNextCard`, before the existing empty-queue branch:

```javascript
  if (state.selected && state.selected.size === 0) {
    state.current = null;
    area().innerHTML = `
      <div class="endscreen">
        <h2>בחרו לפחות קטגוריה אחת<span class="dot">.</span></h2>
        <p class="summary">פתחו את התפריט ובחרו קטגוריות</p>
      </div>`;
    return;
  }
```

- [ ] **Step 5: Style the cross-attribution line in `site/css/app.css`**

Append:

```css
.xt-line {
  margin-top: 8px;
  font-size: 13px;
  font-weight: 700;
  text-align: center;
  color: var(--ink);
  border-top: 1px solid var(--muted);
  padding-top: 8px;
}
```

- [ ] **Step 6: Verify in the browser**

Serve the stack seeded, then seed a qualifying cross-attribution case directly and screenshot:

```bash
docker compose up -d dynamodb
cd backend && TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python seed.py --votes 40 && cd ..
cd backend && TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python -c "
from app import db
db.table().update_item(
    Key={'PK':'ITEM#friday-noon-wedding','SK':'META'},
    UpdateExpression='ADD xt_right_left :a, xt_right_right :b, xt_left_right :c, xt_left_left :d',
    ExpressionAttributeValues={':a':78,':b':22,':c':80,':d':20})
print('seeded crosstab')" && cd ..
TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ALLOW_ADMIN=1 .venv/bin/python backend/local_server.py &
sleep 3
```

Then vote as an affiliated visitor via curl (cookie jar), and screenshot that item's reveal:

```bash
S=/tmp/claude-1000/-home-latnook-Documents-LR2026/7a82793f-40ca-41f0-9458-345ed55ad528/scratchpad
curl -s -c /tmp/lrjar -b /tmp/lrjar -X POST localhost:8080/api/affiliation -d '{"choice":"right"}' >/dev/null
curl -s -c /tmp/lrjar -b /tmp/lrjar -X POST localhost:8080/api/vote -d '{"item_id":"friday-noon-wedding","choice":"left"}' | head -c 200
```

Confirm the JSON shows `xt_right_left` at 79. Kill the server. (The on-screen check happens in Task 9's suite, once the question card exists to grant an affiliation through the UI.)

- [ ] **Step 7: Commit**

```bash
git add site/ && git commit -m "feat(site): cross-attribution line and category-aware deck"
```

---

### Task 7: Frontend — the 🫵 identity card

**Files:**
- Create: `site/js/affiliation.js`
- Modify: `site/js/api.js`, `site/js/deck.js`, `site/js/app.js`

**Interfaces:**
- Consumes: `deck.js` state, `api.js`.
- Produces:
  - `api.js` gains `setAffiliation(choice)` → `{status, body}`
  - `affiliation.js` exports `shouldAsk(state) -> bool`, `renderQuestion()`, `answer(choice)`, `isShowing() -> bool`
  - `deck.js` calls into it: the question is shown instead of the next item when due, and `castVote` routes to `answer()` while it is showing.

- [ ] **Step 1: Add the API call to `site/js/api.js`**

```javascript
export const setAffiliation = (choice) =>
  req("/api/affiliation", { method: "POST", body: JSON.stringify({ choice }) });
```

- [ ] **Step 2: Write `site/js/affiliation.js`**

```javascript
import { setAffiliation } from "./api.js";

const AT_KEY = "lr_affq_at";
const esc = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

let showing = false;
let onDone = () => {};

export const isShowing = () => showing;

function threshold() {
  try {
    const raw = localStorage.getItem(AT_KEY);
    if (raw) return parseInt(raw, 10);
    const k = 3 + Math.floor(Math.random() * 8); // 3..10 inclusive
    localStorage.setItem(AT_KEY, String(k));
    return k;
  } catch {
    return 3;
  }
}

/** Ask when the visitor has no affiliation and their total votes reached the drawn threshold. */
export function shouldAsk(state) {
  if (state.affiliation) return false;
  return Object.keys(state.votes).length >= threshold();
}

export function renderQuestion(area, done) {
  showing = true;
  onDone = done;
  area.innerHTML = `
    <article class="card" id="card" data-affq="1">
      <h2>האם אתה ימני או שמאלני?<span class="dot"></span></h2>
      <div class="media">🫵</div>
      <div class="hint">→ ימני · ← שמאלני · ↓ מרכז משעמם</div>
      <div class="reveal hidden"></div>
    </article>`;
  document.getElementById("btn-neutral").textContent = "מרכז משעמם ↓";
}

function revealHTML(stats, mine) {
  const total = stats.right + stats.left + stats.center || 1;
  const pctR = Math.round((100 * stats.right) / total);
  const pctL = Math.round((100 * stats.left) / total);
  const mark = (side) => (mine === side ? " ✓" : "");
  return `
    <div class="bar">
      <div class="bar-left" style="width:${pctL}%"></div>
      <div class="bar-right" style="width:${pctR}%"></div>
    </div>
    <div class="stats">
      <span class="right-side">ימנים ${pctR}%${mark("right")}</span>
      <span class="left-side">שמאלנים ${pctL}%${mark("left")}</span>
    </div>
    <div class="neutral-count">🤷 ${100 - pctR - pctL}% מרכז משעמם${mark("center")}</div>
    <div class="reveal-actions"><button class="primary" id="btn-next">הבא</button></div>`;
}

export async function answer(choice, refreshMe) {
  const { status, body } = await setAffiliation(choice);
  if (status !== 200 && status !== 409) {
    window.showToast?.("משהו השתבש, נסו שוב");
    return;
  }
  if (status === 409) {
    await refreshMe();
    finish();
    return;
  }
  const card = document.getElementById("card");
  card.querySelector(".hint").classList.add("hidden");
  const reveal = card.querySelector(".reveal");
  reveal.innerHTML = revealHTML(body.stats, body.affiliation);
  reveal.classList.remove("hidden");
  document.getElementById("btn-next").addEventListener("click", () => finish(body.affiliation));
}

function finish(affiliation) {
  showing = false;
  document.getElementById("btn-neutral").textContent = "ניטרלי ↓";
  onDone(affiliation);
}
```

- [ ] **Step 3: Wire it into `site/js/deck.js`**

Add the import:

```javascript
import * as affq from "./affiliation.js";
import { getMe } from "./api.js";
```

(`getMe` is already imported — do not duplicate the import; add `affq` only.)

In `showNextCard()`, before the empty-selection branch, insert the question when due:

```javascript
  if (affq.shouldAsk(state)) {
    state.revealed = false;
    affq.renderQuestion(area(), (affiliation) => {
      if (affiliation) state.affiliation = affiliation;
      showNextCard();
    });
    return;
  }
```

Add the deck-exhaustion fallback: in the empty-queue branch, ask before ending. Replace the `emptyCbs.forEach((cb) => cb());` line with:

```javascript
    if (!state.affiliation) {
      affq.renderQuestion(area(), (affiliation) => {
        if (affiliation) state.affiliation = affiliation;
        showNextCard();
      });
      return;
    }
    emptyCbs.forEach((cb) => cb());
```

Route votes to the question while it is showing — at the very top of `castVote`:

```javascript
  if (affq.isShowing()) {
    const map = { right: "right", left: "left", neutral: "center" };
    await affq.answer(map[choice], async () => {
      const me = await getMe();
      state.affiliation = me.body.affiliation || null;
      state.votes = me.body.votes || state.votes;
    });
    return;
  }
```

- [ ] **Step 4: Verify in the browser**

Serve the stack seeded. Vote three times through the UI is not scriptable headless, so verify the trigger by pre-seeding votes on a cookie and forcing the threshold:

```bash
S=/tmp/claude-1000/-home-latnook-Documents-LR2026/7a82793f-40ca-41f0-9458-345ed55ad528/scratchpad
chromium --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=390,844 \
  --virtual-time-budget=6000 --screenshot=$S/t7-affq.png \
  "http://localhost:8080/?e2e=affq"
```

For this to work, add a localhost-gated e2e hook in `initDeck` (mirroring the existing `e2e=vote` hook), immediately after `rebuildQueue()`:

```javascript
  if (isLocal && new URLSearchParams(location.search).get("e2e") === "affq") {
    try { localStorage.setItem("lr_affq_at", "0"); } catch { /* ignore */ }
    state.affiliation = null;
  }
```

READ the screenshot and confirm: title `האם אתה ימני או שמאלני?`, 🫵 in the media box, hint line reading `→ ימני · ← שמאלני · ↓ מרכז משעמם`, and the bottom strip reading `מרכז משעמם ↓` (not `ניטרלי ↓`). Kill the server.

- [ ] **Step 5: Commit**

```bash
git add site/ && git commit -m "feat(site): identity question card with its own reveal"
```

---

### Task 8: Frontend — category filter in the ☰ panel

**Files:**
- Modify: `site/js/panels.js`, `site/css/app.css`

**Interfaces:**
- Consumes: `deck.js` (`getAllCategories`, `getCategories`, `setCategories`).
- Produces: a `קטגוריות` section rendered above `ההצבעות שלי` inside the existing panel; toggling applies on panel close.

- [ ] **Step 1: Extend the import in `site/js/panels.js`**

```javascript
import {
  getState,
  onDeckEmpty,
  onVotesChanged,
  getAllCategories,
  getCategories,
  setCategories,
} from "./deck.js";
```

- [ ] **Step 2: Render the section and apply on close**

In `openMyVotes()`, build the category markup before the existing rows and include it in the panel HTML:

```javascript
  const selected = new Set(getCategories());
  const catRows = getAllCategories()
    .map(
      (c) => `<label class="cat-row">
        <input type="checkbox" class="cat-box" value="${esc(c.slug)}"${
          selected.has(c.slug) ? " checked" : ""
        }>
        <span>${esc(c.label)}</span>
      </label>`
    )
    .join("");
```

Insert into the panel template, between the head and the votes rows:

```javascript
    <section class="cat-section">
      <h3>קטגוריות</h3>
      <div class="cat-list">${catRows}</div>
    </section>
    <h3 class="myvotes-head">ההצבעות שלי</h3>
```

Apply the selection when the panel closes — replace the close handler with:

```javascript
  const applyAndClose = () => {
    const chosen = [...panel.querySelectorAll(".cat-box")]
      .filter((b) => b.checked)
      .map((b) => b.value);
    setCategories(chosen);
    close();
  };
  $("panel-close").addEventListener("click", applyAndClose);
```

where `close()` is the existing overlay-close routine (restores focus, removes the Escape listener, re-adds `hidden`). Wire `applyAndClose` into the Escape path too, so a keyboard close applies the same selection.

- [ ] **Step 3: Style it in `site/css/app.css`**

```css
.cat-section { margin: 14px 0 18px; }
.cat-section h3, .myvotes-head { font-size: 15px; font-weight: 900; margin-bottom: 8px; }
.cat-list { display: flex; flex-wrap: wrap; gap: 8px; }
.cat-row {
  display: flex; align-items: center; gap: 6px;
  border: var(--rule-w) solid var(--muted);
  padding: 6px 10px; font-size: 13px; font-weight: 700; cursor: pointer;
}
.cat-row input { accent-color: var(--ink); }
```

- [ ] **Step 4: Verify in the browser**

Serve seeded, screenshot the panel via a localhost-gated hook. Add to `initPanels()`:

```javascript
  if (["localhost", "127.0.0.1"].includes(location.hostname) &&
      new URLSearchParams(location.search).get("e2e") === "panel") {
    openMyVotes();
  }
```

```bash
S=/tmp/claude-1000/-home-latnook-Documents-LR2026/7a82793f-40ca-41f0-9458-345ed55ad528/scratchpad
chromium --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=390,844 \
  --virtual-time-budget=6000 --screenshot=$S/t8-panel.png "http://localhost:8080/?e2e=panel"
```

READ it and confirm: a `קטגוריות` heading with 11 checkboxes, all checked, Hebrew labels correct and RTL, `ההצבעות שלי` heading below. Kill the server.

- [ ] **Step 5: Commit**

```bash
git add site/ && git commit -m "feat(site): category filter section in the menu panel"
```

---

### Task 9: Admin — categories, grouped editable rows, image replace, restore

**Files:**
- Modify: `site/admin/index.html`, `site/admin/admin.js`, `site/admin/admin.css`

**Interfaces:**
- Consumes: Task 4's admin API.
- Produces: create form with a category select; items list grouped by category with counts (including empty groups), each row editable (name, emoji, category, image, שמירה, ארכוב/שחזור); `הצג בארכיון` checkbox.

- [ ] **Step 1: Add the category select and archive toggle to `site/admin/index.html`**

In the create form, after the emoji input:

```html
        <select id="c-cat" required></select>
```

Above the items list heading:

```html
      <label class="inline"><input type="checkbox" id="show-archived"> הצג בארכיון</label>
```

- [ ] **Step 2: Load categories and render the create select in `site/admin/admin.js`**

Add near the top:

```javascript
let CATEGORIES = [];

async function loadCategories() {
  const { status, body } = await api("/api/items");
  if (status === 200) CATEGORIES = body.categories || [];
  const opts = CATEGORIES.map(
    (c) => `<option value="${esc(c.slug)}">${esc(c.label)}</option>`
  ).join("");
  $("c-cat").innerHTML = opts;
  $("c-cat").value = "other";
}

const catSelect = (selected, cls) =>
  `<select class="${cls}">${CATEGORIES.map(
    (c) =>
      `<option value="${esc(c.slug)}"${c.slug === selected ? " selected" : ""}>${esc(
        c.label
      )}</option>`
  ).join("")}</select>`;
```

Include `category: $("c-cat").value` in the create-item POST body, and add a `catSelect(DEFAULT_CAT, "ap-cat")` to each approve row, sending `category: row.querySelector(".ap-cat").value` on approve. Use `const DEFAULT_CAT = "other";`.

- [ ] **Step 3: Replace `loadItems()` with the grouped, editable renderer**

```javascript
async function loadItems() {
  const { status, body } = await api("/api/admin/items");
  if (status !== 200) return toast(`שגיאה בטעינת הפריטים (${status})`);
  const showArchived = $("show-archived").checked;
  const items = (body.items || []).filter((i) => showArchived || i.status === "active");
  const byCat = new Map(CATEGORIES.map((c) => [c.slug, []]));
  for (const i of items) (byCat.get(i.category) || byCat.get("other")).push(i);

  $("items").innerHTML = CATEGORIES.map((c) => {
    const rows = byCat.get(c.slug) || [];
    const inner = rows.length
      ? rows.map((i) => itemRowHTML(i)).join("")
      : '<div class="muted empty-cat">אין פריטים בקטגוריה הזו</div>';
    return `<div class="cat-group">
      <h3>${esc(c.label)} · ${rows.length}</h3>${inner}
    </div>`;
  }).join("");

  for (const row of $("items").querySelectorAll(".row")) wireRow(row);
}

function itemRowHTML(i) {
  return `<div class="row${i.status === "archived" ? " archived" : ""}" data-id="${esc(i.id)}">
    <input class="ed-name grow" value="${esc(i.name)}">
    <input class="ed-emoji" value="${esc(i.emoji || "")}" size="3">
    ${catSelect(i.category, "ed-cat")}
    <input type="file" class="ed-file" accept="image/*">
    <span class="muted">${i.votes_left}/${i.votes_right}/${i.votes_neutral}</span>
    <button class="save">שמירה</button>
    <button class="ghost toggle">${i.status === "archived" ? "שחזור" : "ארכוב"}</button>
  </div>`;
}

function wireRow(row) {
  const id = row.dataset.id;
  row.querySelector(".save").addEventListener("click", async () => {
    const fields = {
      name: row.querySelector(".ed-name").value.trim(),
      emoji: row.querySelector(".ed-emoji").value.trim(),
      category: row.querySelector(".ed-cat").value,
    };
    if (!fields.name) return toast("שם לא יכול להיות ריק");
    const file = row.querySelector(".ed-file").files[0];
    if (file) {
      const { status, body } = await api(
        `/api/admin/items/${encodeURIComponent(id)}/image`,
        { method: "POST" }
      );
      if (status !== 200) return toast(`שגיאה בהעלאת תמונה (${status})`);
      if (body.upload_url) {
        const blob = await fileToWebp(file);
        const up = await fetch(body.upload_url, {
          method: "PUT",
          headers: { "content-type": "image/webp" },
          body: blob,
        });
        if (!up.ok) return toast("העלאת התמונה נכשלה");
        fields.image_key = body.image_key;
      } else {
        toast("אין דלי תמונות מקומי — התמונה לא נשמרה");
      }
    }
    const { status } = await api(`/api/admin/items/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    });
    if (status === 200) { toast("נשמר ✓"); refresh(); }
    else toast(`שגיאה (${status})`);
  });

  row.querySelector(".toggle").addEventListener("click", async () => {
    const archived = row.classList.contains("archived");
    const { status } = await api(`/api/admin/items/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status: archived ? "active" : "archived" }),
    });
    if (status === 200) { toast(archived ? "שוחזר" : "נשלח לארכיון"); refresh(); }
    else toast(`שגיאה (${status})`);
  });
}
```

Wire the checkbox and categories into boot: `$("show-archived").addEventListener("change", loadItems);` and `await loadCategories();` before the first `refresh()`.

- [ ] **Step 4: Style the additions in `site/admin/admin.css`**

```css
.cat-group { margin-top: 18px; }
.cat-group h3 { font-size: 14px; font-weight: 900; border-bottom: 2px solid var(--muted); padding-bottom: 4px; }
.empty-cat { padding: 8px 2px; font-style: italic; }
.row.archived { opacity: 0.45; }
.inline { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; margin-top: 10px; }
select { background: var(--surface); color: var(--ink); border: 2px solid var(--ink); padding: 6px; font-family: var(--font); font-size: 13px; }
```

- [ ] **Step 5: Verify in the browser**

Serve seeded. Screenshot `/admin/` (window 1100x1000) to `t9-admin.png`, READ it, and confirm: create form has a category dropdown; items are grouped under Hebrew category headings with counts; empty categories show `אין פריטים בקטגוריה הזו`; each row has name/emoji/category/file/שמירה/ארכוב; `הצג בארכיון` checkbox present.

Then exercise the round-trip with curl and confirm via the API:

```bash
curl -s -X PATCH localhost:8080/api/admin/items/corn-pizza -d '{"category":"conspiracy"}' >/dev/null
curl -s localhost:8080/api/admin/items | python3 -m json.tool | grep -A2 '"id": "corn-pizza"'
curl -s -X PATCH localhost:8080/api/admin/items/corn-pizza -d '{"category":"food"}' >/dev/null
```

Kill the server.

- [ ] **Step 6: Commit**

```bash
git add site/ && git commit -m "feat(admin): category selects, grouped editable rows, image replace, restore"
```

---

### Task 10: Verification suite + docs

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-08-06-lr-voting-site-design.md` (base-spec pointer)

**Interfaces:** none new — verifies and documents.

- [ ] **Step 1: Point the base spec at the newer one**

Add immediately under the base spec's title line:

```markdown
> **Extended by** [`2026-08-07-lr-affiliation-categories-design.md`](2026-08-07-lr-affiliation-categories-design.md):
> visitor self-identification with cross-attribution stats, item categories with visitor filters,
> and admin item management.
```

- [ ] **Step 2: Extend `README.md`**

Add after the existing "Run locally" block:

```markdown
## Features

- Vote ימני / שמאלני / ניטרלי on each item; stats reveal after voting.
- A one-time "האם אתה ימני או שמאלני?" card appears between your 3rd and 10th vote; afterwards
  reveals can show cross-attribution lines like "78% מהימנים חושבים שזה שמאלני" (shown only when a
  camp has 25+ decisive votes on that item and crosses 70%).
- Items are categorised; the ☰ menu lets you switch categories off and the deck follows.
- `/admin/` manages the suggestion queue and every item: rename, re-file, emoji, image upload or
  replace, archive and restore.
```

- [ ] **Step 3: Full backend suite**

```bash
docker compose up -d dynamodb
cd backend && ../.venv/bin/pytest -q && cd ..
```

Expected: all tests pass (42 from before plus this plan's additions). Report the count.

- [ ] **Step 4: Screenshot suite**

Serve the stack seeded with the cross-attribution figures from Task 6 Step 6, then capture, READ, and describe each of:

| File | Window | URL | Must show |
|---|---|---|---|
| `t10-question.png` | 390x844 | `/?e2e=affq` | 🫵 card, `האם אתה ימני או שמאלני?`, `מרכז משעמם ↓` strip |
| `t10-panel.png` | 390x844 | `/?e2e=panel` | קטגוריות with 11 checked boxes, ההצבעות שלי below |
| `t10-admin.png` | 1100x1000 | `/admin/` | grouped items with counts, editable rows, הצג בארכיון |
| `t10-mobile-card.png` | 390x844 | `/` | unchanged item card (no regression) |
| `t10-desktop-reveal.png` | 1280x800 | `/?e2e=vote` | unchanged reveal (no regression) |

- [ ] **Step 5: Console hygiene**

For `/` and `/admin/`: `chromium --headless --disable-gpu --no-sandbox --virtual-time-budget=5000 --dump-dom URL 2>&1 | grep -iE "error|uncaught|failed"` → report output (expect none).

- [ ] **Step 6: Human checklist — report as OPEN, do not self-certify**

- the identity card appears somewhere between the 3rd and 10th vote and only once;
- answering it shows the national split, then the deck continues;
- the ➕ FAB and the `NN/MM` counter are unaffected by answering;
- switching categories off in ☰ changes the deck and the counter denominator;
- deselecting everything shows `בחרו לפחות קטגוריה אחת`;
- a cross-attribution line appears on a qualifying item and nowhere else;
- admin: rename, re-file, add an image, archive then restore.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/ && git commit -m "docs: features section and spec cross-reference"
```

---

## Self-review notes

- **Spec coverage:** §1.1 card/copy/trigger/fallback → T7; §1.2 profile + stats records → T2; §1.3 counters + back-fill → T2; §1.4 cross-attribution rule → T6 (pure function, boundary-checked in T6 Step 2); §1.5 card's own reveal → T7; §2.1 category list → T1; §2.2 item model + legacy default → T1; §2.3 filter UX incl. counter and empty state → T6+T8; §2.4 admin → T4+T9; §2.5 seed → T5; §3 API → T3+T4; §4 error handling → T7 (409 refetch, toast on failure); §5 testing → T1–T4 pytest, T6/T9/T10 visual.
- **Deliberate choices:** the cross-attribution rule lives only in the frontend per spec §6, so it is verified by a node boundary run rather than pytest; `list_all_items` scans (same justification as the existing `list_active_items` — catalogue stays in the low hundreds and admin is not a hot path).
- **Type consistency checked:** `xt_<aff>_<choice>` naming identical across T2/T3/T6; `categories.CATEGORIES` shape `{slug,label}` identical across T1/T3/T8/T9; `setCategories`/`getCategories`/`getAllCategories` match between T6 and T8; `affq.shouldAsk/renderQuestion/answer/isShowing` match between T7's definition and its `deck.js` call sites; affiliation values `right|left|center` consistent everywhere, with the vote-choice→affiliation mapping (`neutral`→`center`) confined to one place in T7 Step 3.
