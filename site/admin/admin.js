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
  `<select class="${cls}">${CATEGORIES.map(
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
  $("show-archived").addEventListener("change", loadItems);
  initCreateForm();
  await loadCategories();
  refresh();
})();
