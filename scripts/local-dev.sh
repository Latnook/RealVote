#!/usr/bin/env bash
# Run the whole app locally: DynamoDB Local + seed + API/site server on :8080.
set -euo pipefail
cd "$(dirname "$0")/.."

export TABLE_NAME="${TABLE_NAME:-lr-local}"
export DDB_ENDPOINT="${DDB_ENDPOINT:-http://localhost:8000}"
export ALLOW_ADMIN="${ALLOW_ADMIN:-1}"   # local admin needs no login

# Start DynamoDB Local unless something already answers on :8000. A stale container
# from another checkout (or an old worktree) holds the port and makes `up` fail —
# and its in-memory table may predate schema changes, so we clear ours out first.
if curl -s -o /dev/null --max-time 2 "$DDB_ENDPOINT"; then
  echo "DynamoDB Local already listening on ${DDB_ENDPOINT} — reusing it."
  echo "  (If items look uncategorised, that table is stale: run"
  echo "   'docker ps | grep dynamo' and remove the container, or set TABLE_NAME=lr-\$RANDOM.)"
else
  docker compose up -d dynamodb
  # Wait for it to accept connections rather than racing the seed step.
  for _ in $(seq 1 30); do
    curl -s -o /dev/null --max-time 1 "$DDB_ENDPOINT" && break
    sleep 0.5
  done
fi

mkdir -p site
(cd backend && ../.venv/bin/python seed.py "$@")
exec .venv/bin/python backend/local_server.py
