# The Database As The Source Of Truth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DynamoDB the only store of item data, so adding an item is one form at `/admin/` instead of editing a seed file, running a local dev server, and publishing from a laptop.

**Architecture:** An optional `image_source` attribute is added to the item record and surfaced on the public feed. The admin create form gains a URL field; the browser fetches the picture, converts it with the `fileToWebp()` already in `admin.js`, and PUTs it to the existing presigned URL — no Lambda change and no image library. Provenance moves off `images.csv` onto the record and is published at `/credits/`. `backend/seed/items.json` and `scripts/publish-items.py` are then deleted, and `seed.py` seeds local development from the public API instead.

**Tech Stack:** Python 3.13 (Lambda runtime), boto3, pytest, DynamoDB (+ DynamoDB Local for tests), vanilla ES modules, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-11-db-as-source-of-truth-design.md`

## Global Constraints

- **Python version:** CI must use **3.13** — it matches `terraform/lambda.tf:71` (`runtime = "python3.13"`). The local `.venv` is 3.14; do not pin CI to that.
- **Tests require DynamoDB Local** on `http://localhost:8000` (`conftest.py:7`) **and** dummy AWS credentials. Two tests in `test_routes_admin.py` call `_presign()`, which builds a plain `boto3.client("s3")` with no credential injection and raises `NoCredentialsError` without them. Presigning signs locally and never calls AWS, so `AWS_ACCESS_KEY_ID=ci AWS_SECRET_ACCESS_KEY=ci AWS_DEFAULT_REGION=us-east-1` is sufficient. Verified 2026-08-11.
- **All user-facing copy is Hebrew.** The admin UI and the credits page are RTL (`<html lang="he" dir="rtl">`).
- **No CDN, no external dependencies at runtime.** Third-party JS is vendored (`site/admin/vendor/`). Do not add a package manager to the frontend.
- **Theme tokens only.** Colours come from `site/css/theme.css` (`--bg`, `--ink`, `--muted`, `--surface`). Do not hardcode hex values in new pages.
- **Image encoding must stay identical across both paths:** long edge capped at 1200px, WebP quality 0.85 (`admin.js:193`). If one is ever changed, change the other.
- **`image_source` is descriptive only.** Nothing fetches it. It is never used to build a URL.
- Run tests from `backend/`: `cd backend && ../.venv/bin/python -m pytest -q`.

---

## Task 1: CI workflow (tests only)

Placed first so every later task is guarded by it.

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a `test` job that must pass on push to `main` and on every pull request.

- [ ] **Step 1: Verify the test suite passes locally with no AWS credentials**

Start DynamoDB Local and run the suite the way CI will:

```bash
docker run -d --rm -p 8000:8000 --name ddb-local amazon/dynamodb-local:latest
until curl -s -o /dev/null http://localhost:8000; do sleep 1; done
cd backend && AWS_ACCESS_KEY_ID=ci AWS_SECRET_ACCESS_KEY=ci AWS_DEFAULT_REGION=us-east-1 \
  DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python -m pytest -q
```

Expected: `85 passed`. If you see `NoCredentialsError`, the dummy credentials are missing.

- [ ] **Step 2: Write the workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    env:
      DDB_ENDPOINT: http://localhost:8000
      # The two presign tests build a real boto3 S3 client. Presigning signs
      # locally and never calls AWS, so dummy values are enough — but absent
      # credentials raise NoCredentialsError and fail the suite.
      AWS_ACCESS_KEY_ID: ci
      AWS_SECRET_ACCESS_KEY: ci
      AWS_DEFAULT_REGION: us-east-1
    steps:
      - uses: actions/checkout@v4

      - name: Start DynamoDB Local
        run: |
          docker run -d --rm -p 8000:8000 --name ddb-local amazon/dynamodb-local:latest
          for _ in $(seq 1 30); do
            curl -s -o /dev/null http://localhost:8000 && exit 0
            sleep 1
          done
          echo "DynamoDB Local did not come up" >&2
          exit 1

      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'   # matches terraform/lambda.tf

      - name: Install Python dependencies
        run: pip install -r backend/requirements-dev.txt

      - name: Run pytest
        working-directory: backend
        run: python -m pytest -q

      - uses: actions/setup-node@v4
        with:
          node-version: '22'

      - name: Cross-attribution boundary checks
        run: node scripts/check-crosstab.mjs
```

- [ ] **Step 3: Validate the YAML parses**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Stop the local container**

```bash
docker stop ddb-local
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pytest and the crosstab checks on push and PR

Tests only, and deliberately so: the repo is public, so a workflow holding
credentials that can write to production would be a standing risk for little
gain — deploys are infrequent and stay a deliberate ./scripts/deploy.sh.

