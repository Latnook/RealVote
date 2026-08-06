# LR Frontend — Implementation Plan (2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The complete K² "Swiss gradient slate" voting frontend — card deck, reveal, gestures, my-votes, suggest, end screen, admin page — as static files in `site/`, running against the Plan-1 backend via `./scripts/local-dev.sh`.

**Architecture:** Vanilla ES modules, no build step, no external dependencies (system font stack). `local_server.py` (Plan 1) serves `site/` and proxies `/api/*` to the Lambda handler, so the browser exercises the exact production code path.

**Tech Stack:** HTML/CSS/vanilla JS (ES modules). Verification: headless Chromium screenshots + `--dump-dom` greps; final human pass.

**Spec:** `docs/superpowers/specs/2026-08-06-lr-voting-site-design.md` §2–§3, §6. Backend API contract (Plan 1, all shipped): `GET /api/items → {"items":[{id,name,emoji,status,votes_left,votes_right,votes_neutral,image_key?}]}`, `GET /api/me → {"votes":{item_id:choice}}`, `POST /api/vote {item_id,choice} → 200 {"item":{...},"your_choice":c} | 400/404/409`, `POST /api/suggest {text} → 202 | 400/429`, admin routes under `/api/admin/*` (locally authorized via ALLOW_ADMIN=1).

## Global Constraints

- Everything `lang="he" dir="rtl"`, Hebrew-only copy, exact strings as given in tasks.
- Theme tokens exactly (theme.css): bg `#23262B`, ink `#F2F3F5`, muted `#8B9099`, surface `#2E3238`, ימני gradient `#3730A3→#0E7490`, שמאלני gradient `#B91C1C→#C2410C`, 2px ink rules, sharp corners (border-radius 0 everywhere except the FAB), gradient drift ~7s.
- Direction mapping is sacred: ימני = right side = blue = `→` = ArrowRight = swipe right; שמאלני = left side = red = `←` = ArrowLeft = swipe left; ניטרלי = `↓` = ArrowDown = swipe down. Reveal bar: red fill anchored to the LEFT edge, blue fill anchored to the RIGHT edge, growing toward each other.
- No frameworks, no CDN/external requests, no build step. ES modules only. No cookies handled in JS (lr_uid is HttpOnly; `fetch` same-origin sends it automatically).
- Every interactive control keyboard-reachable; images get alt text; `aria-label` on icon-only buttons.
- e2e/debug hooks (`?e2e=...` URL params) must be gated on `location.hostname === "localhost"` or `"127.0.0.1"`.
- Screenshots for verification go to the scratchpad dir `/tmp/claude-1000/-home-latnook-Documents-LR2026/7a82793f-40ca-41f0-9458-345ed55ad528/scratchpad/`.
- Local run for verification (from repo root): `docker compose up -d dynamodb`, then `TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ALLOW_ADMIN=1 .venv/bin/python backend/local_server.py` (background), seed once with `cd backend && TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python seed.py --votes 40`. Kill the server when done.
- Chromium screenshot invocation: `chromium --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=W,H --virtual-time-budget=4000 --screenshot=OUT URL`.

## File Structure

```
site/
├── index.html          # shell: topbar, stage, vote bar, overlays, toast
├── css/theme.css       # design tokens only (CSS variables + drift keyframes)
├── css/app.css         # all layout/component styles
├── js/api.js           # fetch wrappers (4 endpoints)
├── js/deck.js          # state, ordering, card render, vote, reveal, next/back
├── js/gestures.js      # keyboard + pointer swipe with tilt
├── js/panels.js        # menu/my-votes, suggest FAB+dialog, end screen, toast
├── js/app.js           # boot: wire modules together
└── admin/
    ├── index.html      # admin shell
    ├── admin.css       # admin-specific layout (reuses theme.css)
    └── admin.js        # local-mode/Cognito seam, queue + items CRUD, image upload
```

---

### Task 1: Shell, theme, static card

**Files:**
- Create: `site/index.html`, `site/css/theme.css`, `site/css/app.css`, `site/js/api.js`, `site/js/app.js` (placeholder boot)

**Interfaces:**
- Produces: the DOM contract every later task relies on — element ids `#menu-btn #counter #ghost #card-area #btn-right #btn-left #btn-neutral #fab #panel #toast`, classes `.hidden .drift`. api.js exports `getItems() getMe() vote(id,choice) suggest(text)` each resolving `{status, body}`.

- [ ] **Step 1: Write `site/css/theme.css`**

```css
/* K² "Swiss gradient slate" — the only file you edit to retheme the site. */
:root {
  --bg: #23262B;
  --ink: #F2F3F5;
  --muted: #8B9099;
  --surface: #2E3238;
  --right-a: #3730A3;  /* ימני gradient start (deep indigo) */
  --right-b: #0E7490;  /* ימני gradient end (deep cyan)    */
  --left-a: #B91C1C;   /* שמאלני gradient start (crimson)  */
  --left-b: #C2410C;   /* שמאלני gradient end (burnt orange) */
  --rule-w: 2px;
  --drift-period: 7s;
  --font: "Helvetica Neue", Helvetica, Arial, "Noto Sans Hebrew", "Segoe UI", sans-serif;
}

@keyframes drift {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
.drift {
  background-size: 250% 250%;
  animation: drift var(--drift-period) ease-in-out infinite;
}
@media (prefers-reduced-motion: reduce) {
  .drift { animation: none; }
}
```

- [ ] **Step 2: Write `site/css/app.css`**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }

