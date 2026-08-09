# RealVote — admin votes tab & `/admin` redirect — Design

**Date:** 2026-08-09
**Status:** Approved by Ariel (2026-08-09)
**Builds on:** `2026-08-07-lr-affiliation-categories-design.md`, Plan 4 (`2026-08-07-realvote-deploy.md`) — site live at `realvote.latnook.com`

Two unrelated-but-adjacent changes to the admin surface:

1. **Votes tab** — the admin panel currently exposes suggestions and items but has no view of
   voting results at all. Vote data is reachable only by hand-running `aws dynamodb scan`.
2. **`/admin` 301** — `https://realvote.latnook.com/admin` (no trailing slash) returns an S3
   `AccessDenied`, so the panel is only reachable at `/admin/`.

---

## 1. The `/admin` 403

### 1.1 Diagnosis

| URL | Status |
|---|---|
| `/admin` | **403 AccessDenied** |
| `/admin/` | 200 |
| `/admin/index.html` | 200 |

`aws_cloudfront_function.dir_index` (`terraform/cloudfront.tf:37`) appends `index.html` only to
URIs that already end in `/`. `/admin` therefore reaches S3 as a request for a key literally named
`admin`, which does not exist. Because the bucket is private and the OAC policy grants no
`s3:ListBucket`, S3 answers **403 rather than 404** — it will not confirm or deny a key's existence
to a caller that cannot list. The bucket policy is correct; only the error wording is misleading.

### 1.2 Fix

Extend the same function with an extensionless-path redirect, placed **before** the existing
rewrite:

```js
function handler(event) {
  var req = event.request;
  if (!req.uri.endsWith("/") && !req.uri.split("/").pop().includes(".")) {
    return {
      statusCode: 301,
      statusDescription: "Moved Permanently",
      headers: { location: { value: req.uri + "/" } },
    };
  }
  if (req.uri.endsWith("/")) {
    req.uri += "index.html";
  }
  return req;
}
```

`/admin` → 301 → `/admin/` → rewrite → `admin/index.html`.

**The dot test is load-bearing.** `/admin/config.json` contains a dot and is therefore never
touched. This matters because `admin.js:307` boots the panel into **LOCAL mode — no authentication
at all** — when `config.json` fails to load. Any change that causes that path to return 200 HTML
instead of a 404 silently disables admin auth in production. The existing warning comments at
`cloudfront.tf:93` and `cloudfront.tf:137` document the same trap; this design preserves both.

A 301 is chosen over an internal rewrite (`req.uri += "/index.html"`) so there is exactly one
canonical URL for the panel rather than two paths serving identical bytes.

**Deploy:** `terraform apply`, then a CloudFront invalidation.
**Verify:** `curl -o /dev/null -w "%{http_code}"` against `/admin` (expect 301), `/admin/` (200),
and `/admin/config.json` (403 — still absent, still not rewritten).

---

## 2. Votes tab

### 2.1 What is already stored

No schema changes. Every fact the tab needs exists today:

| Record | Fields used |
|---|---|
| `USER#<uid>` / `VOTE#<item_id>` | `choice`, `ts` — one row per ballot |
| `USER#<uid>` / `PROFILE` | `affiliation` — present only for visitors who answered the card |
| `ITEM#<id>` / `META` | `name`, `category`, `votes_left/right/neutral`, nine `xt_<affiliation>_<choice>` counters |

Voters are anonymous. `uid` is a random 32-hex value minted into the `lr_uid` cookie
(`handler.py:16`); no name, email, or IP is ever stored. The tab therefore shows **pseudonymous**
ballots — "this browser voted these items this way" — and this limitation is stated in the UI so
the numbers are not over-read. Clearing cookies produces a new `uid`, so the voter count is an
upper bound on distinct browsers, not on people.

### 2.2 Data flow

```
votes tab activated
        │
        ├──> GET /api/admin/votes   ──> db.list_all_votes()  ──> single Scan
        │       summary + per-voter ballots                     (VOTE# and PROFILE rows)
        │
        └──> GET /api/admin/items   ──> existing, unchanged
                names, categories, L/R/N, xt_* counters
                        │
                        ▼
              browser joins on item_id
                        │
        ┌───────────────┼───────────────┬──────────────┐
     summary       voter list      cross-tab        CSV
      strip       (expandable)     by item        (client-side)
```

**The votes endpoint deliberately does not return item names.** Ballots carry `item_id` only; the
browser joins Hebrew names from `/api/admin/items`, which the panel already fetches and which
already carries all nine cross-tab counters per item. Embedding names would repeat the same 111
strings across every ballot and would fork item metadata across two endpoints that could disagree.

