// Sort keys for the admin items list. Pure and DOM-free so the boundaries stay
// checkable from node — see scripts/check-item-sort.mjs.

// db._to_item_dict guarantees all three counters are present and integral, so
// these read the fields directly rather than coalescing.
const VALUE = {
  total: (i) => i.votes_left + i.votes_right + i.votes_neutral,
  left: (i) => i.votes_left,
  right: (i) => i.votes_right,
  neutral: (i) => i.votes_neutral,
};

export const SORT_KEYS = Object.freeze(["default", ...Object.keys(VALUE)]);

/**
 * Orders items by one vote counter. Always returns a new array; "default" — and
 * any key not in VALUE — keeps the order the API supplied (alphabetical by id).
 * Array.prototype.sort is stable, so tied items hold that order too and the list
 * doesn't reshuffle itself on every refresh.
 */
export function sortItems(items, key, dir) {
  const value = VALUE[key];
  const sorted = [...items];
  if (!value) return sorted;
  const sign = dir === "asc" ? 1 : -1;
  return sorted.sort((a, b) => sign * (value(a) - value(b)));
}