html, body { height: 100%; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.hidden { display: none !important; }

/* ---- top bar ---- */
.topbar {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 14px 16px 0;
  gap: 12px;
}
.wordmark { font-size: 16px; font-weight: 900; letter-spacing: 1px; }
.dot {
  background: linear-gradient(90deg, var(--left-a), var(--left-b));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.counter { font-size: 12px; font-weight: 700; letter-spacing: 2px; color: var(--muted); }
.iconbtn {
  background: none; border: none; color: var(--ink);
  font-size: 20px; cursor: pointer; padding: 0 4px;
}
.rule { border-top: var(--rule-w) solid var(--ink); margin: 10px 16px 0; }

/* ---- stage ---- */
#stage { flex: 1; position: relative; overflow: hidden; }
.ghost {
  position: absolute; top: 8px; left: 4px;
  font-size: min(34vh, 160px); font-weight: 900; line-height: 1;
  color: rgba(255, 255, 255, 0.055);
  pointer-events: none; user-select: none;
}
#card-area {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  padding: 18px;
}
.card {
  width: min(92vw, 420px);
  text-align: center;
  touch-action: none;
  will-change: transform;
}
.card h2 { font-size: clamp(26px, 6vw, 40px); font-weight: 900; line-height: 1.12; }
.media {
  margin: 22px auto 0;
  width: min(64vw, 260px); height: min(42vw, 170px);
  background: var(--surface);
  border: var(--rule-w) solid var(--ink);
  box-shadow: 6px 6px 0 rgba(0, 0, 0, 0.45);
  display: flex; align-items: center; justify-content: center;
  font-size: 64px;
  overflow: hidden;
}
.media img { width: 100%; height: 100%; object-fit: cover; }
.hint { margin-top: 14px; font-size: 11px; letter-spacing: 1px; color: var(--muted); }

/* ---- reveal ---- */
.reveal { margin-top: 18px; }
.bar {
  position: relative; height: 30px;
  border: var(--rule-w) solid var(--ink);
  background: var(--surface);
  overflow: hidden;
}
.bar-left, .bar-right {
  position: absolute; top: 0; bottom: 0; width: 0;
  transition: width 900ms cubic-bezier(0.22, 1, 0.36, 1);
}
.bar-left { left: 0; background: linear-gradient(90deg, var(--left-a), var(--left-b)); }
.bar-right { right: 0; background: linear-gradient(270deg, var(--right-a), var(--right-b)); }
.stats { display: flex; justify-content: space-between; margin-top: 8px; font-size: 13px; font-weight: 700; }
.stats .left-side { color: #E8735A; }
.stats .right-side { color: #6E9FDC; }
.neutral-count { margin-top: 4px; font-size: 11px; color: var(--muted); text-align: center; }
.reveal-actions { display: flex; gap: 10px; margin-top: 16px; }
.reveal-actions .primary {
  flex: 1; background: var(--ink); color: var(--bg);
  border: var(--rule-w) solid var(--ink);
  font-size: 16px; font-weight: 900; padding: 12px; cursor: pointer;
}
.reveal-actions .secondary {
  background: none; color: var(--muted);
  border: var(--rule-w) solid var(--muted);
  font-size: 13px; font-weight: 700; padding: 12px 18px; cursor: pointer;
}

/* ---- vote bar ---- */
#vote-bar { border-top: var(--rule-w) solid var(--ink); display: flex; height: 72px; }
.vote {
  flex: 1; border: none; cursor: pointer;
  color: #fff; font-size: 18px; font-weight: 900; font-family: var(--font);
}
.vote.right { background-image: linear-gradient(135deg, var(--right-a), var(--right-b), var(--right-a)); }
.vote.left {
  background-image: linear-gradient(135deg, var(--left-a), var(--left-b), var(--left-a));
  border-right: var(--rule-w) solid var(--ink);
}
#btn-neutral {
  width: 100%; height: 34px;
  background: var(--bg); color: var(--muted);
  border: none; border-top: var(--rule-w) solid var(--ink);
  font-size: 12px; font-weight: 800; letter-spacing: 1px; font-family: var(--font);
  cursor: pointer;
}

/* ---- FAB, panel, toast ---- */
.fab {
  position: fixed; bottom: 92px; left: 18px; z-index: 30;
  width: 54px; height: 54px; border-radius: 50%;
  border: var(--rule-w) solid var(--ink);
  background: var(--surface); color: var(--ink);
  font-size: 26px; cursor: pointer;
  box-shadow: 4px 4px 0 rgba(0, 0, 0, 0.45);
}
.panel {
  position: fixed; inset: 0; z-index: 40;
  background: var(--bg);
  padding: 16px; overflow-y: auto;
}
.panel .panel-head {
  display: flex; justify-content: space-between; align-items: baseline;
  border-bottom: var(--rule-w) solid var(--ink); padding-bottom: 10px;
}
.panel h2 { font-size: 20px; font-weight: 900; }
.myvote-row { border-bottom: 1px solid var(--surface); padding: 12px 2px; }
.myvote-row .name { font-size: 15px; font-weight: 700; }
.myvote-row .detail { font-size: 12px; color: var(--muted); margin-top: 3px; }
.dialog {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.dialog .box {
  width: min(92vw, 380px);
  background: var(--bg); border: var(--rule-w) solid var(--ink);
  box-shadow: 8px 8px 0 rgba(0, 0, 0, 0.5);
  padding: 18px;
}
.dialog textarea {
  width: 100%; margin-top: 12px; height: 76px; resize: none;
  background: var(--surface); color: var(--ink);
  border: var(--rule-w) solid var(--ink);
  font-family: var(--font); font-size: 15px; padding: 8px;
}
.dialog .actions { display: flex; gap: 10px; margin-top: 12px; }
.toast {
  position: fixed; bottom: 120px; right: 50%; transform: translateX(50%);
  z-index: 60; background: var(--ink); color: var(--bg);
  font-size: 14px; font-weight: 700; padding: 10px 18px;
  box-shadow: 4px 4px 0 rgba(0, 0, 0, 0.45);
}

/* ---- end screen ---- */
.endscreen { text-align: center; padding: 24px; }
.endscreen h2 { font-size: clamp(28px, 7vw, 44px); font-weight: 900; }
.endscreen .summary { margin-top: 14px; font-size: 16px; color: var(--muted); }
.endscreen .actions { display: flex; gap: 10px; justify-content: center; margin-top: 24px; }
.endscreen button {
  background: var(--ink); color: var(--bg); border: var(--rule-w) solid var(--ink);
  font-size: 15px; font-weight: 900; padding: 12px 22px; cursor: pointer; font-family: var(--font);
}

/* ---- desktop: edge vote zones ---- */
@media (min-width: 900px) {
  #vote-bar { display: none; }
  body.has-edges #stage { margin: 0 110px; }
  .edge {
    position: fixed; top: 0; bottom: 34px; width: 110px; z-index: 20;
    border: none; cursor: pointer; color: #fff;
    font-size: 20px; font-weight: 900; font-family: var(--font);
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
  }
  .edge .arrow { font-size: 38px; }
  .edge.right { right: 0; background-image: linear-gradient(180deg, var(--right-a), var(--right-b), var(--right-a)); }
  .edge.left { left: 0; background-image: linear-gradient(180deg, var(--left-a), var(--left-b), var(--left-a)); }
}
@media (max-width: 899px) {
  .edge { display: none; }
}
```

- [ ] **Step 3: Write `site/index.html`**

```html
<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>דברים שהם… בעיניי</title>
  <meta property="og:title" content="דברים שהם… בעיניי">
  <meta property="og:description" content="ימני או שמאלני? הקהל מכריע. בואו להצביע.">
  <meta name="theme-color" content="#23262B">
  <link rel="stylesheet" href="/css/theme.css">
  <link rel="stylesheet" href="/css/app.css">
</head>
<body class="has-edges">
  <header class="topbar">
    <button id="menu-btn" class="iconbtn" aria-label="ההצבעות שלי">☰</button>
    <span class="wordmark">בעיניי<span class="dot">.</span></span>
    <span id="counter" class="counter">–/–</span>
  </header>
  <div class="rule"></div>

  <main id="stage">
    <div id="ghost" class="ghost" aria-hidden="true">01</div>
    <section id="card-area" aria-live="polite"></section>
  </main>

  <button class="edge right drift" id="edge-right" aria-label="ימני">
    <span class="arrow">→</span><span>ימני</span>
  </button>
  <button class="edge left drift" id="edge-left" aria-label="שמאלני">
    <span class="arrow">←</span><span>שמאלני</span>
  </button>

  <div id="vote-bar">
    <button id="btn-right" class="vote right drift">ימני →</button>
    <button id="btn-left" class="vote left drift">← שמאלני</button>
  </div>
  <button id="btn-neutral">ניטרלי ↓</button>

  <button id="fab" class="fab hidden" aria-label="הצעת פריט חדש">＋</button>
  <div id="panel" class="panel hidden"></div>
  <div id="dialog" class="dialog hidden"></div>
  <div id="toast" class="toast hidden" role="status"></div>

  <script type="module" src="/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write `site/js/api.js`**

```javascript
async function req(path, opts = {}) {
  let resp;
  try {
    resp = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  } catch (err) {
    return { status: 0, body: {} };
  }
  const body = await resp.json().catch(() => ({}));
  return { status: resp.status, body };
}

export const getItems = () => req("/api/items");
export const getMe = () => req("/api/me");
export const vote = (item_id, choice) =>
  req("/api/vote", { method: "POST", body: JSON.stringify({ item_id, choice }) });
export const suggest = (text) =>
  req("/api/suggest", { method: "POST", body: JSON.stringify({ text }) });
```

- [ ] **Step 5: Write placeholder `site/js/app.js`** (replaced in Task 2)

```javascript
// Placeholder boot — Task 2 replaces this with the real deck wiring.
const area = document.getElementById("card-area");
area.innerHTML = `
  <article class="card" id="card">
    <h2>חתונת שישי בצהריים<span class="dot">.</span></h2>
    <div class="media">💍</div>
    <div class="hint">→ ימני · ← שמאלני · ↓ ניטרלי</div>
  </article>`;
```

- [ ] **Step 6: Verify with headless Chromium**

Start the local stack (Global Constraints command), then:

```bash
S=/tmp/claude-1000/-home-latnook-Documents-LR2026/7a82793f-40ca-41f0-9458-345ed55ad528/scratchpad
chromium --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=390,844 --virtual-time-budget=4000 --screenshot=$S/t1-mobile.png http://localhost:8080/
chromium --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=1280,800 --virtual-time-budget=4000 --screenshot=$S/t1-desktop.png http://localhost:8080/
```

Read both screenshots. Expected: graphite background; RTL topbar (☰ right… actually ☰ appears at the RIGHT edge, wordmark right-of-center, counter at left edge); ink rule; card with Hebrew title + emoji box with hard shadow; mobile shows bottom vote bar (blue ימני on the right half, red שמאלני on the left half) + ניטרלי strip; desktop shows full-height blue right edge / red left edge zones and NO bottom bar. Kill the server.

- [ ] **Step 7: Commit**

```bash
git add site/ && git commit -m "feat(site): K2 shell, theme tokens, static card, api client"
```

---

### Task 2: Deck engine — load, order, vote, reveal, next/back

**Files:**
- Create: `site/js/deck.js`
- Modify: `site/js/app.js` (replace entirely)

**Interfaces:**
- Consumes: api.js; DOM ids from Task 1.
- Produces (Tasks 3–4 rely on these exact exports from deck.js):
  - `initDeck() -> Promise<void>` — loads items+me, builds queue, renders first card
  - `castVote(choice)` — choice ∈ "left"|"right"|"neutral"; no-op if revealed/none current
  - `next()`, `back()` — advance / view previous answered card (view-only)
  - `isRevealed() -> bool`, `currentItem() -> item|null`
  - `getState() -> {items, votes, queue, history}` (live references)
  - `onDeckEmpty(cb)`, `onVotesChanged(cb)` — subscription hooks (panels.js)
  - Card element gets id `#card`; reveal container class `.reveal`.

- [ ] **Step 1: Write `site/js/deck.js`**

```javascript
import { getItems, getMe, vote } from "./api.js";

const state = {
  items: [],            // all active items (id -> object also in byId)
  byId: new Map(),
  votes: {},            // item_id -> choice (mine, server-truth)
  queue: [],            // unvoted item ids, shuffled
  history: [],          // answered/viewed ids this session (for back)
  current: null,        // item id on screen
  revealed: false,
  viewingBack: false,
};

const emptyCbs = [], votesCbs = [];
export const onDeckEmpty = (cb) => emptyCbs.push(cb);
export const onVotesChanged = (cb) => votesCbs.push(cb);
export const isRevealed = () => state.revealed;
export const currentItem = () => (state.current ? state.byId.get(state.current) : null);
export const getState = () => state;

const area = () => document.getElementById("card-area");
const isLocal = ["localhost", "127.0.0.1"].includes(location.hostname);

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export async function initDeck() {
  const [itemsResp, meResp] = await Promise.all([getItems(), getMe()]);
  state.items = itemsResp.body.items || [];
  state.byId = new Map(state.items.map((i) => [i.id, i]));
  state.votes = meResp.body.votes || {};
  state.queue = shuffle(state.items.filter((i) => !(i.id in state.votes)).map((i) => i.id));
  showNextCard();
  if (isLocal && new URLSearchParams(location.search).get("e2e") === "vote") {
    castVote("right");
  }
}

function updateChrome() {
  const total = state.items.length;
  const done = Object.keys(state.votes).length;
  const pos = Math.min(done + 1, total);
  document.getElementById("counter").textContent =
    `${String(pos).padStart(2, "0")}/${String(total).padStart(2, "0")}`;
  document.getElementById("ghost").textContent = String(pos).padStart(2, "0");
}

function mediaHTML(item) {
  if (item.image_key) {
    return `<img src="/${item.image_key}" alt="${item.name}">`;
  }
  return item.emoji || "🤔";
}

function cardHTML(item) {
  return `
    <article class="card" id="card" data-item="${item.id}">
      <h2>${item.name}<span class="dot">.</span></h2>
      <div class="media">${mediaHTML(item)}</div>
      <div class="hint">→ ימני · ← שמאלני · ↓ ניטרלי</div>
      <div class="reveal hidden"></div>
    </article>`;
}

function showNextCard() {
  state.revealed = false;
  state.viewingBack = false;
  if (state.queue.length === 0) {
    state.current = null;
    emptyCbs.forEach((cb) => cb());
    return;
  }
  state.current = state.queue[0];
  updateChrome();
  area().innerHTML = cardHTML(state.byId.get(state.current));
}

function revealHTML(item, myChoice) {
  const l = item.votes_left, r = item.votes_right, n = item.votes_neutral;
  const total = l + r + n;
  const lr = l + r;
  const pctL = lr ? Math.round((100 * l) / lr) : 50;
  const pctR = lr ? 100 - pctL : 50;
  const mark = (side) => (myChoice === side ? " ✓ הצבעת" : "");
  return `
    <div class="bar"><div class="bar-left"></div><div class="bar-right"></div></div>
    <div class="stats">
      <span class="left-side">שמאלני ${pctL}% · ${l.toLocaleString("he")} קולות${mark("left")}</span>
      <span class="right-side">${mark("right")}ימני ${pctR}% · ${r.toLocaleString("he")} קולות</span>
    </div>
    <div class="neutral-count">🤷 ${n.toLocaleString("he")} ניטרלי${mark("neutral")}</div>
    <div class="reveal-actions">
      <button class="primary" id="btn-next">הבא</button>
      <button class="secondary" id="btn-back">חזרה</button>
    </div>`;
}

function renderReveal(item, myChoice) {
  state.revealed = true;
  const card = document.getElementById("card");
  card.querySelector(".hint").classList.add("hidden");
  const reveal = card.querySelector(".reveal");
  reveal.innerHTML = revealHTML(item, myChoice);
  reveal.classList.remove("hidden");
  const l = item.votes_left, r = item.votes_right;
  const lr = l + r;
  const pctL = lr ? Math.round((100 * l) / lr) : 50;
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      reveal.querySelector(".bar-left").style.width = `${pctL}%`;
      reveal.querySelector(".bar-right").style.width = `${100 - pctL}%`;
    })
  );
  document.getElementById("btn-next").addEventListener("click", next);
  document.getElementById("btn-back").addEventListener("click", back);
}

export async function castVote(choice) {
  if (state.revealed || !state.current) return;
  const id = state.current;
  const { status, body } = await vote(id, choice);
  if (status === 200) {
    state.byId.set(id, { ...state.byId.get(id), ...body.item });
    state.votes[id] = choice;
    state.queue = state.queue.filter((q) => q !== id);
    state.history.push(id);
    votesCbs.forEach((cb) => cb());
    renderReveal(state.byId.get(id), choice);
  } else if (status === 409) {
    state.votes[id] = state.votes[id] || "neutral";
    state.queue = state.queue.filter((q) => q !== id);
    showNextCard();
  } else {
    window.showToast?.("משהו השתבש, נסו שוב");
  }
}

export function next() {
  if (!state.revealed) return;
  showNextCard();
}

export function back() {
  const prevIdx = state.history.indexOf(state.current);
  const target =
    state.current && state.viewingBack && prevIdx > 0
      ? state.history[prevIdx - 1]
      : state.history[state.history.length - 1];
  if (!target || target === state.current) return;
  state.current = target;
  state.viewingBack = true;
  area().innerHTML = cardHTML(state.byId.get(target));
  renderReveal(state.byId.get(target), state.votes[target]);
}
```

- [ ] **Step 2: Replace `site/js/app.js`**

```javascript
import { initDeck, castVote } from "./deck.js";

for (const [id, choice] of [
  ["btn-right", "right"],
  ["btn-left", "left"],
  ["btn-neutral", "neutral"],
  ["edge-right", "right"],
  ["edge-left", "left"],
]) {
  document.getElementById(id).addEventListener("click", () => castVote(choice));
}

initDeck();
```

- [ ] **Step 3: Verify — data flows, reveal renders, voted items skipped**

Start the stack (seeded). Then:

```bash
S=/tmp/claude-1000/-home-latnook-Documents-LR2026/7a82793f-40ca-41f0-9458-345ed55ad528/scratchpad
# 1. First card shows a real seeded item name:
chromium --headless --disable-gpu --no-sandbox --virtual-time-budget=5000 --dump-dom http://localhost:8080/ | grep -o 'data-item="[a-z0-9-]*"' | head -1
# 2. Reveal state (e2e auto-vote) screenshot:
chromium --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=390,844 --virtual-time-budget=6000 --screenshot=$S/t2-reveal.png "http://localhost:8080/?e2e=vote"
# 3. Counter/ghost present:
chromium --headless --disable-gpu --no-sandbox --virtual-time-budget=5000 --dump-dom http://localhost:8080/ | grep -oE 'id="counter"[^<]*' | head -1
```

Read `$S/t2-reveal.png`. Expected: card with hint hidden, two-color bar partially filled (red anchored left, blue anchored right), Hebrew stats with ✓ on ימני side, הבא/חזרה buttons. The dump-dom greps must show a real item id and a NN/24-style counter. Kill the server.

- [ ] **Step 4: Commit**

```bash
git add site/ && git commit -m "feat(site): deck engine — load, shuffle, vote, animated reveal, next/back"
```

---

### Task 3: Gestures — keyboard + swipe with tilt

**Files:**
- Create: `site/js/gestures.js`
- Modify: `site/js/app.js` (add two lines)

**Interfaces:**
- Consumes: deck.js exports (`castVote next back isRevealed`).
- Produces: `initGestures()` — attaches once to `document`/`#card-area` (survives card re-renders via delegation).

- [ ] **Step 1: Write `site/js/gestures.js`**

```javascript
import { castVote, next, back, isRevealed } from "./deck.js";

export function initGestures() {
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea")) return;
    if (!document.getElementById("panel").classList.contains("hidden")) return;
    if (!document.getElementById("dialog").classList.contains("hidden")) return;
    if (isRevealed()) {
      if (["ArrowRight", "ArrowLeft", "ArrowDown", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        next();
      } else if (e.key === "Backspace") {
        e.preventDefault();
        back();
      }
      return;
    }
    if (e.key === "ArrowRight") castVote("right");
    else if (e.key === "ArrowLeft") castVote("left");
    else if (e.key === "ArrowDown") castVote("neutral");
  });

  // Swipe with tilt — pointer events, delegated so re-rendered cards keep working.
  const area = document.getElementById("card-area");
  let drag = null;

  area.addEventListener("pointerdown", (e) => {
    const card = e.target.closest("#card");
    if (!card || isRevealed()) return;
    drag = { card, x0: e.clientX, y0: e.clientY, id: e.pointerId };
    card.setPointerCapture(e.pointerId);
  });

  area.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x0;
    const dy = e.clientY - drag.y0;
    drag.card.style.transform = `translate(${dx}px, ${Math.max(dy, -30)}px) rotate(${dx / 18}deg)`;
  });

  const finish = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x0;
    const dy = e.clientY - drag.y0;
    const card = drag.card;
    drag = null;
    card.style.transform = "";
    if (dx > 80 && Math.abs(dy) < Math.abs(dx)) castVote("right");
    else if (dx < -80 && Math.abs(dy) < Math.abs(dx)) castVote("left");
    else if (dy > 80) castVote("neutral");
  };
  area.addEventListener("pointerup", finish);
  area.addEventListener("pointercancel", finish);
}
```

- [ ] **Step 2: Update `site/js/app.js`** — add after the existing imports/wiring:

```javascript
import { initGestures } from "./gestures.js";
```

and, immediately before `initDeck();`:

```javascript
initGestures();
```

- [ ] **Step 3: Verify**

Static check (no interaction possible headless): serve, then
`chromium --headless --disable-gpu --no-sandbox --virtual-time-budget=5000 --dump-dom http://localhost:8080/ | grep -c 'gestures.js'` → expect `1`, and browser console must stay clean: rerun the dump-dom command with `2>&1 | grep -iE 'error|uncaught'` → expect no output. Interactive swipe/keyboard behavior is covered in Task 6's human checklist. Kill the server.

- [ ] **Step 4: Commit**

```bash
git add site/ && git commit -m "feat(site): keyboard and swipe-with-tilt gestures"
```

---

### Task 4: Panels — my-votes, suggest, end screen, toast

**Files:**
- Create: `site/js/panels.js`
- Modify: `site/js/app.js` (add import + init)

**Interfaces:**
- Consumes: deck.js (`getState onDeckEmpty onVotesChanged`), api.js (`suggest`).
- Produces: `initPanels()`; global `window.showToast(msg)` (deck.js already calls it on vote failure).

- [ ] **Step 1: Write `site/js/panels.js`**

```javascript
import { getState, onDeckEmpty, onVotesChanged } from "./deck.js";
import { suggest } from "./api.js";

const $ = (id) => document.getElementById(id);

export function initPanels() {
  window.showToast = showToast;
  $("menu-btn").addEventListener("click", openMyVotes);
  $("fab").addEventListener("click", openSuggest);
  onVotesChanged(updateFab);
  onDeckEmpty(showEndScreen);
  updateFab();
}

function showToast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 2600);
}

function updateFab() {
  const votes = Object.keys(getState().votes).length;
  $("fab").classList.toggle("hidden", votes < 5);
}

/* ---- my votes ---- */
function crowdLine(item, mine) {
  const counts = { left: item.votes_left, right: item.votes_right, neutral: item.votes_neutral };
  const total = counts.left + counts.right + counts.neutral;
  if (!total) return "";
  const pctSame = Math.round((100 * counts[mine]) / total);
  const names = { left: "שמאלני", right: "ימני", neutral: "🤷 ניטרלי" };
  return `הצבעת: ${names[mine]} · הקהל איתך: ${pctSame}%`;
}

function openMyVotes() {
  const { items, votes } = getState();
  const rows = items
    .filter((i) => i.id in votes)
    .map(
      (i) => `<div class="myvote-row">
        <div class="name">${i.emoji || ""} ${i.name}</div>
        <div class="detail">${crowdLine(i, votes[i.id])}</div>
      </div>`
    )
    .join("");
  const panel = $("panel");
  panel.innerHTML = `
    <div class="panel-head">
      <h2>ההצבעות שלי</h2>
      <button class="iconbtn" id="panel-close" aria-label="סגירה">✕</button>
    </div>
    ${rows || '<p style="margin-top:16px; color:var(--muted)">עוד לא הצבעת על כלום.</p>'}`;
  panel.classList.remove("hidden");
  $("panel-close").addEventListener("click", () => panel.classList.add("hidden"));
}

/* ---- suggest ---- */
function openSuggest() {
  const d = $("dialog");
  d.innerHTML = `
    <div class="box">
      <h2>מה עוד שכחנו?</h2>
      <textarea id="suggest-text" maxlength="120" placeholder="לדוגמה: פיצה עם תירס"></textarea>
      <div class="actions">
        <button class="primary" id="suggest-send" style="flex:1; background:var(--ink); color:var(--bg); border:2px solid var(--ink); font-weight:900; padding:10px; cursor:pointer;">שליחה</button>
        <button class="secondary" id="suggest-cancel" style="background:none; color:var(--muted); border:2px solid var(--muted); padding:10px 16px; cursor:pointer;">ביטול</button>
      </div>
    </div>`;
  d.classList.remove("hidden");
  $("suggest-cancel").addEventListener("click", () => d.classList.add("hidden"));
  $("suggest-send").addEventListener("click", async () => {
    const text = $("suggest-text").value.trim();
    if (!text) return;
    const { status } = await suggest(text);
    d.classList.add("hidden");
    if (status === 202) showToast("תודה! ההצעה תיבדק");
    else if (status === 429) showToast("הגעתם למכסה היומית, נסו מחר");
    else showToast("משהו השתבש, נסו שוב");
  });
}

/* ---- end screen ---- */
function agreementPct() {
  const { items, votes } = getState();
  const voted = items.filter((i) => i.id in votes);
  if (!voted.length) return 0;
  const agreed = voted.filter((i) => {
    const counts = { left: i.votes_left, right: i.votes_right, neutral: i.votes_neutral };
    const majority = Object.keys(counts).reduce((a, b) => (counts[a] >= counts[b] ? a : b));
    return votes[i.id] === majority;
  }).length;
  return Math.round((100 * agreed) / voted.length);
}

function showEndScreen() {
  $("card-area").innerHTML = `
    <div class="endscreen">
      <h2>זהו, עברת על הכל<span class="dot">!</span></h2>
      <p class="summary">הסכמת עם הרוב ב־${agreementPct()}% מהפריטים</p>
      <div class="actions">
        <button id="share-btn">שיתוף</button>
        <button id="end-suggest">להציע פריט</button>
      </div>
    </div>`;
  $("share-btn").addEventListener("click", async () => {
    const data = { title: document.title, url: location.origin };
    if (navigator.share) {
      await navigator.share(data).catch(() => {});
    } else {
      await navigator.clipboard.writeText(data.url).catch(() => {});
      showToast("הקישור הועתק");
    }
  });
  $("end-suggest").addEventListener("click", openSuggest);
}
```

- [ ] **Step 2: Update `site/js/app.js`** — add import + init call (before `initDeck();`):

```javascript
import { initPanels } from "./panels.js";
```

```javascript
initPanels();
```

- [ ] **Step 3: Verify**

Serve seeded; console-clean check as in Task 3. Screenshot the my-votes panel and end screen using localhost-gated e2e helpers — add this temporary block? NO — instead verify statically: `--dump-dom` must contain `id="panel"`, `id="fab"`, and grep for `panels.js`. Interactive panel/suggest/end flows go on Task 6's human checklist. Kill the server.

- [ ] **Step 4: Commit**

```bash
git add site/ && git commit -m "feat(site): my-votes panel, suggest flow, end screen, toast"
```

---

### Task 5: Admin page

**Files:**
- Create: `site/admin/index.html`, `site/admin/admin.css`, `site/admin/admin.js`

**Interfaces:**
- Consumes: backend admin API (Plan 1). Auth seam: on load, `fetch("/admin/config.json")` — 404/failure ⇒ **local mode** (no Authorization header; backend's ALLOW_ADMIN=1 authorizes). Plan 3 will deploy a real `config.json` + Cognito SDK wiring into the login section marked `<!-- COGNITO-LOGIN-SLOT -->`.
- Produces: working local admin at `/admin/`.

- [ ] **Step 1: Write `site/admin/index.html`**

```html
<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>בעיניי · ניהול</title>
  <meta name="robots" content="noindex">
  <link rel="stylesheet" href="/css/theme.css">
  <link rel="stylesheet" href="/admin/admin.css">
</head>
<body>
  <header class="topbar">
    <span class="wordmark">בעיניי<span class="dot">.</span> ניהול</span>
    <span id="mode-badge" class="badge"></span>
  </header>
  <div class="rule"></div>

  <!-- COGNITO-LOGIN-SLOT: Plan 3 renders the Cognito login form here when config.json exists -->
  <section id="login" class="hidden">
    <p>נדרשת התחברות — יוגדר בפריסה (Cognito).</p>
  </section>

  <main id="admin-main" class="hidden">
    <section>
      <h2>הצעות ממתינות</h2>
      <div id="queue"></div>
    </section>
    <section>
      <h2>פריט חדש</h2>
      <form id="create-form">
        <input id="c-id" placeholder="item-id (a-z, 0-9, -)" pattern="[a-z0-9-]{1,64}" required>
        <input id="c-name" placeholder="שם בעברית" required>
        <input id="c-emoji" placeholder="אימוג׳י" size="4">
        <label><input type="checkbox" id="c-image"> עם תמונה</label>
        <input type="file" id="c-file" accept="image/*" class="hidden">
        <button type="submit">יצירה</button>
      </form>
    </section>
    <section>
      <h2>פריטים</h2>
      <div id="items"></div>
    </section>
  </main>

  <div id="toast" class="toast hidden" role="status"></div>
  <script type="module" src="/admin/admin.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `site/admin/admin.css`**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font-family: var(--font); padding-bottom: 40px; }
.hidden { display: none !important; }
.topbar { display: flex; justify-content: space-between; align-items: baseline; padding: 14px 16px 0; }
.wordmark { font-size: 16px; font-weight: 900; }
.dot { background: linear-gradient(90deg, var(--left-a), var(--left-b)); -webkit-background-clip: text; background-clip: text; color: transparent; }
.badge { font-size: 11px; font-weight: 700; color: var(--muted); letter-spacing: 1px; }
.rule { border-top: 2px solid var(--ink); margin: 10px 16px 0; }
main { max-width: 720px; margin: 0 auto; padding: 0 16px; }
section { margin-top: 26px; }
h2 { font-size: 17px; font-weight: 900; border-bottom: 2px solid var(--ink); padding-bottom: 6px; }
.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; border-bottom: 1px solid var(--surface); padding: 10px 2px; }
.row .grow { flex: 1; min-width: 180px; }
.muted { color: var(--muted); font-size: 12px; }
input, button, label { font-family: var(--font); font-size: 14px; }
input { background: var(--surface); color: var(--ink); border: 2px solid var(--ink); padding: 7px 9px; }
input:invalid { border-color: var(--left-a); }
button { background: var(--ink); color: var(--bg); border: 2px solid var(--ink); font-weight: 900; padding: 7px 14px; cursor: pointer; }
button.ghost { background: none; color: var(--muted); border-color: var(--muted); }
form { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; align-items: center; }
.toast { position: fixed; bottom: 30px; right: 50%; transform: translateX(50%); background: var(--ink); color: var(--bg); font-weight: 700; padding: 10px 18px; box-shadow: 4px 4px 0 rgba(0,0,0,.45); }
```

- [ ] **Step 3: Write `site/admin/admin.js`**

```javascript
let authHeader = null; // Plan 3 sets this from Cognito; local mode leaves it null.

async function api(path, opts = {}) {
  const headers = { "content-type": "application/json" };
  if (authHeader) headers.authorization = authHeader;
  let resp;
  try {
    resp = await fetch(path, { headers, ...opts });
  } catch {
    return { status: 0, body: {} };
  }
  const body = await resp.json().catch(() => ({}));
  return { status: resp.status, body };
}

const $ = (id) => document.getElementById(id);
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 2600);
}

const slugify = (text) =>
  text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64) ||
  `item-${Date.now() % 100000}`;

/* ---- queue ---- */
async function loadQueue() {
  const { status, body } = await api("/api/admin/suggestions");
  if (status !== 200) return toast(`שגיאה בטעינת התור (${status})`);
  $("queue").innerHTML =
    (body.suggestions || [])
      .map(
        (s) => `<div class="row" data-sid="${s.sid}">
          <span class="grow">${s.text}</span>
          <input class="ap-id" placeholder="${slugify(s.text)}" size="14">
          <input class="ap-emoji" placeholder="אימוג׳י" size="4">
          <button class="approve">אישור</button>
          <button class="ghost reject">דחייה</button>
        </div>`
      )
      .join("") || '<p class="muted" style="margin-top:10px">אין הצעות ממתינות.</p>';

  for (const row of $("queue").querySelectorAll(".row")) {
    const sid = row.dataset.sid;
    const text = row.querySelector(".grow").textContent;
    row.querySelector(".approve").addEventListener("click", async () => {
      const item_id = row.querySelector(".ap-id").value.trim() || slugify(text);
      const emoji = row.querySelector(".ap-emoji").value.trim();
      const { status } = await api(`/api/admin/suggestions/${sid}/approve`, {
        method: "POST",
        body: JSON.stringify({ item_id, name: text, emoji }),
      });
      if (status === 200) { toast("אושר ✓"); refresh(); }
      else if (status === 409) toast("item-id כבר קיים");
      else toast(`שגיאה (${status})`);
    });
    row.querySelector(".reject").addEventListener("click", async () => {
      const { status } = await api(`/api/admin/suggestions/${sid}/reject`, { method: "POST" });
      if (status === 200) { toast("נדחה"); refresh(); }
      else toast(`שגיאה (${status})`);
    });
  }
}

/* ---- items ---- */
async function loadItems() {
  const { status, body } = await api("/api/items");
  if (status !== 200) return;
  $("items").innerHTML = (body.items || [])
    .map(
      (i) => `<div class="row" data-id="${i.id}">
        <span class="grow">${i.emoji || ""} ${i.name}
          <span class="muted">(${i.id} · ${i.votes_left}/${i.votes_right}/${i.votes_neutral})</span>
        </span>
        <button class="ghost archive">ארכוב</button>
      </div>`
    )
    .join("");
  for (const row of $("items").querySelectorAll(".row")) {
    row.querySelector(".archive").addEventListener("click", async () => {
      const { status } = await api(`/api/admin/items/${row.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "archived" }),
      });
      if (status === 200) { toast("נשלח לארכיון"); refresh(); }
      else toast(`שגיאה (${status})`);
    });
  }
}

