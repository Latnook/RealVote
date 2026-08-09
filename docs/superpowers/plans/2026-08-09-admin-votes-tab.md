# Admin Votes Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the admin panel a הצבעות tab showing how many people voted and what each one voted, and make `https://realvote.latnook.com/admin` (no trailing slash) load instead of returning 403.

**Architecture:** One new DynamoDB scan helper (`db.list_all_votes`) behind one new authenticated route (`GET /api/admin/votes`), returning an always-exact summary plus per-voter ballots with a cap on retained detail. The flat admin page becomes three tabs; the votes panel joins ballot `item_id`s against the existing `/api/admin/items` response for Hebrew names and cross-tab counters. Separately, the existing `dir_index` CloudFront function gains a 301 for extensionless paths.

**Tech Stack:** Python 3 + boto3 (Lambda), pytest against DynamoDB Local, vanilla ES-module JavaScript (no framework, no CDN), Terraform, CloudFront Functions (JS runtime 2.0).

**Spec:** `docs/superpowers/specs/2026-08-09-admin-votes-tab-design.md`

## Global Constraints

- **Branch:** `feat/admin-votes-tab` (already created; the spec commit is on it).
- **No new dependencies.** No CDN, no npm packages, no Python packages. Everything vendored or native.
- **All user-visible strings are Hebrew**, copied verbatim from this plan. The page is `dir="rtl"`.
- **Every interpolated value passes through `esc()`** (`site/admin/admin.js:1`) before entering `innerHTML` — item names included.
- **Never let `/admin/config.json` return 200 HTML.** `admin.js:307` boots the panel into LOCAL mode (no authentication) when that file fails to load. Any CloudFront change must leave that path 404/403 when the object is absent.
- **Tests need DynamoDB Local on `http://localhost:8000`.** Start with `docker compose up -d dynamodb` from the repo root. Run tests with `cd backend && ../.venv/bin/python -m pytest`.
- **Do not run `terraform apply` or any prod deploy.** Ariel runs those himself. Tasks 8–9 stop at `terraform plan`.
- **Detail cap:** `VOTES_DETAIL_CAP = 50_000`, defined once in `backend/app/db.py`.
- **Commit after every task.** Conventional-commit prefixes, matching repo history (`feat(...)`, `fix(...)`, `docs(...)`).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `backend/app/db.py` | Modify | Add `VOTES_DETAIL_CAP`, `list_all_votes()`. Data layer only — no HTTP concerns. |
| `backend/app/admin_routes.py` | Modify | Add `list_votes()` handler + `dispatch` entry. Thin HTTP wrapper. |
| `backend/tests/test_db_votes.py` | Modify | Data-layer tests for grouping, tallies, truncation. |
| `backend/tests/test_routes_admin.py` | Modify | Route auth + payload shape tests. |
| `site/admin/index.html` | Modify | Tab nav; wrap existing sections in panels; add votes panel markup. |
| `site/admin/admin.css` | Modify | Tab bar, summary strip, voter rows, ballot rows, cross-tab rows, warning banner. |
| `site/admin/admin.js` | Modify | Tab controller, votes loading/rendering, CSV, auto-refresh. |
| `terraform/cloudfront.tf` | Modify | `dir_index` function gains the extensionless 301. |

`admin.js` grows by roughly 200 lines. That is acceptable here — the file is currently 317 lines and organized by `/* ---- section ---- */` comment banners, and the votes code forms one such coherent block. Splitting it into ES modules would be a larger restructure than this feature warrants, and the repo has no build step to bundle them.

---

## Task 1: `db.list_all_votes()`

**Files:**
- Modify: `backend/app/db.py` (add near `list_all_items`, `db.py:142`)
- Test: `backend/tests/test_db_votes.py` (append)

