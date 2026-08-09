#!/usr/bin/env bash
# Export the table, then tear everything down.
set -euo pipefail
cd "$(dirname "$0")/.."
TF="terraform -chdir=terraform"

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="backups/realvote-$STAMP.json"
mkdir -p backups

TABLE=$($TF output -raw table_name 2>/dev/null || true)

if [ -n "${TABLE:-}" ]; then
  echo "==> exporting $TABLE to $OUT"
  aws dynamodb scan --table-name "$TABLE" --region "$($TF output -raw region)" --output json > "$OUT"
  echo "    $(python3 -c "import json;print(len(json.load(open('$OUT'))['Items']))" ) items saved"
else
  echo "==> no table found in state; skipping export"
fi

echo "==> emptying the site bucket (terraform cannot delete a non-empty bucket)"
BUCKET=$($TF output -raw bucket 2>/dev/null || true)
[ -n "$BUCKET" ] && aws s3 rm "s3://$BUCKET" --recursive >/dev/null || true

echo "==> terraform destroy"
$TF destroy -var-file=realvote.tfvars "$@"
echo
echo "Destroyed. Data export kept at $OUT"
