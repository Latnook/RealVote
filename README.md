# LR — דברים שהם… בעיניי

Hebrew voting site: is it ימני or שמאלני? The crowd decides.
Serverless AWS app (Plan 3) with a no-build vanilla-JS frontend and a
Python Lambda backend — all runnable locally.

## Run locally

    ./scripts/local-dev.sh --votes 50     # DynamoDB Local + seed + http://localhost:8080

Site: http://localhost:8080 · Admin: http://localhost:8080/admin/ (auto-authorized locally)

## Features

- Vote ימני / שמאלני / ניטרלי on each item; stats reveal after voting.
- A one-time "האם אתה ימני או שמאלני?" card appears between your 3rd and 10th vote; afterwards
  reveals can show cross-attribution lines like "78% מהימנים חושבים שזה שמאלני" (shown only when a
  camp has 25+ decisive votes on that item and crosses 70%).
- Items are categorised; the ☰ menu lets you switch categories off and the deck follows.
- `/admin/` manages the suggestion queue and every item: rename, re-file, emoji, image upload or
  replace, archive and restore.

## Tests

    docker compose up -d dynamodb
    cd backend && ../.venv/bin/pytest -q

Docs: `docs/superpowers/specs/` (design), `docs/superpowers/plans/` (build plans).
