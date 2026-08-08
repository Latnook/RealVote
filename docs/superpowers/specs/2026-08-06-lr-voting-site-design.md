# RealVote — "דברים שהם … בעיניי" voting site — Design

> **Extended by** [`2026-08-07-lr-affiliation-categories-design.md`](2026-08-07-lr-affiliation-categories-design.md):
> visitor self-identification with cross-attribution stats, item categories with visitor filters,
> and admin item management.

**Date:** 2026-08-06
**Status:** Approved by Ariel (UX 2026-08-06, data/API 2026-08-06, infra 2026-08-06)
**Name:** RealVote → site at `realvote.latnook.com` (chosen 2026-08-07; the subdomain is a
Terraform variable). Earlier drafts used the placeholder `lr`, which survives in file names.

## 1. What this is

A Hebrew, RTL, mobile-first voting site for the TikTok/Reels trend
"דברים שהם שמאלניים/ימניים בעיניי", timed for the upcoming Israeli elections. Visitors see one
item at a time (e.g. חתונת שישי בצהריים) and vote ימני / שמאלני / ניטרלי. After voting they see
the crowd's split. Visitors can suggest new items; the owner approves them through an admin page.
No user accounts; an anonymous cookie prevents re-voting and powers a "my votes" view.

Spelling: standard — שמאלני (not the meme spelling שמלאני).

## 2. UX

### Voting flow
- Site opens directly into a full-screen card: item image (or big emoji fallback) + item name.
- Three vote inputs, all equivalent:
  - Buttons: ימני (right, blue-gradient), שמאלני (left, red-gradient), ניטרלי strip below.
  - Keyboard: `→` ימני, `←` שמאלני, `↓` ניטרלי.
  - Touch: swipe right/left/down with Tinder-style card tilt while dragging.
  - Arrows always match sides: ימני →, ← שמאלני, ↓ ניטרלי.
- **Reveal:** on vote, a stats bar animates in from both edges (red from left, blue from right),
  with percentages, raw counts, ניטרלי count, and a ✓ on the visitor's choice. **No auto-advance
  timer** — a הבא affordance moves on (tap/swipe/any-key), חזרה flips back through answered
  cards (view-only; no re-vote, no vote editing in v1).
- Item order: shuffled client-side (the CDN-cached items list is identical for everyone;
  the browser shuffles and puts unvoted items first using its own votes from `/api/me`).
- Progress: item counter (e.g. 07/24) + oversized "ghost numeral" behind the layout.

### After 5 votes
A floating ➕ button appears: one-field suggestion form ("מה עוד שכחנו?") → thank-you
("תודה! ההצעה תיבדק") → owner's approval queue. Not published directly.

### My votes
☰ menu → list of everything voted: item, own choice, current crowd split
("הצבעת: שמאלני · הקהל: 68% איתך").

### End of deck
"זהו, עברת על הכל!" + personal summary ("הסכמת עם הרוב ב-N% מהפריטים") + suggest CTA +
share button (native share sheet).

## 3. Visual design — "K²: Swiss gradient slate"

Swiss/International-Typographic system on dark graphite with modern gradient accents.
Chosen over alternatives after mockup rounds (Müller-Brockmann poster palettes, warm greige,
mid-tones, acid/glass directions).

Theme tokens (all CSS variables in one theme file; freely changeable post-launch):

| Token | Value |
|---|---|
| Background | `#23262B` |
| Ink / rules | `#F2F3F5`, 2px rules, sharp corners |
| Muted text | `#8B9099` |
| Card surface | `#2E3238` |
| ימני gradient | `#3730A3 → #0E7490` (deep indigo → deep cyan) |
| שמאלני gradient | `#B91C1C → #C2410C` (crimson → burnt orange) |
| Accent period | wordmark/titles end with a gradient-colored "." |

- Layout: strict grid, 2px ink rules, ghost index numeral, **centered** image block with 2px
  ink border + hard offset shadow. Titles set huge, bold, RTL.
- Desktop: full-height edge vote zones (blue right, red left) mirroring the arrow keys;
  ניטרלי as a full-width bottom strip.
- Motion: gradients drift slowly (~7s loop, background-position); reveal bar grows from both
  edges; card tilts while swiping. Subtle, non-blocking.
- Single theme — no light/dark modes.
- Typeface: Helvetica-family stack with a Hebrew-capable fallback (e.g. Noto Sans Hebrew).

## 4. Data model — DynamoDB, one table, on-demand

| Record | Key pattern | Attributes |
|---|---|---|
| Item | `ITEM#<id>` | name, image key (optional; emoji fallback), status `active/archived`, `votes_left`, `votes_right`, `votes_neutral`, created_at |
| Vote | `USER#<uid>` / `VOTE#<item_id>` | choice `left/right/neutral`, timestamp |
| Suggestion | `SUGG` / `<time-prefixed id>` | text, status `pending/approved/rejected`, uid, timestamp (single partition; SK time-prefix gives oldest-first ordering) |

- Vote counting: atomic `ADD` increments on the item record — correct under any concurrency.
- Double-vote prevention: vote insert is a **conditional put** (`attribute_not_exists`) —
  enforced by the database, not the browser. Item counter increments only on successful insert.
