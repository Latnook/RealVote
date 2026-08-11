# RealVote — the database as the source of truth — Design

**Date:** 2026-08-11
**Status:** Approved by Ariel (2026-08-11)
**Builds on:** `2026-08-09-admin-votes-tab-design.md`, the deploy branch (Terraform + Cognito admin)

Adding an item to the live deck currently takes three manual steps on Ariel's laptop: edit
`backend/seed/items.json`, start DynamoDB Local plus the dev server to run `add-image.py`, then run
`publish-items.py` against production. Four items were added this way on 2026-08-11 and every one of
them needed the full dance.

This design removes the dance by deleting the thing that requires it. Items already live in
DynamoDB — the site reads the table, never the repo — so `items.json` is not a store. It is a copy
of production that a human keeps in sync by hand, and the sync only runs one way: `publish-items.py`
calls `create_item`, which is conditional on the item not existing, so a rename or refile done in
`/admin/` never flows back to the file.

After this work, adding an item is one form at `/admin/`, from any device.

---

## 1. What moves where

| Concern | Today | After |
|---|---|---|
| Item records | DynamoDB (truth) + `items.json` (hand-kept copy) | DynamoDB only |
| Picture bytes | S3 (prod) + `site/img/` (local, gitignored) | unchanged |
| Picture provenance | `images.csv`, hand-edited, referenced by `README.md:155` | `image_source` on the item record, published at `/credits/` |
| Adding an item | local dev server → `add-image.py` → `publish-items.py` | the `/admin/` create form, with a URL field |
| Local dev data | `items.json` via `seed.py` | `seed.py --from-prod`, over the public API |
| Backup | PITR (35 days, `dynamodb.tf:22`) + whatever `items.json` happened to hold | PITR, unchanged; `images.csv` retired as a live document |

Nothing about the voting mechanic, the cross-attribution rule, the deck engine, or the admin
suggestions/votes tabs changes.

### 1.1 The schema stays in the repo; the rows do not

"The database is the source of truth" is about **data**, not about structure. DynamoDB declares only
PK and SK at the table level, so the real schema is the code that writes and reads records — and all
of it stays in git:

| Layer | Where | Fate |
|---|---|---|
| Table declaration — keys, types, TTL, PITR, billing mode | `terraform/dynamodb.tf` | unchanged |
| Local/test table creation, mirroring the above | `db.ensure_table()` (`db.py:61`) | unchanged |
| Record shapes — `ITEM#<id>/META`, `USER#<uid>/PROFILE`, `USER#<uid>/VOTE#<item>` | `db.py:82`, `:102`, `:233` | **extended** — `image_source` is defined here (§2) |
| Canonical category list | `backend/app/categories.py` | unchanged |
| The 115 item **rows** | `backend/seed/items.json` | deleted |

After this change the repo describes the shape of an item slightly more completely than it does
today. It simply stops also carrying a copy of the contents.

---

## 2. Data model

One new optional attribute on the item record:

| Field | Type | Meaning |
|---|---|---|
| `image_source` | string | The URL the picture was fetched from. Absent for pictures uploaded from a local file, and for the three legacy items in §5. |

Touch points:

- `db.create_item(...)` gains an `image_source=None` keyword argument, written only when truthy —
  matching how `image_key` is already handled at `db.py:115`.
- `db.update_item`'s allowed-field set (`db.py:233`) gains `"image_source"`.
- `db.get_item`'s projection (`db.py:93`) returns it when present, so it reaches the **public**
  `/api/items` feed. This is deliberate: the credits page must render without an admin token.
- `admin_routes.create_item` and `patch_item` accept it in the request body. No new validation
  beyond "string, or absent" — it is a provenance note, not a fetched resource.

`image_source` is descriptive only. Nothing reads it to fetch anything; the bytes already live in S3.

---

## 3. The admin create form

### 3.1 Behaviour

The create form gains a URL text field beside the existing file picker. They are mutually exclusive:
filling the URL disables the picker and vice versa.

On submit with a URL, the fetch happens **first**, so a URL that cannot be retrieved never leaves a
pictureless item behind:

```
fetch(<url>) → .blob() → fileToWebp(blob)        ← may fail; nothing written yet
POST /api/admin/items {..., want_image: true, image_source: <url>}
  → { upload_url }
PUT upload_url  (the blob)
```

`fileToWebp()` (`admin.js:193`) already accepts any Blob, caps the long edge at 1200px and encodes
WebP at quality 0.85. Those settings match what `add-image.py` produces, so a picture added through
this path is indistinguishable from the 103 already live. **If one is ever changed, change both** —
otherwise the deck quietly forks into two image qualities.

No Lambda change and no image library are required. The conversion happens in the browser that is
already open.

### 3.2 Failure handling

A remote fetch fails in more ways than a file picker, and each needs a distinct message rather than
a generic error:

| Case | Detection | Behaviour |
|---|---|---|
| Host sends no CORS header | `fetch` rejects | Toast: download it and use the file picker instead. The item is **not** created. |
| Not an image | response `content-type` is not `image/*` | Rejected before the canvas step; item not created. |
| SVG | `content-type: image/svg+xml` | Rejected, pointing at `add-image.py`. Browser-side SVG sanitising is a real security job — the file would be served from our own origin — and is out of scope rather than done badly. |
| Fetch succeeds, S3 PUT fails | `up.ok === false` | Existing behaviour: the item exists without a picture, retried from the edit row. |
| Item id already taken | 409 from the API | Existing behaviour: `item-id כבר קיים`, nothing fetched. |

