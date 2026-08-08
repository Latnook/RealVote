import {
  getState,
  onDeckEmpty,
  onVotesChanged,
  getAllCategories,
  getCategories,
  setCategories,
} from "./deck.js";
import { suggest } from "./api.js";

const $ = (id) => document.getElementById(id);

const esc = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

export function initPanels() {
  window.showToast = showToast;
  $("menu-btn").addEventListener("click", openMyVotes);
  $("fab").addEventListener("click", openSuggest);
  onVotesChanged(updateFab);
  onDeckEmpty(showEndScreen);
  updateFab();
  if (
    ["localhost", "127.0.0.1"].includes(location.hostname) &&
    new URLSearchParams(location.search).get("e2e") === "panel"
  ) {
    // wait for initDeck's data load (items/categories arrive via onVotesChanged)
    // before rendering, rather than opening an empty panel synchronously here.
    onVotesChanged(openMyVotes);
  }
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

/* ---- overlay a11y helper (dialog role, focus trap entry, Escape-to-close) ---- */
function openOverlay(el, focusEl, onClose) {
  const opener = document.activeElement;
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  el.classList.remove("hidden");
  focusEl?.focus();
  const onKeydown = (e) => {
    if (e.key === "Escape") close();
  };
  document.addEventListener("keydown", onKeydown);
  function close() {
    document.removeEventListener("keydown", onKeydown);
    el.classList.add("hidden");
    onClose?.();
    if (opener instanceof HTMLElement) opener.focus();
  }
  return close;
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
  const rows = items
    .filter((i) => i.id in votes)
    .map(
      (i) => `<div class="myvote-row">
        <div class="name">${esc(i.emoji || "")} ${esc(i.name)}</div>
        <div class="detail">${crowdLine(i, votes[i.id])}</div>
      </div>`
    )
    .join("");
  const panel = $("panel");
  panel.innerHTML = `
    <div class="panel-head">
      <h2>תפריט</h2>
      <button class="iconbtn" id="panel-close" aria-label="סגירה">✕</button>
    </div>
    <section class="cat-section">
      <h3>קטגוריות</h3>
      <div class="cat-list">${catRows}</div>
    </section>
    <h3 class="myvotes-head">ההצבעות שלי</h3>
    ${rows || '<p style="margin-top:16px; color:var(--muted)">עוד לא הצבעת על כלום.</p>'}`;
  const applyCategories = () => {
    const boxes = [...panel.querySelectorAll(".cat-box")];
    if (boxes.length === 0) return; // panel opened before categories loaded — nothing to apply
    const chosen = boxes.filter((b) => b.checked).map((b) => b.value);
    const current = getCategories();
    const same = chosen.length === current.length && chosen.every((s) => current.includes(s));
    if (same) return;
    setCategories(chosen);
  };
  const close = openOverlay(panel, $("panel-close"), applyCategories);
  $("panel-close").addEventListener("click", close);
}

/* ---- suggest ---- */
function openSuggest() {
  const d = $("dialog");
  d.innerHTML = `
    <div class="box">
      <h2>מה עוד שכחנו?</h2>
      <textarea id="suggest-text" maxlength="120" placeholder="לדוגמה: פיצה עם תירס"></textarea>
      <div class="actions">
        <button class="primary" id="suggest-send">שליחה</button>
        <button class="secondary" id="suggest-cancel">ביטול</button>
      </div>
    </div>`;
  const close = openOverlay(d, $("suggest-text"));
  $("suggest-cancel").addEventListener("click", close);
  $("suggest-send").addEventListener("click", async (e) => {
    const text = $("suggest-text").value.trim();
    if (!text) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    const { status } = await suggest(text);
    close();
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
    const max = Math.max(counts.left, counts.right, counts.neutral);
    return counts[votes[i.id]] === max;
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
