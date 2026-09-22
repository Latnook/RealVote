#!/usr/bin/env bash
# Apply the infrastructure, publish the site, and point the admin page at Cognito.
set -euo pipefail
cd "$(dirname "$0")/.."
TF="terraform -chdir=terraform"

if [ ! -f terraform/realvote.tfvars ]; then
  echo "terraform/realvote.tfvars is missing — copy realvote.tfvars.example and fill it in." >&2
  exit 1
fi

# Deploy only what CI has seen. The sync publishes the working tree, not a commit, so
# without this an uncommitted edit or an unpushed commit reaches production untested.
# DEPLOY_UNCHECKED=1 skips it — for an emergency, when GitHub itself is the problem.
if [ -z "${DEPLOY_UNCHECKED:-}" ]; then
  echo "==> checking this commit is committed, pushed and green in CI"
  # Untracked files count: anything not ignored under site/ gets synced.
  if [ -n "$(git status --porcelain)" ]; then
    echo "Uncommitted changes — commit them (so CI tests them) before deploying:" >&2
    git status --short >&2
    exit 1
  fi
  git fetch --quiet origin main
  HEAD_SHA=$(git rev-parse HEAD)
  if [ "$HEAD_SHA" != "$(git rev-parse origin/main)" ]; then
    echo "HEAD is not origin/main — push main (or check out what is on it) before deploying." >&2
    exit 1
  fi
  if ! command -v gh >/dev/null; then
    echo "gh (GitHub CLI) is not installed, so CI status cannot be checked." >&2
    exit 1
  fi
  CI=$(gh run list --workflow ci.yml --commit "$HEAD_SHA" --limit 1 \
         --json status,conclusion --jq '.[0] | "\(.status) \(.conclusion)"')
  case "$CI" in
    "completed success") echo "    CI passed on ${HEAD_SHA:0:7}" ;;
    "")                  echo "No CI run found for ${HEAD_SHA:0:7} yet — wait for it to start." >&2; exit 1 ;;
    completed*)          echo "CI failed on ${HEAD_SHA:0:7} ($CI) — fix it before deploying." >&2; exit 1 ;;
    *)                   echo "CI is still running on ${HEAD_SHA:0:7} — wait for it: gh run watch" >&2; exit 1 ;;
  esac
fi

echo "==> terraform apply"
$TF init -backend-config=backend.hcl >/dev/null
$TF apply -var-file=realvote.tfvars "$@"

BUCKET=$($TF output -raw bucket)
DIST=$($TF output -raw distribution_id)
URL=$($TF output -raw site_url)
TABLE=$($TF output -raw table_name)
REGION=$($TF output -raw region)

# Restore from the newest destroy.sh snapshot, if there is one and this stack is bare.
#
# Both halves are gated on emptiness, so a routine deploy over a live stack does nothing:
# restore.py refuses a table that already holds rows, and the pictures are only pushed
# when the img/ prefix is empty. That makes this safe to run on every deploy rather than
# something to remember at exactly the wrong moment. SKIP_RESTORE=1 opts out entirely.
# Newest snapshot that actually holds an export. Two guards, both learned the hard way:
#   1. Only YYYYMMDD-HHMMSS directories count. A plain backups/*/ glob sorts lexically,
#      so any letter-prefixed directory ("rehearsal-…", "keep-…") sorts after every
#      timestamp and silently wins, restoring stale data over a fresh teardown.
#   2. It must contain table.json. A destroy that aborts mid-export leaves an empty but
#      timestamped husk which would otherwise outrank the last good snapshot.
SNAPSHOT=$(ls -d backups/[0-9]*/ 2>/dev/null | sort -r |
           while read -r d; do [ -f "$d/table.json" ] && { echo "$d"; break; }; done || true)
if [ -n "${SNAPSHOT:-}" ] && [ -z "${SKIP_RESTORE:-}" ]; then
  echo "==> snapshot found: $SNAPSHOT"
  if [ -f "${SNAPSHOT}table.json" ]; then
    echo "==> restoring table $TABLE"
    # restore.py needs boto3 from the project venv, not the system python.
    if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
    "$PY" ./scripts/restore.py --table "$TABLE" --region "$REGION" --in "${SNAPSHOT}table.json"
  fi
  if [ -d "${SNAPSHOT}img" ]; then
    if [ -z "$(aws s3 ls "s3://$BUCKET/img/" 2>/dev/null | head -1)" ]; then
      echo "==> restoring $(find "${SNAPSHOT}img" -type f | wc -l) pictures to s3://$BUCKET/img/"
      # Keys are timestamped and never rewritten in place (see s3.tf), so they are
      # genuinely immutable and can be cached for as long as the CDN will hold them.
      aws s3 sync "${SNAPSHOT}img/" "s3://$BUCKET/img/" --only-show-errors \
        --cache-control "public,max-age=31536000,immutable"
    else
      echo "==> img/ already populated — leaving it alone"
    fi
  fi
fi

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
# css/js are NOT fingerprinted-by-content (no hash in the filename), so a returning
# browser could pair fresh HTML with a stale cached module. Keep edges long-cached
# (s-maxage) but make browsers revalidate within minutes (max-age); short cache for
# HTML and config so a redeploy is visible immediately even before the invalidation
# lands. img/ is excluded from --delete because it's gitignored and holds
# admin-uploaded pictures that don't exist in the local site/ tree — without this
# exclude, every deploy would wipe the bucket's uploaded images.
aws s3 sync site/ "s3://$BUCKET/" --delete \
  --exclude "*.html" --exclude "admin/config.json" --exclude "img/*" \
  --cache-control "public,max-age=300,s-maxage=86400"
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