Validation order matters: **create the item only after the image fetch succeeds**, so a CORS failure
does not leave a pictureless item behind. This is a change from the current flow, which creates
first because a local file cannot fail to load.

Wikimedia — the source of 100 of the 103 current pictures — serves
`access-control-allow-origin: *`, verified against `upload.wikimedia.org` on 2026-08-11.

---

## 4. The credits page

A static `/credits/` page, in the same K² typographic style as `/admin/`, built from the public
`/api/items` feed:

- One row per item that has an `image_key`: thumbnail, item name, and `image_source` as a link.
- Items whose `image_source` is absent render **מקור לא תועד** rather than being hidden — an
  undocumented picture should be visible as a gap, not silently omitted.
- Items with no picture at all (12 today, emoji-only) do not appear.

`README.md:155` currently says picture licences are "recorded in `images.csv`". It is repointed at
`/credits/`. The page is always current because it reads the same table the deck does.

---

## 5. Retroactive backfill

`scripts/backfill-image-source.py`, run once against production:

1. Read `images.csv` (`id`, `image_url`).
2. For each row whose item exists in production **and** has an `image_key`, PATCH `image_source`.
3. Report what it skipped.

Measured coverage on 2026-08-11: **115 items, 103 with pictures, 100 with a recorded source.**

The three gaps are `avatar`, `lotr` and `the-matrix` — the movie items added in `5609ad4` without
CSV rows. They are left empty rather than guessed, appear as **מקור לא תועד** on the credits page,
and can be filled from `/admin/` whenever the sources are identified.

The script is idempotent and stays in `scripts/` as the documented way to do a bulk provenance fix.

---

## 6. Retiring the seed file

Deleted: `backend/seed/items.json`, `scripts/publish-items.py`.

`seed.py` gains `--from-prod`, which seeds local DynamoDB from
`https://realvote.latnook.com/api/items` — the **public** feed. No AWS credentials, no Terraform
outputs, no admin token, so a fresh clone of the open-source repo gets the real deck over plain
HTTPS. `--with-images` additionally pulls the pictures from the CDN into `site/img/`; without it,
local dev renders emoji, which is an acceptable default.

This also fixes a standing annoyance: `local-dev.sh` reseeds on every start, which today restores a
stale snapshot and drops `image_key` links, requiring `add-image.py --relink` afterwards. Seeding
from production makes the local deck match the live one instead.

Callers to update: `seed.py:21`, `README.md:112`. The test suite is unaffected — it builds its own
fixtures via `seeded()` in `test_routes_public.py` and never reads the seed file. Historical
references in `docs/superpowers/plans/` are left alone as a record of what was true then.

`images.csv` is kept in the repo as the input to the backfill and as a historical record, but stops
being a document anyone must update.

---

## 7. Continuous integration

**Scope: tests only.** A GitHub Actions workflow on push and pull request:

- `pytest` (85 tests)
- `node scripts/check-crosstab.mjs`

No AWS credentials, no OIDC role, no deploy step. The repo is public, so a workflow that holds
credentials capable of writing to production is a standing risk that buys little here — deployment
is infrequent and deliberate. `./scripts/deploy.sh` stays a manual action from Ariel's laptop.

This is the whole of the "CI/CD" ask. Once items live only in the database, adding one is not a code
change, so there is no content pipeline left to build.

---

## 8. Testing

| Area | Test |
|---|---|
| `image_source` round-trip | `create_item` with a source, `get_item` returns it; absent when not supplied |
| `update_item` | `image_source` is accepted; unknown fields still rejected |
| Public feed | `/api/items` includes `image_source` when present |
| Admin create | POST with `image_source` persists it; POST without it still works |
| Backfill script | Against a fresh table: sourced rows patched, unknown ids skipped, items without `image_key` skipped |
| `seed.py --from-prod` | Against a stubbed feed: items created, idempotent on a second run |
| Credits page | Renders a linked source, and `מקור לא תועד` for an item without one |

The URL-fetch path in `admin.js` is exercised by hand against a Wikimedia URL and against a
known CORS-blocking host — there is no browser test harness in this project, and adding one is out
of scope.

---

## 9. Out of scope

- **Logo plating** (`add-image.py --replate`). Stays a script-side curation pass. Note for whoever
  runs it next: `come-dine-with-me` is pale-yellow artwork that `looks_like_logo()` flags as
  transparent, and the light plate is the one background it cannot be read against.
- **SVG through the admin form** — see §3.2.
- **S3 versioning on the image bucket.** The bucket is unversioned (`s3.tf:33`) and a bad
  `aws s3 rm` is permanent. Worth a one-line `aws_s3_bucket_versioning` resource, but it is a
  separate hardening change, not part of this one.
- **Beyond-35-day backup.** PITR's window is the whole window. A scheduled DynamoDB export to S3
  would extend it; not needed at this scale today.
- **Deleting `images.csv`.** Kept as backfill input and history.