**Interfaces:**
- Consumes: existing `table()`, `CHOICES`, `AFFILIATIONS` from `db.py`.
- Produces: `db.VOTES_DETAIL_CAP` (int) and `db.list_all_votes(detail_cap=VOTES_DETAIL_CAP) -> dict` with keys `summary` (`voters`, `ballots`, `choices`, `affiliations`), `voters` (list of `{uid, affiliation, ballot_count, ballots}`), `detail_truncated` (bool). Task 2 consumes this.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_db_votes.py`:

```python
def test_list_all_votes_groups_by_uid(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.create_item("magnets", "מגנטים על המקרר", "🧲")
    db.record_vote("u1", "katan", "left")
    db.record_vote("u1", "magnets", "right")
    db.record_vote("u2", "katan", "neutral")

    got = db.list_all_votes()

    assert got["summary"]["voters"] == 2
    assert got["summary"]["ballots"] == 3
    assert got["summary"]["choices"] == {"left": 1, "right": 1, "neutral": 1}
    assert got["detail_truncated"] is False
    # sorted by ballot_count descending
    assert [v["uid"] for v in got["voters"]] == ["u1", "u2"]
    assert got["voters"][0]["ballot_count"] == 2
    assert {b["item_id"] for b in got["voters"][0]["ballots"]} == {"katan", "magnets"}


def test_list_all_votes_attaches_affiliation(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.set_affiliation("u1", "left")
    db.record_vote("u1", "katan", "left")
    db.record_vote("u2", "katan", "right")

    voters = {v["uid"]: v for v in db.list_all_votes()["voters"]}

    assert voters["u1"]["affiliation"] == "left"
    assert voters["u2"]["affiliation"] is None


def test_list_all_votes_affiliation_buckets_sum_to_voters(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.set_affiliation("u1", "left")
    db.set_affiliation("u2", "right")
    for uid in ("u1", "u2", "u3"):
        db.record_vote(uid, "katan", "left")

    summary = db.list_all_votes()["summary"]

    assert summary["affiliations"] == {"left": 1, "right": 1, "center": 0, "unknown": 1}
    assert sum(summary["affiliations"].values()) == summary["voters"]


def test_list_all_votes_ignores_profile_without_ballots(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.set_affiliation("lurker", "center")  # answered the card, never voted
    db.record_vote("u1", "katan", "left")

    got = db.list_all_votes()

    assert got["summary"]["voters"] == 1
    assert got["summary"]["affiliations"]["center"] == 0
    assert [v["uid"] for v in got["voters"]] == ["u1"]


def test_list_all_votes_truncates_detail_but_not_counts(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.create_item("magnets", "מגנטים על המקרר", "🧲")
    db.record_vote("u1", "katan", "left")
    db.record_vote("u1", "magnets", "right")

    got = db.list_all_votes(detail_cap=1)

    assert got["detail_truncated"] is True
    assert got["summary"]["ballots"] == 2          # counts stay exact
    assert got["voters"][0]["ballot_count"] == 2   # per-voter count stays exact
    assert len(got["voters"][0]["ballots"]) == 1   # only detail is cut


def test_list_all_votes_empty_table(fresh_table):
    got = db.list_all_votes()

    assert got["summary"] == {
        "voters": 0,
        "ballots": 0,
        "choices": {"left": 0, "right": 0, "neutral": 0},
        "affiliations": {"right": 0, "left": 0, "center": 0, "unknown": 0},
    }
    assert got["voters"] == []
    assert got["detail_truncated"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker compose up -d dynamodb
cd backend && ../.venv/bin/python -m pytest tests/test_db_votes.py -v
```

Expected: the six new tests FAIL with `AttributeError: module 'app.db' has no attribute 'list_all_votes'`. The nine pre-existing tests in the file must still PASS.

- [ ] **Step 3: Implement**

Add `import collections` to the imports at the top of `backend/app/db.py` (alphabetically before `import functools`).

Then add after `list_all_items` (which ends at `db.py:154`):

```python
VOTES_DETAIL_CAP = 50_000


def list_all_votes(detail_cap=VOTES_DETAIL_CAP):
    """Every ballot, grouped by voter, plus an exact summary.

    Rows are tallied as they stream past, which costs O(1) memory — so the summary
    is always exact no matter how large the table gets. Only the retained per-voter
    detail is capped: that is the part that grows linearly and would eventually
    exceed Lambda's 6 MB response limit (~104k ballots). Past the cap we keep
    counting and stop keeping.
    """
    counts = collections.Counter()          # uid -> exact ballot count
    ballots = collections.defaultdict(list)  # uid -> retained detail (may be partial)
    affiliations = {}                        # uid -> affiliation, voters and lurkers alike
    choices = dict.fromkeys(CHOICES, 0)
    retained, truncated, kwargs = 0, False, {}

    while True:
        resp = table().scan(
            FilterExpression="begins_with(SK, :v) OR SK = :p",
            ProjectionExpression="PK,SK,choice,ts,affiliation",
            ExpressionAttributeValues={":v": "VOTE#", ":p": "PROFILE"},
            **kwargs,
        )
        for r in resp["Items"]:
            uid = r["PK"].removeprefix("USER#")
            if r["SK"] == "PROFILE":
                affiliations[uid] = r["affiliation"]
                continue
            counts[uid] += 1
            if r["choice"] in choices:
                choices[r["choice"]] += 1
            if retained < detail_cap:
                ballots[uid].append({
                    "item_id": r["SK"].removeprefix("VOTE#"),
                    "choice": r["choice"],
                    "ts": int(r.get("ts", 0)),
                })
                retained += 1
            else:
                truncated = True
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # A PROFILE with no ballots is not a voter: excluded here so every tally in
    # `summary` covers the same population and the buckets sum to `voters`.
    identified = collections.Counter(
        affiliations[uid] for uid in counts if uid in affiliations
    )
    aff = {a: identified.get(a, 0) for a in AFFILIATIONS}
    aff["unknown"] = len(counts) - sum(aff.values())

    return {
        "summary": {
            "voters": len(counts),
            "ballots": sum(counts.values()),
            "choices": choices,
            "affiliations": aff,
        },
        "voters": [
            {
                "uid": uid,
                "affiliation": affiliations.get(uid),
                "ballot_count": n,
                "ballots": sorted(ballots.get(uid, []), key=lambda b: b["ts"], reverse=True),
            }
            for uid, n in counts.most_common()
        ],
        "detail_truncated": truncated,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_db_votes.py -v
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Run the whole backend suite for regressions**

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

Expected: every test passes. `list_all_votes` adds a scan filter that must not disturb existing behavior.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db.py backend/tests/test_db_votes.py
git commit -m "feat(db): list_all_votes with exact summary and capped detail"
```

---

## Task 2: `GET /api/admin/votes`

**Files:**
- Modify: `backend/app/admin_routes.py` (add handler near `list_items`, `admin_routes.py:100`; add dispatch entry near `admin_routes.py:124`)
- Test: `backend/tests/test_routes_admin.py` (append)

**Interfaces:**
- Consumes: `db.list_all_votes()` from Task 1.
- Produces: `GET /api/admin/votes` → 200 with the Task 1 dict, 401 when unauthenticated. Tasks 4–7 consume this over HTTP.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_routes_admin.py`:

```python
def test_admin_votes_requires_auth(fresh_table):
    resp, _ = call(apigw_event("GET", "/api/admin/votes"))
    assert resp["statusCode"] == 401


def test_admin_votes_returns_summary_and_voters(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.set_affiliation("u1", "left")
    db.record_vote("u1", "katan", "left")
    db.record_vote("u2", "katan", "right")

    resp, body = call(apigw_event("GET", "/api/admin/votes", admin=True))

    assert resp["statusCode"] == 200
    assert body["summary"]["voters"] == 2
    assert body["summary"]["ballots"] == 2
    assert body["summary"]["affiliations"] == {
        "right": 0, "left": 1, "center": 0, "unknown": 1
    }
    assert body["detail_truncated"] is False
    assert {v["uid"] for v in body["voters"]} == {"u1", "u2"}
    assert body["voters"][0]["ballots"][0]["item_id"] == "katan"


def test_admin_votes_empty_table(fresh_table):
    resp, body = call(apigw_event("GET", "/api/admin/votes", admin=True))
    assert resp["statusCode"] == 200
    assert body["summary"]["voters"] == 0
    assert body["voters"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_routes_admin.py -k votes -v
```

Expected: `test_admin_votes_requires_auth` PASSES already (unknown admin paths are gated before routing, so it 401s for the right reason). The other two FAIL with `assert 404 == 200`.

- [ ] **Step 3: Implement**

In `backend/app/admin_routes.py`, add after `list_items` (ends at `admin_routes.py:101`):

```python
def list_votes(event):
    return http.response(200, db.list_all_votes())
```

In `dispatch`, add after the `GET /api/admin/items` entry (`admin_routes.py:124-125`):

```python
    if (method, path) == ("GET", "/api/admin/votes"):
        return list_votes(event)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_routes_admin.py -v
```

Expected: all tests PASS, including the pre-existing ones.

- [ ] **Step 5: Run the whole backend suite**

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/admin_routes.py backend/tests/test_routes_admin.py
git commit -m "feat(admin): GET /api/admin/votes endpoint"
```

---

## Task 3: Three-tab admin shell

No votes data yet — this task only restructures the existing page so a reviewer can judge the tab mechanics on their own.

**Files:**
- Modify: `site/admin/index.html:33-55`
- Modify: `site/admin/admin.css` (append)
- Modify: `site/admin/admin.js` (add tab controller; update `loadQueue`)

**Interfaces:**
- Produces: `showTab(name)` where `name` is one of `"queue" | "items" | "votes"`; panel elements `#panel-queue`, `#panel-items`, `#panel-votes`; `localStorage` key `lr_admin_tab`. Task 4 hooks lazy loading into `showTab`.

- [ ] **Step 1: Restructure the markup**

Replace `site/admin/index.html:33-55` (the whole `<main id="admin-main">` block) with:

```html
  <main id="admin-main" class="hidden">
    <nav class="tabs" id="tabs">
      <button class="tab" data-tab="queue">הצעות <span class="tab-count" id="tab-count"></span></button>
      <button class="tab" data-tab="items">פריטים</button>
      <button class="tab" data-tab="votes">הצבעות</button>
    </nav>

    <section id="panel-queue" class="hidden">
      <h2>הצעות ממתינות</h2>
      <div id="queue"></div>
    </section>

    <section id="panel-items" class="hidden">
      <h2>פריט חדש</h2>
      <form id="create-form">
        <input id="c-id" placeholder="item-id (a-z, 0-9, -)" pattern="[a-z0-9-]{1,64}">
        <input id="c-name" placeholder="שם בעברית" required>
        <input id="c-emoji" placeholder="אימוג׳י" size="4">
        <select id="c-cat" required aria-label="קטגוריה"></select>
        <label><input type="checkbox" id="c-image"> עם תמונה</label>
        <input type="file" id="c-file" accept="image/*" class="hidden" aria-label="תמונה">
        <button type="submit">יצירה</button>
      </form>
      <label class="inline"><input type="checkbox" id="show-archived"> הצג בארכיון</label>
      <h2>פריטים</h2>
      <div id="items"></div>
    </section>

    <section id="panel-votes" class="hidden">
      <h2>הצבעות</h2>
      <div id="votes-body"></div>
    </section>
  </main>
```

- [ ] **Step 2: Add the styles**

Append to `site/admin/admin.css`:

```css
.tabs { display: flex; gap: 4px; margin-top: 18px; border-bottom: 2px solid var(--surface); }
.tab { background: none; color: var(--muted); border: none; border-bottom: 3px solid transparent; margin-bottom: -2px; padding: 8px 12px; font-size: 14px; font-weight: 900; cursor: pointer; }
.tab.active { color: var(--ink); border-bottom-color: var(--ink); }
.tab-count { font-size: 11px; color: var(--muted); }
#panel-queue, #panel-items, #panel-votes { margin-top: 8px; }
```

- [ ] **Step 3: Add the tab controller**

In `site/admin/admin.js`, add a new banner section immediately before `/* ---- Cognito sign-in (CLOUD mode) ---- */` (currently `admin.js:247`):

```js
/* ---- tabs ---- */
const TAB_KEY = "lr_admin_tab";
const TABS = ["queue", "items", "votes"];

function showTab(name) {
  if (!TABS.includes(name)) name = "queue";
  for (const t of TABS) {
    $(`panel-${t}`).classList.toggle("hidden", t !== name);
  }
  for (const btn of $("tabs").querySelectorAll(".tab")) {
    btn.classList.toggle("active", btn.dataset.tab === name);
  }
  // Private-mode Safari throws on setItem; a lost tab preference is not worth failing over.
  try { localStorage.setItem(TAB_KEY, name); } catch { /* ignore */ }
}

function initTabs() {
  for (const btn of $("tabs").querySelectorAll(".tab")) {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  }
  let saved = null;
  try { saved = localStorage.getItem(TAB_KEY); } catch { /* ignore */ }
  showTab(saved || "queue");
}
```

- [ ] **Step 4: Show the pending count on the tab**

In `loadQueue` (`admin.js:60`), immediately after the `$("queue").innerHTML = ...` assignment ends, add:

```js
  const pending = (body.suggestions || []).length;
  $("tab-count").textContent = pending ? `(${pending})` : "";
```

- [ ] **Step 5: Call `initTabs` from both boot paths**

In `enterAdmin` (`admin.js:293`), add `initTabs();` immediately after `initCreateForm();`.

In the boot IIFE's LOCAL branch (`admin.js:312-316`), add `initTabs();` immediately after `initCreateForm();`.

- [ ] **Step 6: Verify manually**

```bash
docker compose up -d dynamodb
./scripts/local-dev.sh
```

Open `http://localhost:8080/admin/`. Confirm:
- Three tabs render right-to-left as **הצעות · פריטים · הצבעות**, with הצעות active.
- Clicking each tab shows exactly one panel.
- `פריט חדש`, the archived toggle, and the items list are all inside פריטים.
- Reloading the page returns to the last tab you selected.
- The suggestions count appears on the הצעות tab when the queue is non-empty.

Then **stop the dev server and the container**:

```bash
docker compose down
```

- [ ] **Step 7: Commit**

```bash
git add site/admin/index.html site/admin/admin.css site/admin/admin.js
git commit -m "feat(admin): three-tab shell for the admin panel"
```

---

## Task 4: Votes panel — summary and per-voter drill-down

**Files:**
- Modify: `site/admin/index.html` (`#panel-votes` body)
- Modify: `site/admin/admin.css` (append)
- Modify: `site/admin/admin.js` (new votes section; hook into `showTab`)

**Interfaces:**
- Consumes: `GET /api/admin/votes` (Task 2), `showTab` (Task 3).
- Produces: module state `VOTES` (the endpoint payload or `null`) and `ITEMS_BY_ID` (`Map<string, item>`); functions `loadVotes()`, `renderVotes()`, `relTime(ts)`, and the constant maps `CHOICE_HE` / `AFF_HE`. Tasks 5–7 consume all of these.

- [ ] **Step 1: Replace the votes panel body**

In `site/admin/index.html`, replace `<div id="votes-body"></div>` with:

```html
      <div id="votes-warn" class="warn hidden"></div>
      <div id="votes-summary"></div>
      <div id="votes-list"></div>
```

- [ ] **Step 2: Add the styles**

Append to `site/admin/admin.css`:

```css
.warn { background: var(--surface); border-right: 4px solid var(--left-a); padding: 8px 10px; margin-top: 12px; font-size: 12px; }
#votes-summary { margin-top: 14px; border-bottom: 1px solid var(--surface); padding-bottom: 12px; }
.sum-line { font-size: 15px; font-weight: 700; }
.sum-line b { font-size: 22px; font-weight: 900; }
.voter { border-bottom: 1px solid var(--surface); }
.voter-head { display: flex; gap: 10px; align-items: center; width: 100%; background: none; border: none; color: var(--ink); padding: 10px 2px; text-align: start; font-weight: 400; cursor: pointer; }
.voter-head .grow { flex: 1; }
.voter-head code { color: var(--muted); font-size: 12px; }
.caret { color: var(--muted); font-size: 11px; }
.chip { font-size: 11px; font-weight: 700; border: 1px solid var(--muted); color: var(--muted); padding: 1px 6px; }
.ballot { display: flex; gap: 10px; align-items: center; padding: 5px 2px 5px 22px; font-size: 13px; }
.ballot .grow { flex: 1; }
.choice { font-weight: 700; font-size: 12px; }
.choice.left { color: var(--left-a); }
.choice.right { color: var(--right-a); }
.choice.neutral { color: var(--muted); }
```

- [ ] **Step 3: Add the votes module**

In `site/admin/admin.js`, add a new banner section immediately before `/* ---- tabs ---- */`:

```js
/* ---- votes ---- */
let VOTES = null;
let ITEMS_BY_ID = new Map();

const CHOICE_HE = { left: "שמאלני", right: "ימני", neutral: "ניטרלי" };
const AFF_HE = { left: "שמאל", right: "ימין", center: "מרכז" };

const RTF = new Intl.RelativeTimeFormat("he", { numeric: "auto" });
const REL_UNITS = [["year", 31536000], ["month", 2592000], ["day", 86400],
                   ["hour", 3600], ["minute", 60]];

// Intl gives correct Hebrew forms for free — "לפני יומיים", not "לפני 2 ימים".
function relTime(ts) {
  if (!ts) return "";
  const diff = ts - Date.now() / 1000;
  for (const [unit, secs] of REL_UNITS) {
    if (Math.abs(diff) >= secs) return RTF.format(Math.round(diff / secs), unit);
  }
  return RTF.format(Math.round(diff), "second");
}

async function loadVotes() {
  // Item names and the cross-tab counters live on /api/admin/items, so the votes
  // payload can stay slim and carry item_id only.
  const [votes, items] = await Promise.all([
    api("/api/admin/votes"),
    api("/api/admin/items"),
  ]);
  if (votes.status !== 200) return toast(`שגיאה בטעינת ההצבעות (${votes.status})`);
  if (items.status !== 200) return toast(`שגיאה בטעינת הפריטים (${items.status})`);
  VOTES = votes.body;
  ITEMS_BY_ID = new Map((items.body.items || []).map((i) => [i.id, i]));
  renderVotes();
}

function renderVotes() {
  if (!VOTES) return;
  const s = VOTES.summary;
  const a = s.affiliations;

  $("votes-warn").classList.toggle("hidden", !VOTES.detail_truncated);
  if (VOTES.detail_truncated) {
    $("votes-warn").textContent =
      "המספרים למעלה מדויקים; פירוט ההצבעות לכל מצביע חלקי בלבד.";
  }

  $("votes-summary").innerHTML =
    `<div class="sum-line"><b>${s.voters}</b> מצביעים · <b>${s.ballots}</b> הצבעות</div>
     <div class="muted">שמאלני ${s.choices.left} · ימני ${s.choices.right} · ניטרלי ${s.choices.neutral}</div>
     <div class="muted">זיהוי: ${a.left} שמאל · ${a.right} ימין · ${a.center} מרכז · ${a.unknown} ללא</div>
     <div class="muted">מזהי המצביעים אנונימיים — עוגייה אקראית, ללא שם או כתובת.</div>`;

  renderVoters();
}

function renderVoters() {
  const voters = VOTES.voters || [];
  if (!voters.length) {
    $("votes-list").innerHTML =
      '<p class="muted" style="margin-top:10px">עדיין אין הצבעות.</p>';
    return;
  }
  $("votes-list").innerHTML = voters.map((v) => {
    const last = v.ballots.length ? Math.max(...v.ballots.map((b) => b.ts)) : 0;
    return `<div class="voter">
      <button class="voter-head">
        <span class="caret">▸</span>
        <code>${esc(v.uid.slice(0, 8))}…</code>
        <span class="grow">${v.ballot_count} הצבעות</span>
        <span class="chip">${esc(v.affiliation ? AFF_HE[v.affiliation] : "—")}</span>
        <span class="muted">${esc(relTime(last))}</span>
      </button>
      <div class="ballots hidden">${v.ballots.map(ballotRowHTML).join("")}</div>
    </div>`;
  }).join("");

  for (const el of $("votes-list").querySelectorAll(".voter")) {
    el.querySelector(".voter-head").addEventListener("click", () => {
      const open = el.querySelector(".ballots").classList.toggle("hidden") === false;
      el.querySelector(".caret").textContent = open ? "▾" : "▸";
    });
  }
}

function ballotRowHTML(b) {
  const item = ITEMS_BY_ID.get(b.item_id);
  return `<div class="ballot">
    <span class="grow">${esc(item ? item.name : b.item_id)}</span>
    <span class="choice ${esc(b.choice)}">${esc(CHOICE_HE[b.choice] || b.choice)}</span>
    <span class="muted">${esc(relTime(b.ts))}</span>
  </div>`;
}
```

- [ ] **Step 4: Load votes lazily when the tab opens**

In `showTab` (Task 3), add before the closing brace, after the `localStorage` write:

```js
  if (name === "votes" && !VOTES) loadVotes();
```

- [ ] **Step 5: Verify manually**

```bash
docker compose up -d dynamodb
./scripts/local-dev.sh
```

The local seed creates items but no votes, so first confirm the empty state reads `עדיין אין הצבעות`, then cast a few votes at `http://localhost:8080/` (including answering the ימני/שמאלני card) and reload `http://localhost:8080/admin/`.

Confirm on the הצבעות tab:
- Summary counts match what you voted.
- The affiliation line's four numbers sum to the voter count.
- A voter row expands and collapses, caret flips ▸/▾, and ballots show Hebrew item names, a colored Hebrew choice, and a relative time such as `לפני דקה`.
- The votes request fires only when you first open the tab (check the Network panel).

```bash
docker compose down
```

- [ ] **Step 6: Commit**

```bash
git add site/admin/index.html site/admin/admin.css site/admin/admin.js
git commit -m "feat(admin): votes tab with summary and per-voter ballots"
```

---

## Task 5: Cross-tab view (לפי פריט)

**Files:**
- Modify: `site/admin/index.html` (`#panel-votes`)
- Modify: `site/admin/admin.css` (append)
- Modify: `site/admin/admin.js` (votes section)

**Interfaces:**
- Consumes: `ITEMS_BY_ID`, `renderVoters`, `AFF_HE` (Task 4).
- Produces: `VOTES_VIEW` (`"voters" | "items"`) and `renderVotesList()`. Task 7's auto-refresh re-renders through `renderVotes`, which must respect the current view.

- [ ] **Step 1: Add the segmented control markup**

In `site/admin/index.html`, insert between `<div id="votes-summary"></div>` and `<div id="votes-list"></div>`:

```html
      <div class="votes-bar">
        <div class="seg" id="votes-seg">
          <button class="seg-btn active" data-view="voters">מצביעים</button>
          <button class="seg-btn" data-view="items">לפי פריט</button>
        </div>
      </div>
```

- [ ] **Step 2: Add the styles**

Append to `site/admin/admin.css`:

```css
.votes-bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.seg { display: flex; }
.seg-btn { background: none; color: var(--muted); border: 2px solid var(--muted); padding: 5px 12px; font-size: 13px; font-weight: 700; cursor: pointer; }
.seg-btn.active { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.xt-row { border-bottom: 1px solid var(--surface); padding: 9px 2px; }
.xt-head { display: flex; gap: 10px; align-items: center; }
.xt-head .grow { flex: 1; }
.xt-line { padding-right: 12px; }
```

- [ ] **Step 3: Add the view switch**

In `site/admin/admin.js`, add to the votes section after `renderVotes`:

```js
let VOTES_VIEW = "voters";

function renderVotesList() {
  if (VOTES_VIEW === "items") renderItemsCross();
  else renderVoters();
}

function renderItemsCross() {
  const total = (i) => i.votes_left + i.votes_right + i.votes_neutral;
  const items = [...ITEMS_BY_ID.values()]
    .filter((i) => total(i) > 0)
    .sort((a, b) => total(b) - total(a));

  if (!items.length) {
    $("votes-list").innerHTML =
      '<p class="muted" style="margin-top:10px">עדיין אין הצבעות.</p>';
    return;
  }

  $("votes-list").innerHTML = items.map((i) => {
    // xt_* counters are denormalized onto each item at vote time, so no join needed.
    const lines = ["right", "left", "center"].map((aff) => {
      const l = i[`xt_${aff}_left`], r = i[`xt_${aff}_right`], n = i[`xt_${aff}_neutral`];
      return l + r + n === 0
        ? ""
        : `<div class="xt-line muted">${esc(AFF_HE[aff])}: שמאלני ${l} · ימני ${r} · ניטרלי ${n}</div>`;
    }).join("");
    return `<div class="xt-row">
      <div class="xt-head">
        <span class="grow">${esc(i.name)}</span>
        <span class="muted">${i.votes_left}/${i.votes_right}/${i.votes_neutral}</span>
      </div>
      ${lines || '<div class="xt-line muted">אף מצביע לא הזדהה.</div>'}
    </div>`;
  }).join("");
}

function initVotesSeg() {
  for (const btn of $("votes-seg").querySelectorAll(".seg-btn")) {
    btn.addEventListener("click", () => {
      VOTES_VIEW = btn.dataset.view;
      for (const b of $("votes-seg").querySelectorAll(".seg-btn")) {
        b.classList.toggle("active", b === btn);
      }
      renderVotesList();
    });
  }
}
```

- [ ] **Step 4: Route rendering through the switch**

In `renderVotes` (Task 4), change the final line from `renderVoters();` to `renderVotesList();`.

In `initTabs` (Task 3), add `initVotesSeg();` as the first line of the function body.

- [ ] **Step 5: Verify manually**

Run the dev server as in Task 4. On the הצבעות tab:
- `לפי פריט` lists items with the most votes first, each showing `L/R/N` and one line per affiliation that actually voted on it.
- Items with zero votes are absent.
- An item voted on only by unidentified visitors shows `אף מצביע לא הזדהה.`
- Switching back to `מצביעים` restores the voter list.
- Cross-check one item's numbers against the פריטים tab, which shows the same `L/R/N`.

```bash
docker compose down
```

- [ ] **Step 6: Commit**

```bash
git add site/admin/index.html site/admin/admin.css site/admin/admin.js
git commit -m "feat(admin): per-item cross-tab view in the votes tab"
```

---

## Task 6: CSV export

**Files:**
- Modify: `site/admin/index.html` (`.votes-bar`)
- Modify: `site/admin/admin.js` (votes section)

**Interfaces:**
- Consumes: `VOTES`, `ITEMS_BY_ID` (Task 4), `.votes-bar` (Task 5).
- Produces: `votesCsv()` returning a BOM-prefixed CSV string, and `initVotesCsv()`.

- [ ] **Step 1: Add the button**

In `site/admin/index.html`, inside `.votes-bar`, after the closing `</div>` of `#votes-seg`:

```html
        <button id="votes-csv" class="ghost">ייצוא CSV</button>
```

- [ ] **Step 2: Implement the export**

In `site/admin/admin.js`, add to the votes section after `initVotesSeg`:

```js
const csvCell = (s) => `"${String(s).replace(/"/g, '""')}"`;

function votesCsv() {
  const rows = [["uid", "item_id", "name", "choice", "timestamp"]];
  for (const v of VOTES.voters) {
    for (const b of v.ballots) {
      const item = ITEMS_BY_ID.get(b.item_id);
      rows.push([v.uid, b.item_id, item ? item.name : "", b.choice,
                 new Date(b.ts * 1000).toISOString()]);
    }
  }
  // U+FEFF BOM: without it Excel reads the file as cp1255 and Hebrew comes out as mojibake.
  return "﻿" + rows.map((r) => r.map(csvCell).join(",")).join("\r\n");
}

function initVotesCsv() {
  $("votes-csv").addEventListener("click", () => {
    if (!VOTES) return toast("אין נתונים לייצוא");
    const blob = new Blob([votesCsv()], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `votes-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast(VOTES.detail_truncated ? "הייצוא חלקי — יותר מדי הצבעות" : "יוצא ✓");
  });
}
```

- [ ] **Step 3: Wire it up**

In `initTabs` (Task 3), add `initVotesCsv();` immediately after the `initVotesSeg();` line added in Task 5.

- [ ] **Step 4: Verify manually**

Run the dev server. On the הצבעות tab click `ייצוא CSV`, then:
- Confirm the file downloads as `votes-YYYY-MM-DD.csv`.
- Open it in LibreOffice (`libreoffice --calc ~/Downloads/votes-*.csv`) and confirm the Hebrew item names render correctly and each row has five columns.
- Confirm the row count equals the total ballots shown in the summary.

```bash
docker compose down
```

- [ ] **Step 5: Commit**

```bash
git add site/admin/index.html site/admin/admin.js
git commit -m "feat(admin): CSV export of the ballot log"
```

---

## Task 7: Visibility-gated auto-refresh

**Files:**
- Modify: `site/admin/admin.js` (votes section, `showTab`)

**Interfaces:**
- Consumes: `loadVotes` (Task 4), `showTab` (Task 3).
- Produces: `votesAutoRefresh(on)`.

- [ ] **Step 1: Implement the timer**

In `site/admin/admin.js`, add to the votes section after `initVotesCsv`:

```js
const VOTES_POLL_MS = 30000;
let votesTimer = null;

// Gated twice: the tab must be the active one AND the browser tab must be visible.
// /api/admin/votes is a full table scan behind a CachingDisabled behavior, so a
// backgrounded window left open overnight would otherwise scan all night.
function votesAutoRefresh(on) {
  clearInterval(votesTimer);
  votesTimer = null;
  if (!on) return;
  votesTimer = setInterval(() => {
    if (document.visibilityState === "visible") loadVotes();
  }, VOTES_POLL_MS);
}
```

- [ ] **Step 2: Drive it from tab switches**

In `showTab` (Task 3), replace the lazy-load line added in Task 4:

```js
  if (name === "votes" && !VOTES) loadVotes();
```

with:

```js
  if (name === "votes" && !VOTES) loadVotes();
  votesAutoRefresh(name === "votes");
```

- [ ] **Step 3: Preserve the open voter on refresh**

Auto-refresh re-renders the list, which would collapse whichever voter the user had expanded. In `renderVoters` (Task 4), capture and restore the open rows. Replace the `for (const el of ...)` wiring block at the end of `renderVoters` with:

```js
  const els = [...$("votes-list").querySelectorAll(".voter")];
  els.forEach((el, idx) => {
    if (VOTES_OPEN.has(voters[idx].uid)) {
      el.querySelector(".ballots").classList.remove("hidden");
      el.querySelector(".caret").textContent = "▾";
    }
    el.querySelector(".voter-head").addEventListener("click", () => {
      const open = el.querySelector(".ballots").classList.toggle("hidden") === false;
      el.querySelector(".caret").textContent = open ? "▾" : "▸";
      if (open) VOTES_OPEN.add(voters[idx].uid);
      else VOTES_OPEN.delete(voters[idx].uid);
    });
  });
```

and declare the set alongside the other votes state, next to `let VOTES = null;`:

```js
const VOTES_OPEN = new Set();
```

- [ ] **Step 4: Verify manually**

Run the dev server and open the הצבעות tab with DevTools' Network panel filtered to `votes`.
- Confirm a request fires roughly every 30s while the tab is open and focused.
- Switch to the פריטים tab: requests stop.
- Return to הצבעות, then switch to a different **browser** tab for over 30s: no requests fire while hidden.
- Expand a voter and wait for a refresh: the row stays expanded.
- Cast a vote in another window and confirm the counts update within 30s.

```bash
docker compose down
```

- [ ] **Step 5: Commit**

```bash
git add site/admin/admin.js
git commit -m "feat(admin): visibility-gated auto-refresh for the votes tab"
```

---

## Task 8: `/admin` 301 redirect

**Files:**
- Modify: `terraform/cloudfront.tf:36-45`

**Interfaces:**
- Produces: updated `aws_cloudfront_function.dir_index` code. No consumers in code; verified by HTTP.

- [ ] **Step 1: Update the function**

Replace the `code` heredoc in `aws_cloudfront_function.dir_index` (`terraform/cloudfront.tf:36-44`) with:

```hcl
  code    = <<-JS
    function handler(event) {
      var req = event.request;
      // Extensionless and slashless (e.g. "/admin") means a directory: send the
      // browser to the canonical trailing-slash URL. The dot test is load-bearing —
      // "/admin/config.json" has a dot, so it is never rewritten and still 404s when
      // absent. If that path ever returned HTML, admin.js would boot LOCAL mode and
      // the panel would have no authentication at all.
      if (!req.uri.endsWith("/") && !req.uri.split("/").pop().includes(".")) {
        return {
          statusCode: 301,
          statusDescription: "Moved Permanently",
          headers: { location: { value: req.uri + "/" } }
        };
      }
      if (req.uri.endsWith("/")) {
        req.uri += "index.html";
      }
      return req;
    }
  JS
```

Also update the resource's `comment` on `cloudfront.tf:34` to:

```hcl
  comment = "Redirect extensionless URIs to a trailing slash, then append index.html; S3 origins have no directory index."
```

- [ ] **Step 2: Validate and plan**

```bash
cd terraform && terraform fmt -check && terraform validate && terraform plan -var-file=realvote.tfvars
```

Expected: `terraform validate` succeeds; the plan shows exactly one change — `aws_cloudfront_function.dir_index` updated in place (`code` and `comment`), which forces a republish of the function and an update to the distribution. **Do not apply.**

- [ ] **Step 3: Commit**

```bash
git add terraform/cloudfront.tf
git commit -m "fix(tf): redirect extensionless URIs to trailing slash so /admin loads"
```

---

## Task 9: Full verification and handoff

No code changes. This task produces the evidence that the branch is ready and the list of deploy commands for Ariel to run himself.

- [ ] **Step 1: Full backend suite**

```bash
docker compose up -d dynamodb
cd backend && ../.venv/bin/python -m pytest -q
```

Expected: every test passes. Record the count.

- [ ] **Step 2: End-to-end local pass**

```bash
./scripts/local-dev.sh
```

Walk the whole admin panel once: all three tabs, both votes views, an expand/collapse, a CSV export, and a create/archive round-trip on the פריטים tab to confirm Task 3's restructure did not break the existing forms.

- [ ] **Step 3: Confirm no leftover processes**

```bash
docker compose down
docker ps | grep -i dynamo   # expect no output
pgrep -af local_server.py    # expect no output
```

- [ ] **Step 4: Review the diff**

```bash
git diff main...feat/admin-votes-tab --stat
```

- [ ] **Step 5: Hand the deploy commands to Ariel**

Report — do not run — the remaining steps, which are his:

```bash
cd terraform && terraform apply -var-file=realvote.tfvars   # publishes the CloudFront function
./scripts/deploy.sh                                          # Lambda + site upload + invalidation
```

Post-deploy verification for him to run:

```bash
for u in /admin /admin/ /admin/config.json; do
  printf "%-22s " "$u"
  curl -s -o /dev/null -w "%{http_code}\n" "https://realvote.latnook.com$u"
done
# expect: /admin 301, /admin/ 200, /admin/config.json 403
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: §1.2 the 301 → Task 8; §2.3 `list_all_votes` → Task 1; §2.4 the route → Task 2; §2.5 the response shape → Tasks 1–2; §2.6 the tab bar → Task 3; §2.7 the panel, relative times, BOM, auto-refresh gating → Tasks 4–7; §2.8 error handling → Tasks 2 and 4 (401/non-200 toasts, empty state, truncation banner, deleted-item fallback in `ballotRowHTML`); §3 testing → Tasks 1, 2, and the manual steps in 3–7 plus Task 9.

**Placeholder scan.** No TBD/TODO. Every code step carries the literal code to write. Task boundaries repeat the identifiers they depend on in their **Interfaces** block rather than saying "as in Task N".

**Type consistency.** `ballot_count` is produced in Task 1, serialized in Task 2, and read in Task 4's `renderVoters`. `VOTES` / `ITEMS_BY_ID` / `AFF_HE` / `CHOICE_HE` are declared in Task 4 and consumed by name in Tasks 5–7. `renderVotesList` is introduced in Task 5, and Task 5 Step 4 explicitly changes `renderVotes`'s last line from `renderVoters()` to it. `VOTES_OPEN` is declared in Task 7 Step 3 and used in the same step. `showTab` is defined in Task 3 and edited by Tasks 4 and 7, each quoting the exact prior line being replaced.
