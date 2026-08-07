import { getState, onDeckEmpty, onVotesChanged } from "./deck.js";
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
        <div class="name">${esc(i.emoji || "")} ${esc(i.name)}</div>
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
        <button class="primary" id="suggest-send">שליחה</button>
        <button class="secondary" id="suggest-cancel">ביטול</button>
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