DynamoDB Local runs as a plain docker container rather than a service
container so the image's default entrypoint is used unchanged. The dummy AWS
credentials are needed by the two presign tests, which build a real boto3 S3
client; presigning signs locally and never calls AWS."
```

---

## Task 2: `image_source` in the data layer

**Files:**
- Modify: `backend/app/db.py:82-99` (`_to_item_dict`), `:102-117` (`create_item`), `:232-246` (`update_item`)
- Test: `backend/tests/test_db_items.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `db.create_item(item_id, name, emoji, image_key=None, category=categories.DEFAULT, image_source=None)` — `image_source` written only when truthy.
  - `db.update_item(item_id, **fields)` accepts `image_source` in its allowed set.
  - `db.get_item()` / `list_active_items()` / `list_all_items()` include `"image_source"` in the returned dict when the record has one, and omit the key entirely otherwise.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_db_items.py`:

```python
def test_create_item_records_image_source(fresh_table):
    db.create_item("picanto", "קיה פיקנטו", "🚗",
                   image_key="img/picanto-1786477356.webp",
                   image_source="https://upload.wikimedia.org/wikipedia/commons/1/11/x.JPG")
    item = db.get_item("picanto")
    assert item["image_source"] == "https://upload.wikimedia.org/wikipedia/commons/1/11/x.JPG"


def test_image_source_absent_when_not_supplied(fresh_table):
    db.create_item("plain", "פשוט", "🙂")
    assert "image_source" not in db.get_item("plain")


def test_update_item_can_set_image_source(fresh_table):
    db.create_item("plain", "פשוט", "🙂")
    db.update_item("plain", image_source="https://example.org/pic.jpg")
    assert db.get_item("plain")["image_source"] == "https://example.org/pic.jpg"


def test_list_active_items_carries_image_source(fresh_table):
    db.create_item("a", "א", "🅰️", image_source="https://example.org/a.jpg")
    db.create_item("b", "ב", "🅱️")
    by_id = {i["id"]: i for i in db.list_active_items()}
    assert by_id["a"]["image_source"] == "https://example.org/a.jpg"
    assert "image_source" not in by_id["b"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_db_items.py -q`
Expected: 4 failures — `TypeError: create_item() got an unexpected keyword argument 'image_source'` and `KeyError: 'image_source'`.

- [ ] **Step 3: Add the field to `_to_item_dict`**

In `backend/app/db.py`, directly after the existing `image_key` block (`:93-94`):

```python
    if record.get("image_key"):
        d["image_key"] = record["image_key"]
    if record.get("image_source"):
        d["image_source"] = record["image_source"]
```

- [ ] **Step 4: Accept it in `create_item`**

Change the signature and add one write, mirroring how `image_key` is handled:

```python
def create_item(item_id, name, emoji, image_key=None, category=categories.DEFAULT,
                image_source=None):
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
        "category": category if categories.is_valid(category) else categories.DEFAULT,
    }
    if image_key:
        record["image_key"] = image_key
    if image_source:
        record["image_source"] = image_source
    table().put_item(Item=record, ConditionExpression="attribute_not_exists(PK)")
```

- [ ] **Step 5: Allow it in `update_item`**

```python
    allowed = {"name", "emoji", "image_key", "status", "category", "image_source"}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_db_items.py -q`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `cd backend && ../.venv/bin/python -m pytest -q`
Expected: `89 passed` (85 existing + 4 new).

- [ ] **Step 8: Commit**

```bash
git add backend/app/db.py backend/tests/test_db_items.py
git commit -m "feat(db): record where a picture came from

image_source holds the URL a picture was fetched from, written only when
supplied so existing records are untouched and read back only when present.
It rides the same projection as image_key, which puts it on the public
/api/items feed — deliberate, because the credits page must render without an
admin token."
```

---

## Task 3: `image_source` through the admin API

**Files:**
- Modify: `backend/app/admin_routes.py:64-80` (`create_item`), `:83-98` (`patch_item`)
- Test: `backend/tests/test_routes_admin.py`, `backend/tests/test_routes_public.py`

**Interfaces:**
- Consumes: `db.create_item(..., image_source=)` and `db.update_item(..., image_source=)` from Task 2.
- Produces:
  - `POST /api/admin/items` accepts an optional `image_source` string in the body; a non-string that is not absent returns 400 and writes nothing.
  - `PATCH /api/admin/items/<id>` accepts `image_source` alongside the existing fields.
  - `GET /api/items` (public, unauthenticated) returns `image_source` for items that have one.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_routes_admin.py`:

