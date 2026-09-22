# RealVote · דברים שהם… בעיניי

A Hebrew, right-to-left voting site built around an Israeli social-media trend: people posting lists
of *"things that are left-wing in my eyes"* and *"things that are right-wing in my eyes"*. Here the
crowd decides instead of the poster — you swipe through Friday-noon weddings, Keter garden chairs
and fridge magnets, calling each one **ימני** or **שמאלני**, and the split appears the moment you
vote.

Serverless on AWS, cheap when idle and able to absorb a viral day. No accounts, no tracking, no
personal data — an anonymous cookie is the whole identity model.

> **Status:** feature-complete and running locally. The AWS deployment
> (`realvote.latnook.com`) is the remaining piece.

## What it looks like

| Voting | The reveal |
|---|---|
| ![A card asking whether פוצ׳יוולי is right- or left-wing](docs/screenshots/card.png) | ![Results with both cross-attribution lines](docs/screenshots/reveal.png) |

The reveal above is the site's whole reason for existing: **72% of self-identified right-wingers
call a jacuzzi cabin left-wing, while 77% of left-wingers call it right-wing.** Both camps disown
it onto the other. That line only appears when a camp has 25+ decisive votes on an item and crosses
70% — the site stays quiet unless it has something worth saying.

| Who are you? | Categories | Admin |
|---|---|---|
| ![The identity question with a 🫵 emoji](docs/screenshots/identity.png) | ![Category filter list](docs/screenshots/categories.png) | ![Admin item manager](docs/screenshots/admin.png) |

Somewhere between your 3rd and 10th vote the site asks **האם אתה ימני או שמאלני?** (third option:
מרכז משעמם). From then on every earlier vote is retroactively attributed to your camp, which is
what makes the cross-tabulation possible.

On desktop the screen edges become full-height vote zones that mirror the arrow keys:

![Desktop layout with red and blue edge vote zones](docs/screenshots/desktop.png)

## How it works

**Voting.** Three equivalent inputs — buttons, arrow keys (`→` ימני, `←` שמאלני, `↓` ניטרלי), or a
swipe anywhere on the card area. Stats animate in after you vote, never before, so the crowd can't
lead you. No timer: you advance when you're ready, and can step back through what you answered.

**One vote per item** is enforced by the database, not the browser: the vote insert is a conditional
write, and the counter increments in the same DynamoDB transaction — so a thousand simultaneous
voters can't lose or double-count anything.

**Suggestions.** After five votes a ➕ appears. Suggestions land in a moderation queue rather than
going live, because a public political site attracts exactly what you'd expect.

**Categories.** Every item has one of twelve categories, and visitors can switch categories off in
the ☰ menu; the deck follows. There is deliberately no progress counter — the deck grows, and a
finish line would only make it feel like homework.

## Design

"Swiss gradient slate" — International-Typographic layout (strict grid, 2px rules, sharp corners,
generous space) on dark graphite, with the two vote fields as slowly drifting gradients:
deep indigo→cyan for ימני, crimson→burnt-orange for שמאלני. One theme, no light/dark toggle. Every
value lives in [`site/css/theme.css`](site/css/theme.css).

The direction mapping is treated as sacred throughout: **ימני is always right, blue, `→`; שמאלני is
always left, red, `←`.** Buttons, keys, swipes and the results bar all agree.

## Architecture

```
Browser ──► CloudFront ──┬──► S3            static site (no build step, vanilla ES modules)
                         └──► API Gateway ──► Lambda (Python) ──► DynamoDB (single table)
                                                                  Cognito guards /api/admin/*
```

Everything is pay-per-request: idle cost is under $1/month, and a viral day costs a few dollars that
day. There is no server to keep running, patch, or resize.

- **`backend/`** — one Lambda handler with a small router, a single-table DynamoDB data layer, and a
  local server that synthesizes the same API Gateway events so local and production run identical
  code.
- **`site/`** — static HTML/CSS/JS. No framework, no bundler, no dependencies; the files you edit
  are the files the browser runs.
- **`scripts/`** — local dev, image ingestion, and a check for the cross-attribution rule.

## Run it locally