- "My votes": single query on `USER#<uid>`.
- Cookie: random anonymous id, `Secure` + `HttpOnly` + `SameSite=Lax`, 1-year. No PII anywhere.
  Deleting the cookie makes a fresh visitor (accepted trade-off; replay/bots still blocked).

## 5. API — API Gateway (HTTP API) + one Python Lambda

| Route | Behavior |
|---|---|
| `GET /api/items` | Active items + counts. CDN-cached ~30s. |
| `GET /api/me` | Visitor's votes (from cookie). Never cached. |
| `POST /api/vote` | `{item_id, choice}` → 200 + fresh counts; 409 if already voted; sets cookie if absent. |
| `POST /api/suggest` | `{text}` → 202 into pending queue. Limit ~5/day/visitor. |
| *(admin auth)* | Amazon **Cognito** user pool with one admin user: username + password (MFA off by default; can be enabled in Cognito later without code changes). The admin page signs in via the Cognito SDK and sends the resulting JWT as an `Authorization` header; an **API Gateway JWT authorizer** verifies it before requests reach the Lambda — no self-written auth code. Lockout/rate-limiting handled by Cognito. |
| `GET /api/admin/suggestions` | Pending queue. |
| `POST /api/admin/suggestions/<id>/approve` | Creates item (name editable at approval; optional image). |
| `POST /api/admin/suggestions/<id>/reject` | Rejects. |
| `POST /api/admin/items` | Create item; returns presigned S3 URL for image upload. |
| `PATCH /api/admin/items/<id>` | Rename / archive / replace image. |

- Errors: clean JSON (`{"error": ...}`); frontend shows Hebrew toast and retries reads;
  a failed vote leaves the card in place (never silently dropped).
- Images: admin uploads via presigned S3 URL; browser resizes/compresses before upload
  (no server-side image processing). Served via CloudFront under `/img/`.
- Anti-abuse v1: DB-level dedup, API Gateway throttling, per-visitor suggestion cap,
  admin login rate-limit. AWS WAF deliberately excluded (adds ~$5/mo; a few Terraform lines
  later if needed).

## 6. Frontend

Static HTML/CSS/vanilla JS, no build step (Voteball philosophy). RTL, Hebrew-only.
Admin page is part of the same static site behind the login. Static OG/social meta tags.
Served from S3 through CloudFront.

## 7. Infrastructure — Terraform, all of it

**Region: `il-central-1` (Tel Aviv)** for all regional resources (Lambda, API Gateway,
DynamoDB, Cognito, S3, SNS, logs) — availability verified 2026-08-06. Two exceptions live
in `us-east-1` because AWS requires it for global services: the ACM certificate used by
CloudFront, and the CloudWatch billing alarm. Terraform uses a second provider alias for
those.

Resources: S3 bucket (site + `/img/`), CloudFront (OAC to S3; `/api/*` → API Gateway;
~30s cache on `GET /api/items`), ACM cert (us-east-1) + Route53 record for
`<subdomain>.latnook.com`, API Gateway HTTP API (with a Cognito JWT authorizer on
`/api/admin/*`), Python Lambda, DynamoDB table (on-demand), **Cognito user pool** (single
admin user), CloudWatch logs + 5xx alarm, **billing alarm** (~$10/mo
threshold) → SNS email, IAM roles (least privilege). Secrets Manager is no longer needed —
Cognito holds the only credential.

- State: S3 backend, reusing the existing bootstrap bucket pattern, separate state key.
- `./scripts/deploy.sh` — terraform apply + sync site files + CloudFront invalidation.
- `./scripts/destroy.sh` — **exports DynamoDB data to a local file first**, then destroys.
- Domain, thresholds, admin email: variables in `lr.tfvars` (gitignored; `.example` committed).
- Cost: idle < $1/month; viral day ≈ a few dollars that day (all pay-per-request; Lambda 1M
  req/mo and CloudFront 1TB/mo free tiers).

## 8. Local development

Everything runs locally before AWS: DynamoDB Local (official Docker image) + the Lambda code
served by a small local HTTP wrapper + static frontend. Seed script creates demo items/votes.
Verified locally: voting (all three inputs), reveal, dedup, my-votes, suggest flow, admin flow.

## 9. Testing

- `pytest` unit tests against DynamoDB Local: vote logic, dedup (409), counters, rate limits,
  admin auth, suggestion lifecycle.
- Post-deploy smoke script: hits the live site end-to-end (vote with a throwaway id, check
  counters, suggest, admin login).
- Manual device checklist: swipe on iOS/Android, arrow keys on desktop, RTL rendering,
  back/reveal pacing.
- Optional local screenshot checks via headless Chromium.

## 10. Security summary

No credentials in git or code — the only credential lives in Cognito (username + password;
MFA available as a later toggle), and admin API routes are verified by API Gateway before
reaching our code; anonymous visitors (no PII, no accounts); HttpOnly/Secure visitor cookie;
least-privilege IAM; HTTPS-only via CloudFront; S3 buckets private (OAC);
no third-party trackers.

## 11. Out of scope for v1

Vote editing; user accounts; AWS WAF; multi-language; analytics beyond vote counts;
automated image sourcing; light/dark themes.

## 12. Open items

1. **Final name/subdomain** — `lr` is a placeholder; decide before public launch.
2. **Seed content** — I draft ~24 items from the trend; Ariel edits/approves.
3. **Images** — optional per item at launch (emoji fallback); added gradually via admin.