```python
def test_create_item_persists_image_source(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True, body={
        "item_id": "picanto", "name": "קיה פיקנטו", "emoji": "🚗",
        "category": "consumer",
        "image_source": "https://upload.wikimedia.org/wikipedia/commons/1/11/x.JPG",
    }))
    assert resp["statusCode"] == 200
    assert db.get_item("picanto")["image_source"] == \
        "https://upload.wikimedia.org/wikipedia/commons/1/11/x.JPG"


def test_create_item_without_image_source_still_works(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True, body={
        "item_id": "plain", "name": "פשוט", "emoji": "🙂"}))
    assert resp["statusCode"] == 200
    assert "image_source" not in db.get_item("plain")


def test_create_item_rejects_non_string_image_source(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True, body={
        "item_id": "bad", "name": "רע", "image_source": 42}))
    assert resp["statusCode"] == 400
    assert db.get_item("bad") is None


def test_patch_item_sets_image_source(fresh_table):
    db.create_item("plain", "פשוט", "🙂")
    resp, _ = call(apigw_event("PATCH", "/api/admin/items/plain", admin=True,
                               body={"image_source": "https://example.org/p.jpg"}))
    assert resp["statusCode"] == 200
    assert db.get_item("plain")["image_source"] == "https://example.org/p.jpg"
```

Append to `backend/tests/test_routes_public.py`:

```python
def test_public_feed_exposes_image_source(fresh_table):
    db.create_item("sourced", "עם מקור", "🖼️",
                   image_key="img/sourced-1.webp",
                   image_source="https://example.org/pic.jpg")
    resp, body = call(apigw_event("GET", "/api/items"))
    assert resp["statusCode"] == 200
    item = next(i for i in body["items"] if i["id"] == "sourced")
    assert item["image_source"] == "https://example.org/pic.jpg"
```

`test_routes_public.py` already defines `call()` at line 8 and imports `apigw_event` — the new test
needs no extra imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_routes_admin.py tests/test_routes_public.py -q`
Expected: 4 failures on `KeyError: 'image_source'`, and `test_create_item_rejects_non_string_image_source` failing because a 200 is returned.

- [ ] **Step 3: Accept and validate it in the create route**

In `backend/app/admin_routes.py`, inside `create_item`, after the category check and before `image_key` is computed:

```python
    image_source = body.get("image_source") or None
    if image_source is not None and not isinstance(image_source, str):
        return http.response(400, {"error": "bad_request"})
    image_key = _image_key(item_id) if body.get("want_image") else None
    try:
        db.create_item(item_id, name, body.get("emoji", ""), image_key=image_key,
                       category=category, image_source=image_source)
```

- [ ] **Step 4: Allow it on the patch route**

```python
    fields = {k: v for k, v in body.items()
              if k in {"name", "emoji", "status", "image_key", "category", "image_source"}}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/python -m pytest -q`
Expected: `94 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/admin_routes.py backend/tests/test_routes_admin.py backend/tests/test_routes_public.py
git commit -m "feat(admin): accept image_source on create and patch

A non-string image_source is a 400 rather than something coerced, so a
malformed client cannot write a number into a field the credits page renders
as a link. Absent stays absent — the field is optional and existing callers
are unaffected."
```

---

## Task 4: Retroactive backfill script

**Files:**
- Create: `scripts/backfill-image-source.py`
- Test: `backend/tests/test_backfill.py`

**Interfaces:**
- Consumes: `PATCH /api/admin/items/<id>` accepting `image_source` (Task 3).
- Produces: `plan_backfill(rows, items) -> list[tuple[str, str]]` — a pure function returning `(item_id, url)` pairs to patch, so the decision logic is testable without AWS.

**Context:** measured on 2026-08-11 — 115 items, 103 with pictures, 100 with a source in `images.csv`. The three without are `avatar`, `lotr` and `the-matrix` (added in `5609ad4` with no CSV row). They are left empty rather than guessed.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_backfill.py`:

```python
import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "backfill-image-source.py"


def load():
    """The filename has a hyphen, so it cannot be imported by name."""
    spec = importlib.util.spec_from_file_location("backfill", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plans_only_pictured_items_with_a_source():
    backfill = load()
    rows = [
        {"id": "picanto", "image_url": "https://example.org/picanto.jpg"},
        {"id": "lotr", "image_url": ""},                                  # no source recorded
        {"id": "ghost", "image_url": "https://example.org/ghost.jpg"},    # not in the table
        {"id": "emoji-only", "image_url": "https://example.org/e.jpg"},   # no picture
    ]
    items = {
        "picanto": {"id": "picanto", "image_key": "img/picanto-1.webp"},
        "lotr": {"id": "lotr", "image_key": "img/lotr-1.webp"},
        "emoji-only": {"id": "emoji-only"},
    }
    assert backfill.plan_backfill(rows, items) == [
        ("picanto", "https://example.org/picanto.jpg")
    ]


def test_skips_items_that_already_have_a_source():
    backfill = load()
    rows = [{"id": "done", "image_url": "https://example.org/new.jpg"}]
    items = {"done": {"id": "done", "image_key": "img/done-1.webp",
                      "image_source": "https://example.org/old.jpg"}}
    assert backfill.plan_backfill(rows, items) == []


def test_whitespace_is_stripped():
    backfill = load()
    rows = [{"id": "  picanto  ", "image_url": "  https://example.org/p.jpg  "}]
    items = {"picanto": {"id": "picanto", "image_key": "img/p-1.webp"}}
    assert backfill.plan_backfill(rows, items) == [("picanto", "https://example.org/p.jpg")]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_backfill.py -q`
