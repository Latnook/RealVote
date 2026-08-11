#!/usr/bin/env node
// Boundary and security checks for the credits page's pure rendering module.
// Pure functions, no deps — run with `node scripts/check-credits.mjs`.
import { safeHref, row, renderRows } from "../site/js/credits.js";

const cases = [];
function test(name, fn) {
  cases.push({ name, fn });
}

// 1. javascript: must never be treated as a safe href, and row() must fall
//    back to the "unattributed" span rather than emit an anchor an admin's
//    text could turn into script execution.
test("safeHref rejects javascript: URLs", () => {
  if (safeHref("javascript:alert(1)") !== false) {
    return "safeHref(\"javascript:alert(1)\") should be false";
  }
  const html = row({
    name: "פריט",
    image_key: "items/a.jpg",
    image_source: "javascript:alert(1)",
  });
  if (html.includes("<a ")) {
    return `expected no <a> tag for a javascript: source, got: ${html}`;
  }
  if (!html.includes('<span class="none">מקור לא תועד</span>')) {
    return `expected the unattributed fallback span, got: ${html}`;
  }
  return null;
});

// 2. A genuine http(s) source becomes a real link.
test("safeHref accepts https and row() links it", () => {
  if (safeHref("https://example.org/p.jpg") !== true) {
    return "safeHref(\"https://example.org/p.jpg\") should be true";
  }
  const html = row({
    name: "פריט",
    image_key: "items/a.jpg",
    image_source: "https://example.org/p.jpg",
  });
  if (!html.includes('<a href="https://example.org/p.jpg"')) {
    return `expected an <a href="https://example.org/p.jpg" ...>, got: ${html}`;
  }
  return null;
});

// 3. data: URLs are also rejected — only http(s) is safe.
test("safeHref rejects data: URLs", () => {
  if (safeHref("data:text/html,<script>") !== false) {
    return "safeHref(\"data:text/html,<script>\") should be false";
  }
  return null;
});

// 4. No image_source at all -> the unattributed fallback.
test("row() with no image_source renders the fallback", () => {
  const html = row({ name: "פריט", image_key: "items/a.jpg" });
  if (!html.includes('<span class="none">מקור לא תועד</span>')) {
    return `expected the unattributed fallback span, got: ${html}`;
  }
  if (html.includes("<a ")) {
    return `expected no <a> tag when there is no source, got: ${html}`;
  }
  return null;
});

// 5. HTML metacharacters in name must be escaped, not injected raw.
test("row() escapes HTML metacharacters in name", () => {
  const html = row({
    name: '<img onerror=alert(1)>',
    image_key: "items/a.jpg",
  });
  if (html.includes("<img onerror=alert(1)>")) {
    return `unescaped payload leaked into markup: ${html}`;
  }
  if (!html.includes("&lt;img onerror=alert(1)&gt;")) {
    return `expected the escaped name in markup, got: ${html}`;
  }
  return null;
});

// 6. renderRows() filters out items with no image_key and keeps those with one.
test("renderRows() excludes items without image_key", () => {
  const items = [
    { name: "בלי תמונה" },
    { name: "עם תמונה", image_key: "items/b.jpg" },
  ];
  const html = renderRows(items);
  if (html.includes("בלי תמונה")) {
    return `expected item without image_key to be excluded, got: ${html}`;
  }
  if (!html.includes("עם תמונה")) {
    return `expected item with image_key to be included, got: ${html}`;
  }
  return null;
});

let failures = 0;
for (const c of cases) {
  const error = c.fn();
  if (error === null || error === undefined) {
    console.log(`PASS  ${c.name}`);
  } else {
    failures++;
    console.log(`FAIL  ${c.name}`);
    console.log(`      ${error}`);
  }
}

console.log(`\n${cases.length - failures}/${cases.length} passed`);
if (failures > 0) {
  console.log("SUMMARY: FAIL");
  process.exit(1);
} else {
  console.log("SUMMARY: PASS");
}
