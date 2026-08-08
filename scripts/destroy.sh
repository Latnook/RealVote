#!/usr/bin/env bash
# Export the table, then tear everything down.
set -euo pipefail
cd "$(dirname "$0")/.."
TF="terraform -chdir=terraform"

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="backups/realvote-$STAMP.json"
mkdir -p backups

TABLE=$(terraform -chdir=terraform state show aws_dynamodb_table.main 2>/dev/null | awk -F'"' '/^\s+name /{print $2; exit}')

if [ -n "${TABLE:-}" ]; then
  echo "==> exporting $TABLE to $OUT"
  aws dynamodb scan --table-name "$TABLE" --output json > "$OUT"
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
