import { getItems, getMe, vote } from "./api.js";

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
};

const emptyCbs = [], votesCbs = [];
let submitting = false;
export const onDeckEmpty = (cb) => emptyCbs.push(cb);
export const onVotesChanged = (cb) => votesCbs.push(cb);
export const isRevealed = () => state.revealed;
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
  state.queue = shuffle(state.items.filter((i) => !(i.id in state.votes)).map((i) => i.id));
  votesCbs.forEach((cb) => cb());
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
  state.revealed = false;
  state.viewingBack = false;
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
  return `
    <div class="bar"><div class="bar-left"></div><div class="bar-right"></div></div>
    <div class="stats">
      <span class="right-side">ימני ${pctR}% · ${r.toLocaleString("he")} קולות${mark("right")}</span>
      <span class="left-side">שמאלני ${pctL}% · ${l.toLocaleString("he")} קולות${mark("left")}</span>
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
