#!/usr/bin/env bash
# Run the whole app locally: DynamoDB Local + seed + API/site server on :8080.
set -euo pipefail
cd "$(dirname "$0")/.."

export TABLE_NAME="${TABLE_NAME:-lr-local}"
export DDB_ENDPOINT="${DDB_ENDPOINT:-http://localhost:8000}"
export ALLOW_ADMIN="${ALLOW_ADMIN:-1}"   # local admin needs no login

docker compose up -d dynamodb
mkdir -p site
(cd backend && ../.venv/bin/python seed.py "$@")
exec .venv/bin/python backend/local_server.py
