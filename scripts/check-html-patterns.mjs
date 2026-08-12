#!/usr/bin/env node
// Every `pattern="..."` attribute in site/ must be a valid regular expression under the
// RegExp `v` flag.
//
// This exists because the failure mode is silent. Browsers compile the HTML `pattern`
// attribute with `v` (not `u`), and under `v` a trailing unescaped `-` in a character
// class — `[a-z0-9-]`, the obvious way to write it — is a syntax error. The browser does
// not fall back to `u` and does not surface anything to the user: it discards the
// attribute and validates nothing at all. The form still looks like it validates.
//
// site/admin/index.html shipped exactly that for months. The server-side check in
// backend/app/admin_routes.py caught the bad input anyway, so nothing broke visibly,
// which is precisely why it went unnoticed.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const SITE = join(ROOT, "site");

function* htmlFiles(dir) {
  for (const entry of readdirSync(dir)) {
    if (entry === "img" || entry === "vendor") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) yield* htmlFiles(full);
    else if (entry.endsWith(".html")) yield full;
  }
}

let checked = 0, failed = 0;
for (const file of htmlFiles(SITE)) {
  const html = readFileSync(file, "utf8");
  for (const m of html.matchAll(/\spattern="([^"]*)"/g)) {
    const source = m[1];
    checked++;
    // Anchoring mirrors how a browser wraps the attribute before compiling it.
    try {
      new RegExp(`^(?:${source})$`, "v");
      console.log(`PASS  ${relative(ROOT, file)}  pattern="${source}"`);
    } catch (err) {
      failed++;
      console.log(`FAIL  ${relative(ROOT, file)}  pattern="${source}"`);
      console.log(`        ${err.message}`);
      console.log(`        A browser would DISCARD this attribute and validate nothing.`);
    }
  }
}

console.log(`\n${checked - failed}/${checked} passed`);
console.log(`SUMMARY: ${failed ? "FAIL" : "PASS"}`);
process.exit(failed ? 1 : 0);
