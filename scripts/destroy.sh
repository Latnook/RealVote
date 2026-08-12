#!/usr/bin/env bash
# Snapshot everything that cannot be rebuilt from this repository, then tear it all down.
#
# Two things here exist nowhere else. The DynamoDB table holds every vote, and the
# bucket's img/ prefix holds every item picture — site/img/ is gitignored and deploy.sh
# excludes img/* from its sync, so neither comes back from a checkout. Point-in-time
# recovery does not help: PITR dies with the table it protects.
#
# The snapshot lands in backups/<stamp>/ and deploy.sh restores from the newest one it
# finds. Rehearse the whole loop with scripts/rehearse-cycle.sh before trusting it.
set -euo pipefail
cd "$(dirname "$0")/.."
TF="terraform -chdir=terraform"

# backup.py needs boto3, which lives in the project venv, not in the system python its
# shebang would otherwise pick.
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi

STAMP=$(date +%Y%m%d-%H%M%S)
DIR="backups/$STAMP"
mkdir -p "$DIR"

# Remove the snapshot directory if we abort before it holds anything. An empty but
# timestamped husk is worse than no directory at all: it outranks every older, good
# snapshot in deploy.sh's newest-wins selection.
cleanup_partial() {
  if [ ! -f "$DIR/table.json" ] && [ ! -d "$DIR/img" ]; then
    rmdir "$DIR" 2>/dev/null || true
  fi
}
trap cleanup_partial EXIT

TABLE=$($TF output -raw table_name 2>/dev/null || true)
REGION=$($TF output -raw region 2>/dev/null || true)
BUCKET=$($TF output -raw bucket 2>/dev/null || true)

if [ -n "${TABLE:-}" ]; then
  echo "==> exporting table $TABLE"
  "$PY" ./scripts/backup.py --table "$TABLE" --region "$REGION" --out "$DIR/table.json"
else
  echo "==> no table in state; skipping export"
fi

if [ -n "${BUCKET:-}" ]; then
  echo "==> copying s3://$BUCKET/img/ into the snapshot"
  aws s3 sync "s3://$BUCKET/img/" "$DIR/img/" --only-show-errors
  echo "    $(find "$DIR/img" -type f | wc -l) pictures saved"
fi

# Refuse to tear down behind a snapshot that saved nothing. Without this, a transient
# credential or network failure above would produce an empty backups/<stamp>/ and the
# destroy would proceed anyway — losing everything while looking like it had a backup.
ROWS=$(python3 -c "import json,sys;print(json.load(open('$DIR/table.json'))['count'])" 2>/dev/null || echo 0)
PICS=$(find "$DIR/img" -type f 2>/dev/null | wc -l)
echo "==> snapshot: $ROWS rows, $PICS pictures in $DIR"
if [ "$ROWS" -eq 0 ] && [ "$PICS" -eq 0 ] && [ -z "${ALLOW_EMPTY_SNAPSHOT:-}" ]; then
  echo "    the snapshot is empty and the stack is not — refusing to destroy." >&2
  echo "    Set ALLOW_EMPTY_SNAPSHOT=1 if the stack really is empty." >&2
  exit 1
fi

echo "==> emptying the site bucket (terraform cannot delete a non-empty bucket)"
[ -n "${BUCKET:-}" ] && aws s3 rm "s3://$BUCKET" --recursive --only-show-errors || true

echo "==> terraform destroy"
$TF destroy -var-file=realvote.tfvars "$@"

echo
echo "Destroyed. Snapshot kept at $DIR"
echo "The next ./scripts/deploy.sh restores from it automatically."
