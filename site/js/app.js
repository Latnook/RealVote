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