### 2.3 Backend — `db.list_all_votes(detail_cap=50_000)`

New function in `backend/app/db.py`, following the paginated-scan shape of `list_all_items`
(`db.py:142`):

- `FilterExpression="begins_with(SK, :v) OR SK = :p"` with `:v = "VOTE#"`, `:p = "PROFILE"`
- `ProjectionExpression="PK,SK,choice,ts,affiliation"` — none of these are DynamoDB reserved
  words, so no `ExpressionAttributeNames` aliasing is needed here. (`name` and `status` are
  reserved, which is why existing scans alias them as `#n` / `#s`; a projection added later must
  do the same.)
- Paginates to completion via `LastEvaluatedKey`
- Tallies the summary on every row; retains per-voter ballot detail only while under `detail_cap`

**The cap applies to retained detail, never to the counts.** Tallying a row is O(1) memory and the
whole table is read regardless, so the summary is always exact. Only `voters[].ballots` grows
linearly with input and can exhaust a limit.

At the boundary: once `detail_cap` retained ballots is reached, further ballots are tallied but not
retained, and `detail_truncated` is set. Scanning still runs to completion. Ballots already
retained are kept as-is — a voter present in `voters` may therefore hold a partial ballot list, so
the UI must not treat `len(voters[i].ballots)` as that voter's true total. Each voter object
carries its own exact `ballot_count`, tallied independently of retention, and the UI displays that.

Sizing: a serialized ballot measures ~60 bytes (`item_id` averages 12.3 chars in current data).
The binding constraint is **Lambda's 6 MB synchronous response payload limit**, reached at roughly
104,000 ballots — where the endpoint would return 502 rather than degrade. `detail_cap = 50_000`
(~3 MB) sits at half that ceiling, leaving room for voter wrapper objects and future fields. At 111
items that is ~450 completionist voters or a few thousand typical ones. Beyond it the correct next
step is server-side CSV streaming to S3, not a larger cap.

### 2.4 Backend — route

`admin_routes.list_votes(event)` — a thin wrapper returning `http.response(200, ...)`, registered
in `dispatch` as `("GET", "/api/admin/votes")` beside the existing entries at
`admin_routes.py:124`. It inherits the `authorized` gate `dispatch` already applies to every
`/api/admin/*` path, so authentication needs no new code.

The path matches the `/api/*` CloudFront behavior (`cloudfront.tf:127`, Managed-CachingDisabled),
so responses are never cached at the edge.

### 2.5 Response shape

```json
{
  "summary": {
    "voters": 10,
    "ballots": 224,
    "choices":      { "left": 91, "right": 86, "neutral": 47 },
    "affiliations": { "left": 5, "right": 1, "center": 0, "unknown": 4 }
  },
  "voters": [
    {
      "uid": "3fdd68dc680b480f821c998d779fe9ee",
      "affiliation": "left",
      "ballot_count": 80,
      "ballots": [ { "item_id": "katan", "choice": "left", "ts": 1754750000 } ]
    }
  ],
  "detail_truncated": false
}
```

`affiliations.unknown` is derived (`voters − identified`) so visitors who voted without declaring a
side are visible rather than silently absent. `affiliation` is `null` for those voters.
`voters` is sorted by `ballot_count`, descending.

`ballot_count` is the voter's exact total and is always accurate; `ballots` may be shorter under
truncation (§2.3).

**Only uids with at least one ballot appear.** A `PROFILE` row without any `VOTE#` rows is ignored
entirely — it does not create a `voters` entry, does not count toward `summary.voters`, and does
not count toward `summary.affiliations`. Every tally in `summary` is therefore over the same
population, and the affiliation buckets always sum to `summary.voters`.

### 2.6 Frontend — tab bar

The panel today is a flat scroll of three `<section>`s (`site/admin/index.html:33`). It becomes
three tabs, RTL order right-to-left:

| Tab | Contents |
|---|---|
| **הצעות** | the pending-suggestions queue (`#queue`), with a count badge when non-empty |
| **פריטים** | the "פריט חדש" create form, the `show-archived` toggle, and the items list |
| **הצבעות** | new — §2.7 |

`פריט חדש` moves into `פריטים`, where it belongs. **הצעות** remains the default tab so existing
habit is unbroken; the last-used tab is remembered in `localStorage` under `lr_admin_tab`.

Implementation is a `<nav class="tabs">` of buttons toggling the existing `.hidden` class on each
section — no framework, matching how `admin.js` already shows and hides `#login` and `#admin-main`.
Votes data loads lazily on first activation of its tab, so opening the panel does not trigger a
scan.

