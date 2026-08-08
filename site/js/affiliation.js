import { setAffiliation } from "./api.js";

const AT_KEY = "lr_affq_at";

let showing = false;
let answered = false;
let revealed = false;
let pendingAffiliation = null;
let onDone = () => {};

export const isShowing = () => showing;
// True once the choice is submitted and this module's own reveal (bar/stats + הבא) is on
// screen. deck.js folds this into its own isRevealed() so gestures.js's pointerdown-drag
// guard skips the card while the reveal is up — otherwise setPointerCapture on #card
// retargets the "הבא" button's click to the card and swallows it.
export const isRevealed = () => revealed;

/** Advance past the reveal, same as clicking הבא. Returns false if there's nothing to advance. */
export function advance() {
  if (!revealed) return false;
  finish(pendingAffiliation);
  return true;
}

function threshold() {
  try {
    const raw = localStorage.getItem(AT_KEY);
    if (raw) return parseInt(raw, 10);
    const k = 3 + Math.floor(Math.random() * 8); // 3..10 inclusive
    localStorage.setItem(AT_KEY, String(k));
    return k;
  } catch {
    return 3;
  }
}

/** Ask when the visitor has no affiliation and their total votes reached the drawn threshold. */
export function shouldAsk(state) {
  if (state.affiliation) return false;
  return Object.keys(state.votes).length >= threshold();
}

export function renderQuestion(area, done) {
  showing = true;
  answered = false;
  revealed = false;
  pendingAffiliation = null;
  onDone = done;
  area.innerHTML = `
    <article class="card" id="card" data-affq="1">
      <h2>האם אתה ימני או שמאלני?<span class="dot"></span></h2>
      <div class="media">🫵</div>
      <div class="hint">→ ימני · ← שמאלני · ↓ מרכז משעמם</div>
      <div class="reveal hidden"></div>
    </article>`;
  document.getElementById("btn-neutral").textContent = "מרכז משעמם ↓";
}

function revealHTML(stats, mine) {
  const total = stats.right + stats.left + stats.center || 1;
  const pctR = Math.round((100 * stats.right) / total);
  const pctL = Math.round((100 * stats.left) / total);
  const mark = (side) => (mine === side ? " ✓" : "");
  return `
    <div class="bar">
      <div class="bar-left" style="width:${pctL}%"></div>
      <div class="bar-right" style="width:${pctR}%"></div>
    </div>
    <div class="stats">
      <span class="right-side">ימנים ${pctR}%${mark("right")}</span>
      <span class="left-side">שמאלנים ${pctL}%${mark("left")}</span>
    </div>
    <div class="neutral-count">🤷 ${100 - pctR - pctL}% מרכז משעמם${mark("center")}</div>
    <div class="reveal-actions"><button class="primary" id="btn-next">הבא</button></div>`;
}

export async function answer(choice, refreshMe) {
  if (!showing || answered) return;
  answered = true;
  const { status, body } = await setAffiliation(choice);
  if (status !== 200 && status !== 409) {
    answered = false; // allow retry
    window.showToast?.("משהו השתבש, נסו שוב");
    return;
  }
  if (status === 409) {
    await refreshMe();
    finish();
    return;
  }
  const card = document.getElementById("card");
  card.querySelector(".hint").classList.add("hidden");
  const reveal = card.querySelector(".reveal");
  reveal.innerHTML = revealHTML(body.stats, body.affiliation);
  reveal.classList.remove("hidden");
  revealed = true;
  pendingAffiliation = body.affiliation;
  document.getElementById("btn-next").addEventListener("click", advance);
}

function finish(affiliation) {
  showing = false;
  revealed = false;
  pendingAffiliation = null;
  document.getElementById("btn-neutral").textContent = "ניטרלי ↓";
  onDone(affiliation);
}
