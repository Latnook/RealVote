# LR — דברים שהם… בעיניי

Hebrew voting site: is it ימני or שמאלני? The crowd decides.
Serverless AWS app (Plan 3) with a no-build vanilla-JS frontend and a
Python Lambda backend — all runnable locally.

## Run locally

    ./scripts/local-dev.sh --votes 50     # DynamoDB Local + seed + http://localhost:8080

Site: http://localhost:8080 · Admin: http://localhost:8080/admin/ (auto-authorized locally)

## Tests

    docker compose up -d dynamodb
    cd backend && ../.venv/bin/pytest -q

Docs: `docs/superpowers/specs/` (design), `docs/superpowers/plans/` (build plans).