### 2.7 Frontend — the votes panel

```
┌ סיכום ────────────────────────────────────────┐
│  10 מצביעים    224 הצבעות                      │
│  שמאלני 91 · ימני 86 · ניטרלי 47                │
│  זיהוי: 5 שמאל · 1 ימין · 0 מרכז · 4 ללא        │
└───────────────────────────────────────────────┘
        [ מצביעים | לפי פריט ]        [ ייצוא CSV ]

▸ 3fdd68dc…   80 הצבעות   [שמאל]   לפני 3 שעות
▾ 6c99afaf…   64 הצבעות   [—]      לפני יומיים
      קטאן                שמאלני    לפני יומיים
      בובספוג             ימני      לפני יומיים
```

A segmented control switches the list between two views:

- **מצביעים** — one row per voter (uid abbreviated to 8 chars, ballot count, affiliation chip, time
  of most recent vote). Clicking expands that voter's ballots in place, with no extra fetch.
- **לפי פריט** — one row per item: its L/R/N totals plus the ימין / שמאל / מרכז cross-tab read
  straight off the `xt_*` counters already present on each item record.

Details that are easy to get wrong, specified now:

- **CSV begins with a UTF-8 BOM (`U+FEFF`, written `﻿` in source)**, without which Excel
  renders Hebrew as mojibake. Columns:
  `uid, item_id, name, choice, timestamp`. Filename `votes-YYYY-MM-DD.csv`. Built client-side from
  data already loaded; inherits `detail_cap` and says so when truncated.
- **Relative times use `Intl.RelativeTimeFormat("he")`** — native, no dependency, correct Hebrew
  pluralization (`לפני יומיים`, not `לפני 2 ימים`).
- **All interpolated values pass through the existing `esc()`** (`admin.js:1`), item names included.
- **Auto-refresh is 30s, gated twice** — only while the votes tab is active *and*
  `document.visibilityState === "visible"`. The interval is cleared on tab switch and on hide, so a
  backgrounded browser does not scan the table all day.

### 2.8 Error handling

| Case | Behavior |
|---|---|
| 401 or other non-200 | `toast("שגיאה בטעינת ההצבעות (<status>)")`, consistent with `loadQueue` / `loadItems` |
| Network failure (`status === 0`) | Same toast path; `api()` already normalizes this |
| Zero votes | `עדיין אין הצבעות` empty state, matching the existing empty-queue string |
| `detail_truncated: true` | Warning banner stating the **drill-down** is partial and the summary is exact |
| Ballot referencing a deleted item | Row renders the raw `item_id` rather than dropping the vote |

---

## 3. Testing

### 3.1 Backend (TDD, real DynamoDB Local via the `fresh_table` fixture)

`backend/tests/test_db_votes.py`:

- grouping of ballots by `uid`
- `affiliation` attached from the `PROFILE` row; `null` when absent
- summary arithmetic: `voters`, `ballots`, `choices`
- `affiliations.unknown` derived correctly, and affiliation buckets sum to `summary.voters`
- a `PROFILE` row with no `VOTE#` rows is ignored by every tally (§2.5)
- `detail_cap` exceeded → `detail_truncated: true`, **and the summary still exact**
- under truncation, `ballot_count` remains exact for a voter whose `ballots` list was cut short
- empty table → zeroed summary, empty `voters`

`backend/tests/test_routes_admin.py`:

- `GET /api/admin/votes` unauthenticated → 401 (mirrors `test_admin_items_requires_auth`)
- authenticated → 200 with the §2.5 shape

### 3.2 Frontend

The repo has no JS test framework, so verification is manual on the local dev server
(`scripts/local-dev.sh`): tab switching and persistence, voter expand/collapse, both segmented
views, CSV opening in a spreadsheet with Hebrew intact, and auto-refresh stopping when the tab is
hidden or switched away.

### 3.3 CloudFront function

No local harness. Verified after deploy by `curl` against the three URLs in §1.2.

---

## 4. Out of scope

- Deanonymizing voters — no identifying data is collected, and none will be added.
- Server-side CSV streaming (only needed past `detail_cap`; see §2.3).
- Precomputed vote counters on a `STATS` row — considered and rejected: it cannot produce per-voter
  ballots, so it would sit alongside the scan rather than replace it, while adding a third item to
  the vote write transaction and requiring a backfill.
- Per-voter `Query` endpoints (`/api/admin/votes/{uid}`) — rejected because CSV export and the
  summary both need the full set anyway, turning drill-down into an N+1 fetch.