Expected: FAIL — `FileNotFoundError` on the script path.

- [ ] **Step 3: Write the script**

Create `scripts/backfill-image-source.py` (make it executable: `chmod +x`):

```python
#!/usr/bin/env python3
"""Backfill image_source onto items whose picture predates the field.

Provenance used to live in images.csv, a hand-edited file that README.md cited for
picture licensing. It now lives on the item record and is published at /credits/.
This walks the CSV once and patches every item it can account for.

    ./scripts/backfill-image-source.py --dry-run     # show the plan, write nothing
    ./scripts/backfill-image-source.py               # apply it

Idempotent: an item that already carries an image_source is left alone, so a partial
run can simply be repeated. Items with no picture are skipped (nothing to attribute),
and so are CSV rows for ids the table does not have.
"""

import argparse
import csv
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "images.csv"


def plan_backfill(rows, items):
    """Return [(item_id, url)] for pictured items that have a source but no image_source."""
    plan = []
    for row in rows:
        iid = (row.get("id") or "").strip()
        url = (row.get("image_url") or "").strip()
        if not iid or not url:
            continue
        item = items.get(iid)
        if not item or not item.get("image_key") or item.get("image_source"):
            continue
        plan.append((iid, url))
    return plan


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def site_url():
    """Read the site URL from Terraform so it is never hardcoded here."""
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"].rstrip("/")
    try:
        out = subprocess.run(
            ["terraform", f"-chdir={ROOT / 'terraform'}", "output", "-raw", "site_url"],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        sys.exit("terraform is not on PATH — set SITE_URL instead")
    except subprocess.CalledProcessError as e:
        sys.exit(f"terraform output site_url failed — has the infra been applied?\n"
                 f"{e.stderr.strip()[:200]}")
    return out.stdout.strip().rstrip("/")


def fetch_items(base):
    with urllib.request.urlopen(f"{base}/api/items", timeout=30) as resp:
        return {i["id"]: i for i in json.load(resp)["items"]}


def patch(base, token, item_id, url):
    req = urllib.request.Request(
        f"{base}/api/admin/items/{item_id}",
        data=json.dumps({"image_source": url}).encode(),
        headers={"content-type": "application/json", "authorization": token},
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status == 200


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    ap.add_argument("--csv", type=pathlib.Path, default=CSV_PATH)
    args = ap.parse_args()

    base = site_url()
    items = fetch_items(base)
    rows = read_rows(args.csv)
    plan = plan_backfill(rows, items)

    pictured = [i for i in items.values() if i.get("image_key")]
    unsourced = [i["id"] for i in pictured
                 if not i.get("image_source") and i["id"] not in dict(plan)]

    print(f"==> {len(items)} items, {len(pictured)} with pictures, {len(plan)} to backfill")
    for iid, url in plan:
        print(f"  · {iid:24} {url[:70]}")
    if unsourced:
        print(f"no source recorded for {len(unsourced)}: {', '.join(sorted(unsourced))}")

    if args.dry_run:
        print("\ndry run — nothing was written")
        return 0
    if not plan:
        print("nothing to do")
        return 0

    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        sys.exit("set ADMIN_TOKEN to a Cognito id token (copy it from /admin/ devtools)")

    ok = sum(patch(base, token, iid, url) for iid, url in plan)
    print(f"\nbackfilled {ok}/{len(plan)}")
    return 0 if ok == len(plan) else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_backfill.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Dry-run against production**

Run: `./scripts/backfill-image-source.py --dry-run`
Expected: `115 items, 103 with pictures, 100 to backfill`, then `no source recorded for 3: avatar, lotr, the-matrix`.

**Do not apply it yet** — the credits page (Task 6) is what makes the result visible. Applying here is safe but unverifiable.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill-image-source.py backend/tests/test_backfill.py
git commit -m "feat(scripts): backfill image_source from images.csv

Walks the CSV once and patches every pictured item that has a recorded source
and no image_source yet — 100 of the 103 pictured items. avatar, lotr and
the-matrix have no CSV row (they arrived in 5609ad4 without one) and are left
empty rather than guessed; /credits/ will show them as unattributed.

The planning half is a pure function so the decision logic is tested without
AWS; the filename has a hyphen, so the test loads it through importlib."
```

