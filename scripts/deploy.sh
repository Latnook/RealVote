#!/usr/bin/env bash
# Apply the infrastructure, publish the site, and point the admin page at Cognito.
set -euo pipefail
cd "$(dirname "$0")/.."
TF="terraform -chdir=terraform"

if [ ! -f terraform/realvote.tfvars ]; then
  echo "terraform/realvote.tfvars is missing — copy realvote.tfvars.example and fill it in." >&2
  exit 1
fi

echo "==> terraform apply"
$TF init -backend-config=backend.hcl -upgrade >/dev/null
$TF apply -var-file=realvote.tfvars "$@"

BUCKET=$($TF output -raw bucket)
DIST=$($TF output -raw distribution_id)
URL=$($TF output -raw site_url)

# The admin page fetches /admin/config.json to decide between LOCAL and CLOUD mode.
# It must exist in production and must NOT be committed.
echo "==> writing site/admin/config.json"
cat > site/admin/config.json <<JSON
{
  "region": "$($TF output -raw region)",
  "userPoolId": "$($TF output -raw user_pool_id)",
  "userPoolClientId": "$($TF output -raw user_pool_client_id)"
}
JSON

echo "==> syncing site/ to s3://$BUCKET"
# Long cache for fingerprinted-by-content assets, short for HTML and config so a
# redeploy is visible immediately even before the invalidation lands.
aws s3 sync site/ "s3://$BUCKET/" --delete \
  --exclude "*.html" --exclude "admin/config.json" \
  --cache-control "public,max-age=86400"
aws s3 sync site/ "s3://$BUCKET/" \
  --exclude "*" --include "*.html" --include "admin/config.json" \
  --cache-control "no-cache"

echo "==> invalidating CloudFront"
# CSS and JS are referenced without version strings, so a partial invalidation can
# leave new HTML pointing at old modules. Invalidate everything.
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" >/dev/null

echo
echo "Deployed: $URL"
echo "Admin:    $URL/admin/"
echo "If this was the first apply, confirm the SNS subscription email AWS just sent you."