/* ---- create (with optional browser-side webp resize + presigned upload) ---- */
async function fileToWebp(file, maxDim = 1200) {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, maxDim / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bmp.width * scale);
  canvas.height = Math.round(bmp.height * scale);
  canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
  return new Promise((res) => canvas.toBlob(res, "image/webp", 0.85));
}

function initCreateForm() {
  $("c-image").addEventListener("change", () =>
    $("c-file").classList.toggle("hidden", !$("c-image").checked)
  );
  $("c-name").addEventListener("input", () => {
    if (!$("c-id").value) $("c-id").placeholder = slugify($("c-name").value) || "item-id";
  });
  $("create-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const item_id = $("c-id").value.trim() || slugify($("c-name").value);
    const want_image = $("c-image").checked;
    const { status, body } = await api("/api/admin/items", {
      method: "POST",
      body: JSON.stringify({
        item_id,
        name: $("c-name").value.trim(),
        emoji: $("c-emoji").value.trim(),
        want_image,
      }),
    });
    if (status === 409) return toast("item-id כבר קיים");
    if (status !== 200) return toast(`שגיאה (${status})`);
    if (want_image && body.upload_url && $("c-file").files[0]) {
      const blob = await fileToWebp($("c-file").files[0]);
      const up = await fetch(body.upload_url, {
        method: "PUT",
        headers: { "content-type": "image/webp" },
        body: blob,
      });
      toast(up.ok ? "נוצר + תמונה הועלתה ✓" : "נוצר, אך העלאת התמונה נכשלה");
    } else {
      toast(want_image && !body.upload_url ? "נוצר (אין דלי תמונות מקומי)" : "נוצר ✓");
    }
    $("create-form").reset();
    $("c-file").classList.add("hidden");
    refresh();
  });
}

