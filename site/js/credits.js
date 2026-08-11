// Pure rendering for the credits page: no DOM access, no fetch, no side
// effects at import time. `credits-page.js` fetches and injects; this module
// only turns items into markup so it can be unit-tested with plain node.
export const esc = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

// Only http(s) may become an href — an item's source is admin-entered text, and
// javascript: in an anchor would run on click.
export const safeHref = (url) => /^https?:\/\//i.test(url);

export function row(item) {
  const src = item.image_source && safeHref(item.image_source)
    ? `<a href="${esc(item.image_source)}" rel="noopener nofollow ugc"
          target="_blank">${esc(item.image_source)}</a>`
    : `<span class="none">מקור לא תועד</span>`;
  return `<li>
    <img src="/${esc(item.image_key)}" alt="" loading="lazy">
    <div class="meta">
      <div class="name">${esc(item.name)}</div>
      <div class="src">${src}</div>
    </div>
  </li>`;
}

// Items with no picture need no attribution; unattributed pictures are shown
// as a visible gap rather than quietly omitted.
export function renderRows(items) {
  const pictured = items
    .filter((i) => i.image_key)
    .sort((a, b) => a.name.localeCompare(b.name, "he"));
  return pictured.map(row).join("") ||
    `<li class="none">אין עדיין תמונות</li>`;
}
