#!/usr/bin/env node
// Boundary checks for the admin items-list sort control.
// Pure functions, no deps — run with `node scripts/check-item-sort.mjs`.
import { SORT_KEYS, sortItems } from "../site/admin/item-sort.js";

const cases = [];
function test(name, got, expected) {
  cases.push({ name, got, expected });
}

// Counters are guaranteed present and integral by db._to_item_dict, so the
// fixtures mirror that contract rather than exercising missing fields.
const ITEMS = [
  { id: "a", votes_left: 10, votes_right: 1, votes_neutral: 5 },   // total 16
  { id: "b", votes_left: 2, votes_right: 30, votes_neutral: 0 },   // total 32
  { id: "c", votes_left: 7, votes_right: 7, votes_neutral: 9 },    // total 23
];
const ids = (items) => items.map((i) => i.id).join(",");

test("left desc", ids(sortItems(ITEMS, "left", "desc")), "a,c,b");
test("left asc", ids(sortItems(ITEMS, "left", "asc")), "b,c,a");
test("right desc", ids(sortItems(ITEMS, "right", "desc")), "b,c,a");
test("right asc", ids(sortItems(ITEMS, "right", "asc")), "a,c,b");
test("neutral desc", ids(sortItems(ITEMS, "neutral", "desc")), "c,a,b");
test("neutral asc", ids(sortItems(ITEMS, "neutral", "asc")), "b,a,c");

// total sums all three choices, so it must not track any single counter:
// b wins on total (32) while losing badly on left and neutral.
test("total desc sums all three", ids(sortItems(ITEMS, "total", "desc")), "b,c,a");
test("total asc sums all three", ids(sortItems(ITEMS, "total", "asc")), "a,c,b");

// The default key means "however the API ordered them" (alphabetical by id),
// so the direction toggle must not silently reverse it.
test("default keeps input order", ids(sortItems(ITEMS, "default", "desc")), "a,b,c");
test("default ignores direction", ids(sortItems(ITEMS, "default", "asc")), "a,b,c");

// An unknown key would come from a typo in the <option value>; falling back to
// input order keeps the admin list rendering instead of throwing mid-render.
test("unknown key falls back to input order", ids(sortItems(ITEMS, "bogus", "desc")), "a,b,c");

// Ties must not jitter between refreshes: x and y are equal on left, and x
// precedes y in the input, so x must precede y in both directions.
const TIED = [
  { id: "x", votes_left: 5, votes_right: 0, votes_neutral: 0 },
  { id: "y", votes_left: 5, votes_right: 0, votes_neutral: 0 },
  { id: "z", votes_left: 9, votes_right: 0, votes_neutral: 0 },
];
test("ties keep input order when descending", ids(sortItems(TIED, "left", "desc")), "z,x,y");
test("ties keep input order when ascending", ids(sortItems(TIED, "left", "asc")), "x,y,z");

// loadItems() reuses the array it built per category, so sorting must not
// reorder the caller's array underneath it.
const original = [...ITEMS];
sortItems(ITEMS, "right", "desc");
test("does not mutate the input array", ids(ITEMS), ids(original));

test("exposes exactly the five selectable keys",
  [...SORT_KEYS].sort().join(","), "default,left,neutral,right,total");

let failures = 0;
for (const c of cases) {
  if (c.got === c.expected) {
    console.log(`PASS  ${c.name}`);
  } else {
    failures++;
    console.log(`FAIL  ${c.name}`);
    console.log(`      expected ${JSON.stringify(c.expected)}, got ${JSON.stringify(c.got)}`);
  }
}

console.log(`\n${cases.length - failures}/${cases.length} passed`);
if (failures > 0) {
  console.log("SUMMARY: FAIL");
  process.exit(1);
} else {
  console.log("SUMMARY: PASS");
}