---

## Task 5: URL ingest in the admin create form

**Files:**
- Modify: `site/admin/index.html:47-55` (the create form)
- Modify: `site/admin/admin.js:192-245` (`fileToWebp`, `initCreateForm`)

**Interfaces:**
- Consumes: `POST /api/admin/items` accepting `image_source` (Task 3).
- Produces: no exported interface — this is UI. New internal helpers: `urlToBlob(url)` and `imageErrorMessage(err)`.

**Behaviour change to be deliberate about:** today the item is created *before* the picture is handled, which is safe only because a local file cannot fail to load. A URL can, so the fetch moves **first** and nothing is written until it succeeds.

- [ ] **Step 1: Add the URL field to the form**

In `site/admin/index.html`, after the `c-file` input (`:53`):

```html
        <input type="file" id="c-file" accept="image/*" class="hidden" aria-label="תמונה">
        <input type="url" id="c-url" class="hidden" placeholder="או קישור לתמונה"
               aria-label="קישור לתמונה">
```

- [ ] **Step 2: Show both inputs together, and make them mutually exclusive**

In `initCreateForm()` (`admin.js:203-207`), replace the single toggle:

```js
  $("c-image").addEventListener("change", () => {
    const on = $("c-image").checked;
    $("c-file").classList.toggle("hidden", !on);
    $("c-url").classList.toggle("hidden", !on);
  });
  // One source or the other, never both — whichever was touched last wins.
  $("c-url").addEventListener("input", () => {
    if ($("c-url").value.trim()) $("c-file").value = "";
  });
  $("c-file").addEventListener("change", () => {
    if ($("c-file").files[0]) $("c-url").value = "";
  });
```

- [ ] **Step 3: Add the fetch helper and its error messages**

Directly after `fileToWebp()` in `admin.js`:

```js
/* A remote picture fails in more ways than a file picker, and each needs its own
   message — "it didn't work" would send you hunting for the wrong problem. */
async function urlToBlob(url) {
  let resp;
  try {
    resp = await fetch(url, { mode: "cors" });
  } catch {
    throw new Error("cors");
  }
  if (!resp.ok) throw new Error("http");
  const type = resp.headers.get("content-type") || "";
  if (type.includes("svg")) throw new Error("svg");
  if (!type.startsWith("image/")) throw new Error("not-image");
  return resp.blob();
}

function imageErrorMessage(err) {
  if (err.message === "svg") return "SVG — השתמש ב-add-image.py";
  if (err.message === "not-image") return "הקישור אינו מוביל לתמונה";
  if (err.message === "http") return "הקישור החזיר שגיאה";
  return "לא ניתן להוריד מהקישור — הורד את התמונה והעלה כקובץ";
}
```

- [ ] **Step 4: Rewrite the submit handler so the picture is resolved first**

Replace the body of the `create-form` submit listener (`admin.js:210-245`) with:

```js
  $("create-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const item_id = $("c-id").value.trim() || slugify($("c-name").value);
    const want_image = $("c-image").checked;
    const source_url = $("c-url").value.trim();
    const file = $("c-file").files[0];

    // Resolve the picture BEFORE creating the item: a URL that cannot be fetched
    // must not leave a pictureless item behind.
    let blob = null;
    if (want_image && (source_url || file)) {
      try {
        blob = await fileToWebp(source_url ? await urlToBlob(source_url) : file);
      } catch (err) {
        return toast(imageErrorMessage(err));
      }
    }

    const { status, body } = await api("/api/admin/items", {
      method: "POST",
      body: JSON.stringify({
        item_id,
        name: $("c-name").value.trim(),
        emoji: $("c-emoji").value.trim(),
        category: $("c-cat").value,
        want_image,
        ...(source_url ? { image_source: source_url } : {}),
      }),
    });
    if (status === 409) return toast("item-id כבר קיים");
    if (status !== 200) return toast(`שגיאה (${status})`);

    if (blob && body.upload_url) {
      const up = await fetch(body.upload_url, {
        method: "PUT",
        headers: { "content-type": "image/webp" },
        body: blob,
      });
      toast(up.ok ? "נוצר + תמונה הועלתה ✓" : "נוצר, אך העלאת התמונה נכשלה");
    } else if (want_image && !body.upload_url) {
      toast("נוצר (אין דלי תמונות מקומי)");
    } else if (want_image) {
      toast("נוצר — עדיין ללא תמונה");
    } else {
      toast("נוצר ✓");
    }

    $("create-form").reset();
    $("c-file").classList.add("hidden");
    $("c-url").classList.add("hidden");
    $("c-id").focus();
    refresh();
  });
```

- [ ] **Step 5: Verify by hand — there is no browser test harness in this project**

```bash
./scripts/local-dev.sh          # leave running in another terminal
```

