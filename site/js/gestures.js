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
    if (["ArrowRight", "ArrowLeft", "ArrowDown"].includes(e.key)) e.preventDefault();
    if (e.key === "ArrowRight") castVote("right");
    else if (e.key === "ArrowLeft") castVote("left");
    else if (e.key === "ArrowDown") castVote("neutral");
  });

  // Swipe with tilt — pointer events, delegated so re-rendered cards keep working.
  const area = document.getElementById("card-area");
  let drag = null;

  area.addEventListener("pointerdown", (e) => {
    if (drag) return;
    // A swipe may start anywhere in the stage, not just on the card itself — on a phone
    // most of the reachable area is the empty space below it. The card is still what
    // moves; the touch merely has to land inside #card-area.
    const card = document.getElementById("card");
    if (!card || isRevealed()) return;
    if (e.target.closest("button, a, input, textarea")) return;   // let controls be controls
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
