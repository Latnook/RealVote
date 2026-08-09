const esc = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

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

/* ---- categories ---- */
let CATEGORIES = [];
const DEFAULT_CAT = "other";

async function loadCategories() {
  const { status, body } = await api("/api/items");
  if (status === 200) CATEGORIES = body.categories || [];
  const opts = CATEGORIES.map(
    (c) => `<option value="${esc(c.slug)}">${esc(c.label)}</option>`
  ).join("");
  $("c-cat").innerHTML = opts;
  $("c-cat").value = DEFAULT_CAT;
}

const catSelect = (selected, cls) =>
  `<select class="${cls}" aria-label="קטגוריה">${CATEGORIES.map(
    (c) =>
      `<option value="${esc(c.slug)}"${c.slug === selected ? " selected" : ""}>${esc(
        c.label
      )}</option>`
  ).join("")}</select>`;

/* ---- queue ---- */
async function loadQueue() {
  const { status, body } = await api("/api/admin/suggestions");
  if (status !== 200) return toast(`שגיאה בטעינת התור (${status})`);
  $("queue").innerHTML =
    (body.suggestions || [])
      .map(
        (s) => `<div class="row" data-sid="${esc(s.sid)}">
          <span class="grow">${esc(s.text)}</span>
          <input class="ap-id" placeholder="${slugify(s.text)}" size="14">
          <input class="ap-emoji" placeholder="אימוג׳י" size="4">
          ${catSelect(DEFAULT_CAT, "ap-cat")}
          <button class="approve">אישור</button>
          <button class="ghost reject">דחייה</button>
        </div>`
      )
      .join("") || '<p class="muted" style="margin-top:10px">אין הצעות ממתינות.</p>';

  const pending = (body.suggestions || []).length;
  $("tab-count").textContent = pending ? `(${pending})` : "";

  for (const row of $("queue").querySelectorAll(".row")) {
    const sid = row.dataset.sid;
    const text = row.querySelector(".grow").textContent;
    row.querySelector(".approve").addEventListener("click", async () => {
      const item_id = row.querySelector(".ap-id").value.trim() || slugify(text);
      const emoji = row.querySelector(".ap-emoji").value.trim();
      const category = row.querySelector(".ap-cat").value;
      const { status } = await api(`/api/admin/suggestions/${encodeURIComponent(sid)}/approve`, {
        method: "POST",
        body: JSON.stringify({ item_id, name: text, emoji, category }),
      });
      if (status === 200) { toast("אושר ✓"); refresh(); }
      else if (status === 409) toast("item-id כבר קיים");
      else toast(`שגיאה (${status})`);
    });
    row.querySelector(".reject").addEventListener("click", async () => {
      const { status } = await api(`/api/admin/suggestions/${encodeURIComponent(sid)}/reject`, { method: "POST" });
      if (status === 200) { toast("נדחה"); refresh(); }
      else toast(`שגיאה (${status})`);
    });
  }
}

/* ---- items ---- */
async function loadItems() {
  if (CATEGORIES.length === 0) {
    await loadCategories();
    if (CATEGORIES.length === 0) {
      toast("שגיאה בטעינת הקטגוריות");
      return;
    }
  }
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
    <input type="file" class="ed-file" accept="image/*" aria-label="תמונה">
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
        category: $("c-cat").value,
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
    } else if (want_image && !body.upload_url) {
      toast("נוצר (אין דלי תמונות מקומי)");
    } else if (want_image) {
      toast("נוצר — עדיין ללא תמונה");
    } else {
      toast("נוצר ✓");
    }
    $("create-form").reset();
    $("c-file").classList.add("hidden");
    $("c-id").focus();
    refresh();
  });
}

function refresh() { loadQueue(); loadItems(); }

/* ---- votes ---- */
let VOTES = null;
const VOTES_OPEN = new Set();
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

  renderVotesList();
}

const emptyVotes = () =>
  '<p class="muted" style="margin-top:10px">עדיין אין הצבעות.</p>';

let VOTES_VIEW = "voters";

function renderVotesList() {
  if (!VOTES) return;
  if (VOTES_VIEW === "items") renderItemsCross();
  else renderVoters();
}

