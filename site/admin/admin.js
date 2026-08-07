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

/* ---- queue ---- */
async function loadQueue() {
  const { status, body } = await api("/api/admin/suggestions");
  if (status !== 200) return toast(`שגיאה בטעינת התור (${status})`);
  $("queue").innerHTML =
    (body.suggestions || [])
      .map(
        (s) => `<div class="row" data-sid="${s.sid}">
          <span class="grow">${esc(s.text)}</span>
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
  if (status !== 200) return toast(`שגיאה בטעינת הפריטים (${status})`);
  $("items").innerHTML = (body.items || [])
    .map(
      (i) => `<div class="row" data-id="${i.id}">
        <span class="grow">${esc(i.emoji || "")} ${esc(i.name)}
          <span class="muted">(${esc(i.id)} · ${i.votes_left}/${i.votes_right}/${i.votes_neutral})</span>
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
  initCreateForm();
  refresh();
})();