function refresh() { loadQueue(); loadItems(); }

/* ---- boot: auth seam ---- */
(async () => {
  const cfg = await fetch("/admin/config.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (cfg) {
    // Plan 3: Cognito SRP login renders here; sets authHeader = `Bearer ${idToken}` then boots.
    $("mode-badge").textContent = "CLOUD";
    $("login").classList.remove("hidden");
    return;
  }
  $("mode-badge").textContent = "LOCAL";
  $("admin-main").classList.remove("hidden");
  initCreateForm();
  refresh();
})();
```

- [ ] **Step 4: Verify**

Serve seeded. Push a suggestion through the public API, then screenshot:

```bash
S=/tmp/claude-1000/-home-latnook-Documents-LR2026/7a82793f-40ca-41f0-9458-345ed55ad528/scratchpad
curl -s -X POST localhost:8080/api/suggest -d '{"text":"בדיקת ממשק ניהול"}' >/dev/null
chromium --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=900,900 --virtual-time-budget=6000 --screenshot=$S/t5-admin.png http://localhost:8080/admin/
```

Read the screenshot: LOCAL badge, the pending suggestion "בדיקת ממשק ניהול" with אישור/דחייה, the create form, and the items list with vote tallies. Then verify approve works end-to-end via API: `curl -s localhost:8080/api/admin/suggestions` shows the sid; nothing further (UI click flows are Task 6 human checklist). Kill the server.

- [ ] **Step 5: Commit**

```bash
git add site/ && git commit -m "feat(site): admin page — queue, item CRUD, image upload, auth seam"
```

---

### Task 6: Polish + full verification suite

**Files:**
- Create: `site/favicon.svg`
- Modify: `site/index.html` (favicon link), `README.md` (create — quick local-run notes)

**Interfaces:** none new — this task verifies and documents.

- [ ] **Step 1: Write `site/favicon.svg`**

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" fill="#23262B"/>
  <rect x="6" y="30" width="24" height="26" fill="#B91C1C"/>
  <rect x="34" y="18" width="24" height="38" fill="#3730A3"/>
  <rect x="6" y="10" width="52" height="4" fill="#F2F3F5"/>
</svg>
```

