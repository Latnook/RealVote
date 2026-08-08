#!/usr/bin/env node
// Boundary checks for the crosstab cross-attribution lines (spec §5).
// Pure functions, no deps — run with `node scripts/check-crosstab.mjs`.
import { crossAttributionLines, XT_MIN_CAMP_VOTES, XT_CROSS_THRESHOLD } from "../site/js/crosstab.js";

const cases = [];
function test(name, item, expectedLineCount, extra) {
  cases.push({ name, item, expectedLineCount, extra });
}

// 1. 24 decisive votes at 100% cross — below XT_MIN_CAMP_VOTES, must produce no line
//    even though the share is maximal.
test(
  "24 decisive @100% -> no line",
  { xt_right_left: 24, xt_right_right: 0, xt_left_left: 0, xt_left_right: 0 },
  0
);

// 2. 25 decisive votes at EXACTLY the 70% threshold -> the comparison is strict (>),
//    so this must not produce a line.
test(
  "25 decisive @ exactly 70% -> no line",
  { xt_right_left: 17.5, xt_right_right: 7.5, xt_left_left: 0, xt_left_right: 0 },
  0
);

// 3. 25 decisive votes at 71% -> crosses the threshold, exactly one "ימנים" line.
test(
  "25 decisive @ 71% -> one ימנים line",
  { xt_right_left: 17.75, xt_right_right: 7.25, xt_left_left: 0, xt_left_right: 0 },
  1,
  (lines) => lines[0].includes("ימנים") && lines[0].includes("שמאלני")
);

// 4. Own-camp claim: each camp overwhelmingly assigns the item to ITSELF
//    (right -> right, left -> left) -> no tension, no lines.
test(
  "own-camp claim -> no line",
  { xt_right_left: 10, xt_right_right: 90, xt_left_left: 90, xt_left_right: 10 },
  0
);

// 5. Both camps disowning the item (right says left, left says right) -> two lines.
test(
  "both camps disowning -> two lines",
  { xt_right_left: 90, xt_right_right: 10, xt_left_left: 10, xt_left_right: 90 },
  2
);

let failures = 0;
console.log(`XT_MIN_CAMP_VOTES=${XT_MIN_CAMP_VOTES} XT_CROSS_THRESHOLD=${XT_CROSS_THRESHOLD}\n`);
for (const c of cases) {
  const lines = crossAttributionLines(c.item);
  let ok = lines.length === c.expectedLineCount;
  let detail = "";
  if (ok && c.extra) {
    ok = c.extra(lines);
    if (!ok) detail = " (line content check failed)";
  }
  if (ok) {
    console.log(`PASS  ${c.name}`);
  } else {
    failures++;
    console.log(`FAIL  ${c.name}${detail}`);
    console.log(`      expected ${c.expectedLineCount} line(s), got ${lines.length}: ${JSON.stringify(lines)}`);
  }
}

console.log(`\n${cases.length - failures}/${cases.length} passed`);
if (failures > 0) {
  console.log("SUMMARY: FAIL");
  process.exit(1);
} else {
  console.log("SUMMARY: PASS");
}
