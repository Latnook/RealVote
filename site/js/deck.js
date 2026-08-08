import { getItems, getMe, vote } from "./api.js";
import { crossAttributionLines } from "./crosstab.js";
import * as affq from "./affiliation.js";

const esc = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const state = {
  items: [],            // all active items (id -> object also in byId)
  byId: new Map(),
  votes: {},            // item_id -> choice (mine, server-truth)
  queue: [],            // unvoted item ids, shuffled
  history: [],          // answered/viewed ids this session (for back)
  current: null,        // item id on screen
  revealed: false,
  viewingBack: false,
  affiliation: null,     // "right" | "left" | "center" | null
  allCategories: [],     // [{slug,label}] from the API
  selected: null,        // Set of selected slugs; null means "all"
};

const emptyCbs = [], votesCbs = [];
let submitting = false;
export const onDeckEmpty = (cb) => emptyCbs.push(cb);
export const onVotesChanged = (cb) => votesCbs.push(cb);
export const isRevealed = () => state.revealed || affq.isRevealed();
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

const CATS_KEY = "lr_cats";

function loadSelected() {
  try {
    const raw = localStorage.getItem(CATS_KEY);
    return raw ? new Set(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

export const getAllCategories = () => state.allCategories;
export const getCategories = () =>
  state.selected ? [...state.selected] : state.allCategories.map((c) => c.slug);

export function setCategories(slugs) {
  state.selected = new Set(slugs);
  try {
    localStorage.setItem(CATS_KEY, JSON.stringify([...state.selected]));
  } catch {
    /* private mode: filter still applies for this session */
  }
  rebuildQueue();
  showNextCard();
}

function inSelection(item) {
  return !state.selected || state.selected.has(item.category);
}

function rebuildQueue() {
  state.queue = shuffle(
    state.items.filter((i) => inSelection(i) && !(i.id in state.votes)).map((i) => i.id)
  );
}

function renderLoadError() {
  state.current = null;
  area().innerHTML = `
    <div class="endscreen">
      <h2>לא הצלחנו לטעון<span class="dot">.</span></h2>
      <p class="summary">בדקו את החיבור לאינטרנט ונסו שוב</p>
      <div class="actions"><button id="retry-btn">נסו שוב</button></div>
    </div>`;
  document.getElementById("retry-btn").addEventListener("click", () => {
    area().innerHTML = "";
    initDeck();
  });
}

export async function initDeck() {
  const [itemsResp, meResp] = await Promise.all([getItems(), getMe()]);
  if (itemsResp.status !== 200) {
    renderLoadError();
    return;
  }
  state.items = itemsResp.body.items || [];
  state.byId = new Map(state.items.map((i) => [i.id, i]));
  state.votes = meResp.body.votes || {};
  state.allCategories = itemsResp.body.categories || [];
  state.affiliation = meResp.body.affiliation || null;
  state.selected = loadSelected();
  rebuildQueue();
  if (isLocal && new URLSearchParams(location.search).get("e2e") === "affq") {
    try { localStorage.setItem("lr_affq_at", "0"); } catch { /* ignore */ }
    state.affiliation = null;
  }
  votesCbs.forEach((cb) => cb());
  showNextCard();
  if (isLocal && new URLSearchParams(location.search).get("e2e") === "vote") {
    castVote("right");
  }
}

function updateChrome() {
  const inScope = state.items.filter(inSelection);
  const total = inScope.length;
  const done = inScope.filter((i) => i.id in state.votes).length;
  const pos = Math.min(done + 1, total);
  document.getElementById("counter").textContent =
    `${String(pos).padStart(2, "0")}/${String(total).padStart(2, "0")}`;
  document.getElementById("ghost").textContent = String(pos).padStart(2, "0");
}

function mediaHTML(item) {
  if (item.image_key) {
    return `<img src="/${esc(item.image_key)}" alt="${esc(item.name)}">`;
  }
  return esc(item.emoji || "🤔");
}

function cardHTML(item) {
  return `
    <article class="card" id="card" data-item="${esc(item.id)}">
      <h2>${esc(item.name)}<span class="dot">.</span></h2>
      <div class="media">${mediaHTML(item)}</div>
      <div class="hint">→ ימני · ← שמאלני · ↓ ניטרלי</div>
      <div class="reveal hidden"></div>
    </article>`;
}

function showNextCard() {
  if (affq.shouldAsk(state)) {
    state.revealed = false;
    affq.renderQuestion(area(), (affiliation) => {
      if (affiliation) state.affiliation = affiliation;
      showNextCard();
    });
    return;
  }
  state.revealed = false;
  state.viewingBack = false;
  if (state.selected) {
    const inScope = state.items.filter(inSelection);
    if (state.selected.size === 0 || inScope.length === 0) {
      state.current = null;
      area().innerHTML = `
        <div class="endscreen">
          <h2>בחרו לפחות קטגוריה אחת<span class="dot">.</span></h2>
          <p class="summary">אין פריטים בקטגוריות שנבחרו</p>
        </div>`;
      return;
    }
  }
  if (state.queue.length === 0) {
    state.current = null;
    if (state.items.length === 0) {
      area().innerHTML = `
        <div class="endscreen">
          <h2>אין פריטים כרגע<span class="dot">.</span></h2>
          <p class="summary">חזרו בקרוב — פריטים חדשים נוספים כל הזמן</p>
        </div>`;
      return;
    }
    if (!state.affiliation) {
      affq.renderQuestion(area(), (affiliation) => {
        if (affiliation) state.affiliation = affiliation;
        showNextCard();
      });
      return;
    }
    emptyCbs.forEach((cb) => cb());
    return;
  }
  state.current = state.queue[0];
  updateChrome();
  area().innerHTML = cardHTML(state.byId.get(state.current));
}

function revealHTML(item, myChoice) {
  const l = item.votes_left, r = item.votes_right, n = item.votes_neutral;
  const lr = l + r;
  const pctL = lr ? Math.round((100 * l) / lr) : 50;
  const pctR = lr ? 100 - pctL : 50;
  const mark = (side) => (myChoice === side ? " ✓ הצבעת" : "");
  const xtLines = state.affiliation ? crossAttributionLines(item) : [];
  const xtHTML = xtLines.map((l) => `<div class="xt-line">${esc(l)}</div>`).join("");
  return `
    <div class="bar"><div class="bar-left"></div><div class="bar-right"></div></div>
    <div class="stats">
      <span class="right-side">ימני ${pctR}% · ${r.toLocaleString("he")} קולות${mark("right")}</span>
      <span class="left-side">שמאלני ${pctL}% · ${l.toLocaleString("he")} קולות${mark("left")}</span>
    </div>
    <div class="neutral-count">🤷 ${n.toLocaleString("he")} ניטרלי${mark("neutral")}</div>
    ${xtHTML}
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
  if (affq.isShowing()) {
    const map = { right: "right", left: "left", neutral: "center" };
    await affq.answer(map[choice], async () => {
      const me = await getMe();
      state.affiliation = me.body.affiliation || null;
      state.votes = me.body.votes || state.votes;
    });
    return;
  }
  if (submitting || state.revealed || !state.current) return;
  submitting = true;
  const id = state.current;
  try {
    const { status, body } = await vote(id, choice);
    if (id !== state.current) return; // stale response — state moved on
    if (status === 200) {
      state.byId.set(id, { ...state.byId.get(id), ...body.item });
      state.votes[id] = choice;
      state.queue = state.queue.filter((q) => q !== id);
      state.history.push(id);
      votesCbs.forEach((cb) => cb());
      renderReveal(state.byId.get(id), choice);
    } else if (status === 409) {
      const me = await getMe();
      state.votes = me.body.votes || state.votes;
      state.queue = state.queue.filter((q) => q !== id);
      votesCbs.forEach((cb) => cb());
      showNextCard();
    } else {
      window.showToast?.("משהו השתבש, נסו שוב");
    }
  } finally {
    submitting = false;
  }
}

export function next() {
  if (affq.isRevealed()) {
    document.getElementById("btn-next")?.click();
    return;
  }
  if (!state.revealed) return;
  showNextCard();
}

export function back() {
  const idx = state.history.indexOf(state.current);
  if (idx <= 0) return;
  const target = state.history[idx - 1];
  state.current = target;
  state.viewingBack = true;
  area().innerHTML = cardHTML(state.byId.get(target));
  renderReveal(state.byId.get(target), state.votes[target]);
}