Open `http://localhost:8080/admin/` and check all four:

| Case | Input | Expected |
|---|---|---|
| Happy path | name `בדיקה`, tick עם תמונה, URL `https://upload.wikimedia.org/wikipedia/commons/2/2f/Flat_earth.png` | `נוצר + תמונה הועלתה ✓`, card shows the picture |
| CORS refusal | any URL on a host without `access-control-allow-origin` | `לא ניתן להוריד מהקישור…`, **no item created** — confirm the list does not grow |
| Not an image | `https://example.com/` | `הקישור אינו מוביל לתמונה`, no item created |
| File picker still works | tick עם תמונה, choose a local JPG | `נוצר + תמונה הועלתה ✓` |

Then confirm the source was stored:

```bash
curl -s http://localhost:8080/api/items | python3 -c "
import json,sys
print([i.get('image_source') for i in json.load(sys.stdin)['items'] if i['id']=='בדיקה-slug'])"
```

- [ ] **Step 6: Stop the local stack and clean up the test item**

```bash
docker compose down
```

Delete any test items you created from `/admin/` before committing.

- [ ] **Step 7: Commit**

```bash
git add site/admin/index.html site/admin/admin.js
git commit -m "feat(admin): create an item from a picture URL

The browser fetches the URL, runs it through the fileToWebp() already here and
PUTs it to the presigned URL, so no Lambda change and no image library are
needed. Wikimedia — the source of 100 of the 103 current pictures — serves
access-control-allow-origin: *.

The picture is now resolved BEFORE the item is created. A local file cannot
fail to load, which is why the old order was safe; a URL can, and creating
first would leave a pictureless item behind every time a host refuses CORS.

SVG is refused rather than sanitised in the browser: the file would be served
from our own origin, and that is not a job to do badly."
```

---

## Task 6: The credits page

**Files:**
- Create: `site/credits/index.html`
- Create: `site/js/credits.js`
- Modify: `README.md:155-156`

**Interfaces:**
- Consumes: `image_source` on the public `/api/items` feed (Tasks 2-3).
- Produces: a page at `/credits/`. No Terraform change is needed — the CloudFront function at `terraform/cloudfront.tf:34-60` rewrites any extensionless URI to a trailing slash and then to `index.html`, generically.

- [ ] **Step 1: Write the page**

Create `site/credits/index.html`:

```html
<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>קרדיטים — בעיניי</title>
  <meta name="theme-color" content="#23262B">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="stylesheet" href="/css/theme.css">
  <style>
    body { background: var(--bg); color: var(--ink); font-family: var(--font);
           margin: 0; padding: 0 16px 48px; }
    header { padding: 18px 0 10px; }
    .wordmark { font-weight: 900; font-size: 20px; }
    .rule { border-top: var(--rule-w) solid var(--ink); margin-bottom: 18px; }
    h1 { font-size: 22px; font-weight: 900; margin: 0 0 6px; }
    p.lede { color: var(--muted); font-size: 14px; margin: 0 0 22px; max-width: 60ch; }
    ul { list-style: none; margin: 0; padding: 0; }
    li { display: flex; gap: 12px; align-items: center;
         padding: 10px 0; border-bottom: 1px solid var(--surface); }
    img { width: 64px; height: 43px; object-fit: cover; background: var(--surface); flex: none; }
    .meta { min-width: 0; }
    .name { font-weight: 700; font-size: 15px; }
    .src { font-size: 12px; color: var(--muted); word-break: break-all; }
    .src a { color: var(--muted); }
    .none { color: var(--muted); font-style: italic; }
  </style>
</head>
<body>
  <header>
    <span class="wordmark">בעיניי<span class="dot">.</span></span>
  </header>
  <div class="rule"></div>
  <h1>קרדיטים לתמונות</h1>
  <p class="lede">
    הקוד של האתר מפורסם ברישיון MIT, אך התמונות אינן כלולות בו: כל אחת נאספה ממקור
    צד־שלישי והרישיונות שלהן משתנים. הרשימה נבנית מהנתונים החיים של האתר.
  </p>
  <ul id="credits"></ul>
  <script type="module" src="/js/credits.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write the module**

Create `site/js/credits.js`:

```js
// Built from the public feed, so the list is whatever the deck is currently showing.
const esc = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

// Only http(s) may become an href — an item's source is admin-entered text, and
// javascript: in an anchor would run on click.
const safeHref = (url) => /^https?:\/\//i.test(url);

function row(item) {
  const src = item.image_source && safeHref(item.image_source)
    ? `<a href="${esc(item.image_source)}" rel="noopener nofollow ugc"
          target="_blank">${esc(item.image_source)}</a>`
    : `<span class="none">מקור לא תועד</span>`;
  return `<li>
    <img src="/${esc(item.image_key)}" alt="" loading="lazy">
    <div class="meta">
      <div class="name">${esc(item.name)}</div>
      <div class="src">${src}</div>
    </div>
  </li>`;
}