Add to `site/index.html` `<head>` (and `site/admin/index.html`): `<link rel="icon" type="image/svg+xml" href="/favicon.svg">`

- [ ] **Step 2: Create `README.md`** (repo root)

```markdown
# LR — דברים שהם… בעיניי

Hebrew voting site: is it ימני or שמאלני? The crowd decides.
Serverless AWS app (Plan 3) with a no-build vanilla-JS frontend and a
Python Lambda backend — all runnable locally.

## Run locally

    ./scripts/local-dev.sh --votes 50     # DynamoDB Local + seed + http://localhost:8080

Site: http://localhost:8080 · Admin: http://localhost:8080/admin/ (auto-authorized locally)

## Tests

    docker compose up -d dynamodb
    cd backend && ../.venv/bin/pytest -q

Docs: `docs/superpowers/specs/` (design), `docs/superpowers/plans/` (build plans).
```

- [ ] **Step 3: Full screenshot suite**

Serve seeded, then capture: mobile card, mobile reveal (`?e2e=vote`), desktop card, desktop reveal, admin — five screenshots to the scratchpad, all read and sanity-checked (RTL layout, colors, no overlapping text, bar direction: red-left/blue-right).

- [ ] **Step 4: Console hygiene**

`--dump-dom` runs for `/` and `/admin/` with `2>&1 | grep -iE "error|uncaught|failed"` → no output.

