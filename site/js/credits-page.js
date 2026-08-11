// Built from the public feed, so the list is whatever the deck is currently showing.
import { renderRows } from "./credits.js";

async function main() {
  const list = document.getElementById("credits");
  let items = [];
  try {
    const resp = await fetch("/api/items");
    items = (await resp.json()).items || [];
  } catch {
    list.innerHTML = `<li class="none">לא ניתן לטעון את הרשימה</li>`;
    return;
  }
  list.innerHTML = renderRows(items);
}

main();