async function main() {
  const list = document.getElementById("credits");
  let items = [];
  try {
    const resp = await fetch("/api/items");
    items = (await resp.json()).items || [];
  } catch {
    list.innerHTML = `<li class="none">לא ניתן לטעון את הרשימה</li>`;
    return;
  }
  // Items with no picture need no attribution; unattributed pictures are shown
  // as a visible gap rather than quietly omitted.
  const pictured = items
    .filter((i) => i.image_key)
    .sort((a, b) => a.name.localeCompare(b.name, "he"));
  list.innerHTML = pictured.map(row).join("") ||
    `<li class="none">אין עדיין תמונות</li>`;
}

main();
```

- [ ] **Step 3: Verify locally**

```bash
./scripts/local-dev.sh
```

Open `http://localhost:8080/credits/` and confirm: pictures render, sourced items link out, and an item with no source shows *מקור לא תועד*. If the local deck has no `image_source` values yet (expected before Task 4 is applied), every row should read *מקור לא תועד* — that is the correct empty state, not a bug.

- [ ] **Step 4: Repoint the README**

Replace `README.md:155-156`:

```markdown
MIT — see [`LICENSE`](LICENSE). Item pictures are **not** covered by it: each was collected from a
third-party source, recorded on the item itself and listed at
[`/credits/`](https://realvote.latnook.com/credits/). Their licences vary.
```

- [ ] **Step 5: Stop the local stack**

```bash
docker compose down
```

- [ ] **Step 6: Commit**

```bash
git add site/credits/index.html site/js/credits.js README.md
git commit -m "feat(site): credits page listing every picture's source

Reads the same public feed the deck does, so it cannot drift from what is
actually on the cards — which is the whole reason provenance moved off
images.csv and onto the record.

Items without a recorded source render 'מקור לא תועד' rather than being
dropped: an unattributed picture should be visible as a gap. Sources are only
turned into links when they are http(s), since the field is admin-entered
text and javascript: in an href would run on click.

No Terraform change — the CloudFront directory-index function is generic."
```

---

## Task 7: Retire the seed file

**Files:**
- Delete: `backend/seed/items.json`, `scripts/publish-items.py`
- Modify: `backend/seed.py`
- Modify: `README.md:112`
- Test: `backend/tests/test_seed.py` (create)

**Interfaces:**
- Consumes: the public `/api/items` feed.
- Produces: `seed.fetch_items(feed_url) -> list[dict]` and `seed.seed_items(items) -> int` (count created). `seed.py` CLI: `[--feed URL] [--with-images] [--votes N]`.

**Do this task last** — it removes the escape hatch, and the earlier tasks are easier to verify while `items.json` still exists.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_seed.py`:

```python
import seed
from app import db


def test_seed_items_creates_and_is_idempotent(fresh_table):
    items = [
        {"id": "a", "name": "א", "emoji": "🅰️", "category": "food"},
        {"id": "b", "name": "ב", "emoji": "🅱️", "category": "nonsense"},
    ]
    assert seed.seed_items(items) == 2
    assert db.get_item("a")["name"] == "א"
    # An unknown category falls back rather than raising, matching create_item.
    assert db.get_item("b")["category"] == "other"
    # Second run creates nothing and does not raise.
    assert seed.seed_items(items) == 0


def test_seed_items_carries_image_fields(fresh_table):
    seed.seed_items([{
        "id": "pic", "name": "תמונה", "emoji": "🖼️", "category": "food",
        "image_key": "img/pic-1.webp", "image_source": "https://example.org/p.jpg",
    }])
    item = db.get_item("pic")
    assert item["image_key"] == "img/pic-1.webp"
    assert item["image_source"] == "https://example.org/p.jpg"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_seed.py -q`
Expected: FAIL — `AttributeError: module 'seed' has no attribute 'seed_items'`.

- [ ] **Step 3: Rewrite `seed.py`**

```python
"""Create the local table and seed it from the live site. Optionally add demo votes.

Items live in DynamoDB, not in this repo — the deck you get locally is whatever the
public feed is currently serving. That needs no AWS credentials and no admin token,
so a fresh clone can seed itself over plain HTTPS.

Usage: TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 python seed.py \
           [--feed URL] [--with-images] [--votes N]
"""
import argparse
import json
import os
import pathlib
import random
import sys
import urllib.request

from app import db

FEED = "https://realvote.latnook.com/api/items"
IMG_DIR = pathlib.Path(__file__).resolve().parent.parent / "site" / "img"


def fetch_items(feed_url):
    with urllib.request.urlopen(feed_url, timeout=30) as resp:
        return json.load(resp)["items"]