function renderItemsCross() {
  const total = (i) => i.votes_left + i.votes_right + i.votes_neutral;
  const items = [...ITEMS_BY_ID.values()]
    .filter((i) => total(i) > 0)
    .sort((a, b) => total(b) - total(a));

  if (!items.length) {
    $("votes-list").innerHTML = emptyVotes();
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

const csvCell = (s) => {
  const v = String(s);
  // Item names come from public suggestion text (admin.js:89), so a cell can start
  // with a formula character. A leading apostrophe makes spreadsheets treat it as text.
  const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
  return `"${safe.replace(/"/g, '""')}"`;
};

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

function renderVoters() {
  const voters = VOTES.voters || [];
  if (!voters.length) {
    $("votes-list").innerHTML = emptyVotes();
    return;
  }
  $("votes-list").innerHTML = voters.map((v) => {
    const last = v.ballots[0]?.ts || 0;
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
}

function ballotRowHTML(b) {
  const item = ITEMS_BY_ID.get(b.item_id);
  return `<div class="ballot">
    <span class="grow">${esc(item ? item.name : b.item_id)}</span>
    <span class="choice ${esc(b.choice)}">${esc(CHOICE_HE[b.choice] || b.choice)}</span>
    <span class="muted">${esc(relTime(b.ts))}</span>
  </div>`;
}

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
  if (name === "votes" && !VOTES) loadVotes();
  votesAutoRefresh(name === "votes");
}

function initTabs() {
  initVotesSeg();
  initVotesCsv();
  for (const btn of $("tabs").querySelectorAll(".tab")) {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  }
  let saved = null;
  try { saved = localStorage.getItem(TAB_KEY); } catch { /* ignore */ }
  showTab(saved || "queue");
}

/* ---- Cognito sign-in (CLOUD mode) ----
   USER_PASSWORD_AUTH is not enabled on the pool, so we use the InitiateAuth REST API
   with SRP... which needs a crypto library. Instead the pool allows ALLOW_USER_SRP_AUTH
   only, so the browser must perform SRP. Rather than ship a library, this uses the
   AdminNoSrp-free path: Cognito's `USER_SRP_AUTH` via the hosted SDK is heavy, so we
   call InitiateAuth with AuthFlow=USER_SRP_AUTH through amazon-cognito-identity-js,
   loaded from our own origin (vendored, no CDN). The published bundle is UMD, not an
   ES module, so it's loaded via a classic <script> tag in index.html and its exports
   are read off the window.AmazonCognitoIdentity global set by that script. */
function initCloud(cfg) {
  $("mode-badge").textContent = "CLOUD";
  $("login").classList.remove("hidden");

  const { CognitoUserPool, CognitoUser, AuthenticationDetails } = window.AmazonCognitoIdentity;
  const pool = new CognitoUserPool({
    UserPoolId: cfg.userPoolId,
    ClientId: cfg.userPoolClientId,
  });

  let pendingUser = null;

  $("login-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const email = $("l-email").value.trim();
    const user = new CognitoUser({ Username: email, Pool: pool });
    const creds = new AuthenticationDetails({ Username: email, Password: $("l-pass").value });
    user.authenticateUser(creds, {
      onSuccess: (session) => enterAdmin(session.getIdToken().getJwtToken()),
      onFailure: (err) => toast(err.message || "התחברות נכשלה"),
      newPasswordRequired: () => {
        pendingUser = user;
        $("login-form").classList.add("hidden");
        $("newpass-form").classList.remove("hidden");
      },
    });
  });

  $("newpass-form").addEventListener("submit", (e) => {
    e.preventDefault();
    pendingUser.completeNewPasswordChallenge($("l-newpass").value, {}, {
      onSuccess: (session) => enterAdmin(session.getIdToken().getJwtToken()),
      onFailure: (err) => toast(err.message || "עדכון הסיסמה נכשל"),
    });
  });
}

function enterAdmin(idToken) {
  authHeader = `Bearer ${idToken}`;
  $("login").classList.add("hidden");
  $("admin-main").classList.remove("hidden");
  initCreateForm();
  initTabs();
  loadCategories().then(refresh);
}

/* ---- boot: auth seam ---- */
(async () => {
  // Wired once, unconditionally: #show-archived exists in the DOM regardless of
  // mode, so both LOCAL and CLOUD boot paths need this listener.
  $("show-archived").addEventListener("change", loadItems);

  const cfg = await fetch("/admin/config.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (cfg) {
    initCloud(cfg);
    return;
  }
  $("mode-badge").textContent = "LOCAL";
  $("admin-main").classList.remove("hidden");
  initCreateForm();
  initTabs();
  await loadCategories();
  refresh();
})();
