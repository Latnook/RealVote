# LR — self-identification & categories — Design

**Date:** 2026-08-07
**Status:** Approved by Ariel (2026-08-07)
**Builds on:** `2026-08-06-lr-voting-site-design.md` (base design), Plans 1 & 2 (backend + frontend, merged to `main`)

Two features added to the live-locally voting site, before the AWS deploy plan:

1. **Self-identification** — a one-time "האם אתה ימני או שמאלני?" card whose answer cross-tabulates
   every vote ("78% מהימנים חושבים שזה שמאלני").
2. **Categories** — one category per item, with visitor-toggleable filters.

---

## 1. Self-identification

### 1.1 The card

A special card, not a regular item. Rendered with the same K² layout and the same three-way
mechanic (buttons / arrow keys / swipe), differing only in:

| Element | Value |
|---|---|
| Title | `האם אתה ימני או שמאלני?` (standard spelling שמאלני; user's phrasing, kept verbatim) |
| Media | `🫵` (emoji fallback path — no image) |
| Right button | `ימני →` (blue gradient, unchanged) |
| Left button | `← שמאלני` (red gradient, unchanged) |
| Bottom strip | `מרכז משעמם ↓` (replaces `ניטרלי ↓` **on this card only**) |

Choice values on the wire: `right` / `left` / `center`.

**When it appears.** A threshold `k` is drawn uniformly from 3–10 (inclusive) on first visit and
persisted in `localStorage` (`lr_affq_at`) so a reload does not move it. The card is shown once the
visitor's **total** vote count (server truth from `/api/me`, not a session counter) reaches `k` —
so a returning visitor who already has 12 votes and no affiliation sees it on their next card
rather than never. Shown once ever per visitor.

**Deck-exhaustion fallback:** if the visitor reaches the end of the deck (or of their filtered
subset) without hitting the drawn position and has not yet answered, the card is shown immediately
before the end screen. Everyone is asked exactly once.

**Not a vote.** The card does not advance the `NN/MM` counter, does not count toward the 5-vote
threshold that reveals the ➕ FAB, and never appears in "ההצבעות שלי".

### 1.2 Storage

One record per visitor, keyed by the existing anonymous cookie id:

```
PK = USER#<uid>
SK = PROFILE
affiliation = "right" | "left" | "center"
ts          = <epoch seconds>
```

Written with `attribute_not_exists(PK)` — answering is once-only; a second attempt returns `409`.

Global tallies for the card's own reveal live on a singleton record:

```
PK = STATS
SK = AFFILIATION
affil_right / affil_left / affil_center   (atomic ADD)
```

**Privacy.** The uid is a random 32-hex value with no name, email, account, or stored IP attached.
Political affiliation is held only as one of three values against that random id, exactly as votes
already are. The admin surface exposes aggregates only — never individual rows.

**Cookie behaviour.** The affiliation is *not* written into a browser cookie; it is stored server-side
against the cookie's uid and returned by `GET /api/me`, which the page already calls at load. Net
effect for the visitor is "the site remembers me", without a client-editable value.

### 1.3 Cross-tab counters

Every item carries nine additional counters, all `int`, all default `0`:

```
xt_<affiliation>_<choice>   for affiliation ∈ {right,left,center}, choice ∈ {left,right,neutral}
```

e.g. `xt_right_left` = number of self-identified **ימנים** who voted **שמאלני** on this item.

**On vote.** `record_vote` reads the voter's `PROFILE` (one `GetItem`). If an affiliation exists, the
matching `xt_*` counter is incremented **in the same `UpdateExpression`** as the main counter, inside
the existing `TransactWriteItems` — no extra transaction item, no new failure mode. Voters with no
affiliation yet increment only the main counters.

**On answering (back-fill).** When the affiliation is claimed successfully:

1. conditional put of `PROFILE` (claims the answer; `409` if already set),
2. `ADD` the global `affil_*` counter,
3. query the visitor's existing votes (`get_user_votes`, one query),
4. for each voted item, `ADD` the matching `xt_<aff>_<choice>` counter (≤ ~10 `UpdateItem` calls).

Steps 3–4 are best-effort: a crash mid-back-fill leaves some of that visitor's earlier votes
uncounted in the cross-tabs. Accepted — these are approximate display statistics, the claim in
step 1 is what must be exact, and it is.

### 1.4 Display rule — cross-attribution only

No bars and no symmetric comparison. The reveal gains **a single sentence**, and only in the one
genuinely interesting case: **a camp overwhelmingly assigning an item to the opposite camp.**

For each camp `C ∈ {right, left}` independently, with `decisive_C = xt_C_left + xt_C_right`
(neutral excluded, matching the main bar):

| Camp | Shown when | Line |
|---|---|---|
| ימנים | `decisive_right ≥ 25` **and** `xt_right_left / decisive_right > 0.70` | `NN% מהימנים חושבים שזה שמאלני` |
| שמאלנים | `decisive_left ≥ 25` **and** `xt_left_right / decisive_left > 0.70` | `NN% מהשמאלנים חושבים שזה ימני` |

Gated additionally on the viewer having answered the identity question.

The two lines are evaluated independently and **both may appear at once** — each camp disowning the
item onto the other, which is the strongest result the site can produce. A camp claiming an item as
its *own* is never shown: it carries no tension.

Constants (`XT_MIN_CAMP_VOTES = 25`, `XT_CROSS_THRESHOLD = 0.70`) live in one `const` block in the
frontend, and the rule is a single pure function so it can be reasoned about and checked against
boundary inputs in isolation.

Otherwise the reveal renders exactly as it does today. `center`-identified voters are counted
(`xt_center_*`) but never displayed; the data is retained for possible later use.

**Expected behaviour on a fresh site:** nothing qualifies until a camp accumulates 25 decisive votes
on an item *and* lands above 70% cross-attribution. The feature switches itself on as traffic
arrives. This is intended, not a defect.

### 1.5 The card's own reveal

After answering, the same bar mechanic shows the national split from the `STATS/AFFILIATION`
counters — ימנים (blue, right-anchored) vs שמאלנים (red, left-anchored), with `מרכז משעמם` as the
separate count line beneath, mirroring the neutral line on item cards. Then `הבא` continues into the
deck as normal.

---

## 2. Categories

### 2.1 The list

Backend owns the canonical list (slug → Hebrew label) and serves it to the browser, so there is one
source of truth and no drift:

| Slug | Label |
|---|---|
| `events` | אירועים |
| `travel` | חופשות וטיולים |
| `food` | אוכל |
| `home` | בית |
| `consumer` | צרכנות |
| `social` | חברתי |
| `sport` | ספורט |
| `movies` | סרטים |
| `tv` | תוכניות טלוויזיה |
| `conspiracy` | תיאוריות קונספירציה |
| `other` | אחר |

Adding a category is one line in that list plus a redeploy of static files and the Lambda.

### 2.2 Item model

Items gain `category` (string slug). Defaults to `other`, both at creation and defensively when an
older record has no such attribute — so no item can ever fall out of the deck. Invalid slugs are
rejected with `400`.

### 2.3 Filter UX

A `קטגוריות` section at the top of the ☰ panel: one toggle per category, **all on by default**,
selection persisted in `localStorage` (`lr_cats`; absence of the key means "all"). The panel already
exists and already traps focus / closes on Escape — the section is added inside it.

- The deck queue is the visitor's unvoted items **within the selected categories**.
- The counter reflects the filtered set (e.g. `04/09`, not `04/24`).
- Filters apply when the panel closes; the queue rebuilds, and if the card on screen no longer
  qualifies, it advances.
- Deselecting everything shows `בחרו לפחות קטגוריה אחת` in the card area instead of an empty screen
  or a false end screen.
- The end-screen agreement score is computed over the visitor's votes within the selected
  categories — a consequence of filtering, called out here because two visitors can legitimately
  finish "the whole site" with different denominators.

### 2.4 Admin

- Create-item form: category `<select>`, required, defaulting to `אחר`.
- Approve row: same `<select>` alongside the existing item-id / emoji inputs.
- `PATCH /api/admin/items/<id>` accepts `category`, so existing items can be re-filed.
- The items list shows each item's category label.

### 2.5 Seed content

The 24 seeded items are assigned categories in `backend/seed/items.json`. Ariel will add further
items and populate the remaining categories through the admin UI.

---

## 3. API changes

| Route | Change |
|---|---|
| `GET /api/items` | each item gains `category` and the nine `xt_*` counters; response gains a top-level `categories: [{slug, label}]`. Still CDN-cacheable ~30s (identical for all visitors). |
| `GET /api/me` | gains `affiliation`: `"right" \| "left" \| "center" \| null`. Never cached. |
| `POST /api/affiliation` | **new.** Body `{choice}` → `200 {affiliation, stats:{right,left,center}}`; `409` if already answered; `400` on an invalid choice. Sets the uid cookie if absent, like the other write routes. |
| `POST /api/admin/items` | accepts `category` (validated against the list; defaults `other`). |
| `POST /api/admin/suggestions/<sid>/approve` | accepts `category` (same validation/default). |
| `PATCH /api/admin/items/<id>` | accepts `category` in the field whitelist. |

Response-shape additions are backward-compatible; no existing key changes meaning.

## 4. Error handling

Unchanged posture: clean JSON errors, Hebrew toast on failure, the card stays put on a failed write.
A failed `POST /api/affiliation` (network or 5xx) leaves the question card on screen so the visitor
can retry; a `409` (already answered in another tab) is treated as success — the client refetches
`/api/me` for the truth and moves on.

## 5. Testing

**Backend (pytest, DynamoDB Local):**
- affiliation write succeeds once, `409` on repeat, `400` on invalid choice;
- back-fill: with N existing votes, answering increments exactly the matching `xt_*` counters;
- `record_vote` increments `xt_*` when a profile exists and only the main counters when it does not;
- global `affil_*` counters tally;
- `/api/me` returns the affiliation (and `null` before answering);
- category validation on create / approve / patch; unknown slug → `400`; default `other`;
- `/api/items` includes `category`, `xt_*`, and the `categories` list.

**Frontend:** headless-Chromium screenshots for the question card, its reveal, a qualifying
cross-attribution reveal (seeded to exceed the thresholds), a both-camps-disown reveal (both lines
at once), the category filter panel, and the filtered-empty state; console-hygiene greps; the
cross-attribution rule exercised as a pure function against boundary inputs (24 vs 25 decisive
votes; 70.0% vs 70.1%; a camp claiming the item as its own → no line).

## 6. Out of scope

Changing an answered affiliation; showing the `center` row in cross-tabs; per-category statistics
pages; multi-category items; server-side computation of the significance rule; category management
through the UI (the list is code).