Needs Docker, Python 3.12+, and ImageMagick (for the image tooling only).

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
./scripts/local-dev.sh --votes 50        # DynamoDB Local + seed + http://localhost:8080
```

Site at <http://localhost:8080>, admin at <http://localhost:8080/admin/> (authentication is skipped
locally; in production API Gateway verifies a Cognito token before any admin request reaches the
code). Add `HOST=0.0.0.0` to reach it from a phone on the same network.

To see the cross-attribution lines, seed voters who have declared a side:

```bash
cd backend && TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python seed_crosstab.py
```

## Tests

```bash
docker compose up -d dynamodb
cd backend && ../.venv/bin/pytest -q      # 134 tests against DynamoDB Local
node scripts/check-crosstab.mjs           # boundary checks for the cross-attribution rule
node scripts/check-credits.mjs            # credits page rendering, incl. safeHref
node scripts/check-html-patterns.mjs      # pattern="" attributes must compile under `v`
node scripts/check-item-sort.mjs          # admin items-list sort keys, direction and tie order
```

With the dev server running, this proves it reproduces the CloudFront response headers
policies, so a CSP violation found (or not found) locally means the same in production:

```bash
node scripts/check-headers.mjs http://localhost:8080 https://realvote.latnook.com
```

## Adding items and pictures

Items live in DynamoDB and are managed from `/admin/`. `backend/seed.py` seeds a local table
from the live site's public feed, so no AWS credentials are needed:

```bash
cd backend && TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python seed.py --with-images
```

The pictures themselves are **not in this repository**. Each item records the URL its picture came
from, and every one is listed at [`/credits/`](https://realvote.latnook.com/credits/);
`seed.py --with-images` pulls the pictures from the CDN into `site/img/` for local work. Items
without a picture fall back to a large emoji.

For bulk work: fill the `image_url` column of `images.csv` (a URL or a local path) and run

```bash
./scripts/add-image.py --from-csv images.csv     # --missing shows what still needs one
```

Remote images are **downloaded and stored**, never hotlinked — remote URLs expire and tracker
blockers drop requests to CDN hosts, so a hotlinked picture silently disappears for many visitors.
SVGs are kept as vectors and sanitised on the way in.

An item added from `/admin/` is live the moment it is created: the browser converts the picture and
uploads it straight to S3, and the same request writes the item to DynamoDB. There is no second
publishing step. `deploy.sh` ships code rather than content — it excludes `img/*` from the S3 sync
and never touches the table — so it is only needed when the code itself changes. Deploy first when a
change includes a new category: the category list lives in the Lambda, and an item filed under a
category the API doesn't serve yet has nowhere to appear.

## Teardown and rebuild

Two things live only in AWS. The DynamoDB table holds every vote, and the bucket's `img/`
prefix holds every picture — `site/img/` is gitignored and `deploy.sh` excludes `img/*`
from its sync, so neither comes back from a checkout. Point-in-time recovery does not
help either: PITR dies with the table it protects.

So `destroy.sh` snapshots both into `backups/<stamp>/` before Terraform touches anything,
and refuses to proceed if that snapshot came out empty while the stack is not
(`ALLOW_EMPTY_SNAPSHOT=1` overrides). The next `deploy.sh` restores from the newest
timestamped snapshot automatically:

```bash
./scripts/destroy.sh -auto-approve     # snapshot, then tear down
./scripts/deploy.sh  -auto-approve     # rebuild, then restore votes + pictures
```

Both halves of the restore are gated on emptiness — `restore.py` declines a table that
already holds rows, and pictures are only pushed when `img/` is empty — so an ordinary
deploy over a live stack restores nothing. `SKIP_RESTORE=1` opts out entirely.

The snapshot format is DynamoDB's own typed JSON, so a restored row is identical to the
exported one rather than something that survived a round-trip through Python types. The
pair is covered by `backend/tests/test_backup_restore.py`, which asserts that a restored
table serves byte-identical `list_active_items()`, `list_all_votes()` and affiliation
stats. Directories not named `YYYYMMDD-HHMMSS` are ignored by the restore, so a snapshot
you want to keep by hand can sit in `backups/` without ever being chosen.

Expect 30–60 minutes of downtime for a full cycle: CloudFront and the ACM certificate are
both slow to delete and recreate. The Cognito pool is replaced too, so the admin gets a
new temporary password by email and both SNS subscriptions need confirming again.

## Documentation

- [`docs/superpowers/specs/`](docs/superpowers/specs/) — the design documents, including why the
  cross-attribution rule has the thresholds it has
- [`docs/superpowers/plans/`](docs/superpowers/plans/) — the implementation plans, task by task

## Privacy

No accounts, no analytics, no third-party requests. A visitor is a random 32-character id in a
cookie. The one genuinely sensitive value — your political self-identification — is stored as one of
three words against that random id, with no name, email or IP beside it. The admin interface only
ever shows aggregates. The per-visitor counters behind the daily suggestion cap carry a two-day TTL,
so they expire rather than accumulating a record of when each id was active.

## Security

The admin API sits behind an API Gateway JWT authorizer backed by a single-account Cognito pool
(admin-create-only, 12-character password policy, TOTP available). The Lambda's own check is
`"jwt" in requestContext.authorizer` — absent unless the authorizer actually ran, so it fails
**closed**. `ALLOW_ADMIN=1` opens the admin API for local development and is ignored whenever
`AWS_LAMBDA_FUNCTION_NAME` is set, so it cannot take effect in production. IAM is scoped to one
table, one bucket prefix and one log group; the S3 bucket is reachable only through the
distribution's OAC.

Every render path escapes through an `esc()` helper, and a `Content-Security-Policy` with **no
`unsafe-inline` and no `unsafe-eval`** stands behind it, so a missed call is inert rather than
exploitable. Two policies are served (`terraform/cloudfront.tf`): the public site gets
`default-src 'none'` with everything else `'self'`; `/admin/*` additionally allows `connect-src
https:`, which it needs to fetch an operator-typed picture URL, reach Cognito, and PUT to a
presigned S3 URL. Both send HSTS, `nosniff`, `frame-ancestors 'none'` and a referrer policy.

Because there is no `unsafe-inline`, **inline `style=""` attributes and inline `<script>`/`<style>`
blocks will silently stop working** — set styles through the CSSOM (as `deck.js` and
`affiliation.js` do) and put rules in a stylesheet. `backend/local_server.py` serves the same
headers in development so a violation surfaces locally rather than in production.

Known and accepted: `lr_uid` is a client-side cookie, so a determined visitor can clear it to vote
again or reset the suggestion cap. Fixing that needs accounts or a CAPTCHA, which would cost more
than the poll is worth.

## Licence

MIT — see [`LICENSE`](LICENSE). Item pictures are **not** covered by it: each was collected from a
third-party source, recorded on the item itself and listed at
[`/credits/`](https://realvote.latnook.com/credits/). Their licences vary.