- [ ] **Step 5: Human checklist (hand to the controller/user — do not self-certify)**

Report these as OPEN items for the human pass: swipe tilt + release-snap on touch; arrow keys vote and advance; Backspace goes back; reveal bar animates; הבא/חזרה; ☰ my-votes; ➕ after 5 votes; suggest → admin queue → approve → item appears for new visitor; end screen + share; admin archive.

- [ ] **Step 6: Commit**

```bash
git add site/ README.md && git commit -m "feat(site): favicon, README, verification suite"
```

---

## Self-review notes

- Spec §2 coverage: card/vote inputs (T1-T3), reveal + no-timer + back view-only (T2), client-side shuffle unvoted-first (T2), counter + ghost (T2), FAB after 5 (T4), my-votes (T4), end screen + share (T4), suggest flow (T4). §3: all tokens in theme.css (T1), edge zones desktop (T1), drift + reduced-motion (T1), centered media block + offset shadow (T1). §6: static, no build, RTL, OG tags (T1), admin same site (T5).
- Deliberate scope choices: vote-bar buttons + edge zones both call the same castVote; 409 on vote (stale tab) silently advances; `viewingBack` allows stepping further back through history; images use `/img/...` keys as served by CloudFront later and by nothing locally (emoji fallback covers local).
- Type consistency check: deck exports match gestures/panels imports; api.js return shape `{status, body}` used consistently; element ids in JS all exist in index.html.
