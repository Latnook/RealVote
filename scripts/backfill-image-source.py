#!/usr/bin/env python3
"""Backfill image_source onto items whose picture predates the field.

Provenance used to live in images.csv, a hand-edited file that README.md cited for
picture licensing. It now lives on the item record and is published at /credits/.
This walks the CSV once and patches every item it can account for.

    ./scripts/backfill-image-source.py --dry-run     # show the plan, write nothing
    ./scripts/backfill-image-source.py               # apply it

Idempotent: an item that already carries an image_source is left alone, so a partial
run can simply be repeated. Items with no picture are skipped (nothing to attribute),
and so are CSV rows for ids the table does not have.
"""

import argparse
import csv
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "images.csv"


def plan_backfill(rows, items):
    """Return [(item_id, url)] for pictured items that have a source but no image_source."""
    plan = []
    for row in rows:
        iid = (row.get("id") or "").strip()
        url = (row.get("image_url") or "").strip()
        if not iid or not url:
            continue
        item = items.get(iid)
        if not item or not item.get("image_key") or item.get("image_source"):
            continue
        plan.append((iid, url))
    return plan


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def site_url():
    """Read the site URL from Terraform so it is never hardcoded here."""
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"].rstrip("/")
    try:
        out = subprocess.run(
            ["terraform", f"-chdir={ROOT / 'terraform'}", "output", "-raw", "site_url"],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        sys.exit("terraform is not on PATH — set SITE_URL instead")
    except subprocess.CalledProcessError as e:
        sys.exit(f"terraform output site_url failed — has the infra been applied?\n"
                 f"{e.stderr.strip()[:200]}")
    return out.stdout.strip().rstrip("/")


def fetch_items(base):
    with urllib.request.urlopen(f"{base}/api/items", timeout=30) as resp:
        return {i["id"]: i for i in json.load(resp)["items"]}


def patch(base, token, item_id, url):
    req = urllib.request.Request(
        f"{base}/api/admin/items/{item_id}",
        data=json.dumps({"image_source": url}).encode(),
        headers={"content-type": "application/json", "authorization": token},
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status == 200


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    ap.add_argument("--csv", type=pathlib.Path, default=CSV_PATH)
    args = ap.parse_args()

    base = site_url()
    items = fetch_items(base)
    rows = read_rows(args.csv)
    plan = plan_backfill(rows, items)

    pictured = [i for i in items.values() if i.get("image_key")]
    unsourced = [i["id"] for i in pictured
                 if not i.get("image_source") and i["id"] not in dict(plan)]

    print(f"==> {len(items)} items, {len(pictured)} with pictures, {len(plan)} to backfill")
    for iid, url in plan:
        print(f"  · {iid:24} {url[:70]}")
    if unsourced:
        print(f"no source recorded for {len(unsourced)}: {', '.join(sorted(unsourced))}")

    if args.dry_run:
        print("\ndry run — nothing was written")
        return 0
    if not plan:
        print("nothing to do")
        return 0

    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        sys.exit("set ADMIN_TOKEN to a Cognito id token (copy it from /admin/ devtools)")

    ok = sum(patch(base, token, iid, url) for iid, url in plan)
    print(f"\nbackfilled {ok}/{len(plan)}")
    return 0 if ok == len(plan) else 1


if __name__ == "__main__":
    sys.exit(main())