def seed_items(items):
    """Create every item that is not already there. Returns how many were created."""
    created = 0
    for it in items:
        try:
            db.create_item(
                it["id"], it["name"], it.get("emoji", ""),
                image_key=it.get("image_key"),
                category=it.get("category", "other"),
                image_source=it.get("image_source"),
            )
            created += 1
        except Exception:
            pass  # already seeded — idempotent
    return created


def fetch_images(items, base):
    """Pull pictures from the CDN into site/img/ so local cards are not emoji-only."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    got = 0
    for it in items:
        key = it.get("image_key")
        if not key:
            continue
        dest = IMG_DIR.parent / key
        if dest.exists():
            continue
        try:
            urllib.request.urlretrieve(f"{base}/{key}", dest)
            got += 1
        except Exception as e:
            print(f"  ✗ {it['id']}: {e}")
    return got


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", default=FEED, help="public /api/items URL to seed from")
    parser.add_argument("--with-images", action="store_true",
                        help="also download the pictures into site/img/")
    parser.add_argument("--votes", type=int, default=0)
    args = parser.parse_args()

    db.ensure_table(os.environ["TABLE_NAME"])
    try:
        items = fetch_items(args.feed)
    except Exception as e:
        print(f"could not read {args.feed}: {e}\n"
              f"seeding an empty deck — add items from /admin/", file=sys.stderr)
        items = []

    created = seed_items(items)
    print(f"items: {created} created, {len(items) - created} already existed")

    if args.with_images and items:
        base = args.feed.rsplit("/api/", 1)[0]
        print(f"images: {fetch_images(items, base)} downloaded")

    for n in range(args.votes):
        uid = f"demo-{n}"
        if not items:
            break
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

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_seed.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Delete the retired files**

```bash
git rm backend/seed/items.json scripts/publish-items.py
```

- [ ] **Step 6: Update the README**

Replace `README.md:112`:

```markdown
Items live in DynamoDB and are managed from `/admin/`. `backend/seed.py` seeds a local table
from the live site's public feed, so no AWS credentials are needed:

```bash
cd backend && python seed.py --with-images
```
```

- [ ] **Step 7: Verify the whole local stack still comes up**

```bash
./scripts/local-dev.sh
```

Expected: `items: 115 created, 0 already existed`. Open `http://localhost:8080/` and confirm cards render. Then:

```bash
curl -s http://localhost:8080/api/items | python3 -c "
import json,sys; d=json.load(sys.stdin)['items']
print(len(d), 'items,', sum(1 for i in d if i.get('image_source')), 'with a source')"
docker compose down
```

- [ ] **Step 8: Run the whole suite**

Run: `cd backend && ../.venv/bin/python -m pytest -q`
Expected: `99 passed` — 85 at the start, +4 (Task 2), +5 (Task 3), +3 (Task 4), +2 here.

- [ ] **Step 9: Commit**

```bash
git add -A backend/seed.py backend/tests/test_seed.py README.md
git commit -m "feat(seed): seed local dev from the live feed; retire items.json

items.json was never a store — the site reads DynamoDB, never the repo — so it
was a copy of production kept in sync by hand, and the sync only ran one way:
publish-items.py called a conditional create, so a rename or refile done in
/admin/ never came back. Both are deleted.

seed.py now reads the public /api/items feed, which needs no AWS credentials
and no admin token, so a fresh clone gets the real deck over plain HTTPS.
--with-images pulls the pictures from the CDN; without it, local cards fall
back to emoji. This also ends the reseed-then---relink dance, since the local
deck is now whatever production is actually serving."
```

- [ ] **Step 10: Apply the backfill and verify it on the credits page**

Now that everything is in place:

```bash
./scripts/backfill-image-source.py --dry-run    # confirm 100 to backfill
export ADMIN_TOKEN=...                          # id token from /admin/ devtools
./scripts/backfill-image-source.py
```

Then open `https://realvote.latnook.com/credits/` and confirm 100 rows link to their source and 3 (`avatar`, `lotr`, `the-matrix`) read *מקור לא תועד*.

> This step writes to production and needs Ariel's approval before it runs.

---

## Notes for the implementer

- **Deployment is manual and out of CI by design.** After Tasks 5-7, the site changes need `./scripts/deploy.sh` to reach production. Task 4's backfill and Task 7's Step 10 write to the live table. Neither happens automatically; both need Ariel's explicit go-ahead.
- **`images.csv` stays.** It is the backfill's input and a historical record. It is no longer a document anyone must update — that is the point of Task 4.
- **Do not run `add-image.py --replate` as part of this work.** `come-dine-with-me` is pale-yellow artwork that `looks_like_logo()` flags as transparent, and the light plate is the one background it cannot be read against.
