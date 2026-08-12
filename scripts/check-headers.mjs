#!/usr/bin/env node
// Compare the security headers two origins serve, path by path.
//
//   node scripts/check-headers.mjs http://localhost:8080 https://realvote.latnook.com
//
// The point is to prove that the dev server in backend/local_server.py really does
// reproduce the CloudFront response headers policies in terraform/cloudfront.tf, so a
// CSP violation found (or not found) locally means the same thing in production. Run it
// against a running local server before trusting a local browser test.
//
// Strict-Transport-Security is excluded by design: dev is plain http, where the header
// is meaningless and would pin localhost to https for a year if sent.

const COMPARED = [
  "content-security-policy",
  "x-content-type-options",
  "x-frame-options",
  "referrer-policy",
];

// One path per CloudFront cache behaviour, since each carries its own policy.
const PATHS = [
  ["/", "default behaviour (site)"],
  ["/credits/", "default behaviour (site)"],
  ["/css/app.css", "default behaviour (site)"],
  ["/admin/", "/admin/*"],
  ["/admin/admin.js", "/admin/*"],
  ["/api/items", "/api/items"],
  ["/api/me", "/api/*"],
];

const [, , a, b] = process.argv;
if (!a || !b) {
  console.error("usage: check-headers.mjs <base-a> <base-b>");
  process.exit(2);
}

async function headers(base, path) {
  const resp = await fetch(base + path, { redirect: "follow" });
  const out = {};
  for (const h of COMPARED) out[h] = resp.headers.get(h) ?? "(absent)";
  return { status: resp.status, out };
}

let failed = 0;
for (const [path, behaviour] of PATHS) {
  let ra, rb;
  try {
    [ra, rb] = await Promise.all([headers(a, path), headers(b, path)]);
  } catch (err) {
    console.log(`ERROR ${path} — ${err.message}`);
    failed++;
    continue;
  }
  const diffs = COMPARED.filter((h) => ra.out[h] !== rb.out[h]);
  if (diffs.length === 0) {
    console.log(`MATCH  ${path.padEnd(16)} [${behaviour}]`);
  } else {
    failed++;
    console.log(`DIFFER ${path.padEnd(16)} [${behaviour}]`);
    for (const h of diffs) {
      console.log(`         ${h}`);
      console.log(`           a: ${ra.out[h]}`);
      console.log(`           b: ${rb.out[h]}`);
    }
  }
}

console.log(failed ? `\n${failed} path(s) differ` : "\nall paths match");
process.exit(failed ? 1 : 0);
