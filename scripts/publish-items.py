#!/usr/bin/env python3
"""Publish seeded items and their pictures to production.

`deploy.sh` ships code, not content: it excludes `img/*` from the S3 sync and never touches
DynamoDB, so a new item added to backend/seed/items.json reaches production only through
this script. It does the two halves in the order that avoids a broken card — pictures to
S3 first, then the items already pointing at them.

    ./scripts/publish-items.py --dry-run          # show the plan, write nothing
    ./scripts/publish-items.py                    # every seeded item not yet in the table
    ./scripts/publish-items.py --since HEAD~1     # only ids added by recent commits
    ./scripts/publish-items.py tesla arak         # named ids

Safe to re-run: create_item is conditional on the item not existing, so items that are
already live keep their vote counts and any renaming or refiling done from /admin/.
That also means this script only ever ADDS — to rename, refile or re-picture something
that is already in production, use the admin page.

Pictures are matched from site/img/ by filename, the same `<id>-<epoch>.<ext>` convention
add-image.py writes and `--relink` reads; the newest file for an id wins. An item with no
picture on disk is still published — it falls back to a large emoji, exactly as locally.

No CloudFront invalidation is needed: image keys carry an epoch, so a newly published
picture is a URL the edge has never seen.
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "site" / "img"
SEED = ROOT / "backend" / "seed" / "items.json"
CONTENT_TYPES = {".webp": "image/webp", ".svg": "image/svg+xml"}


def tf_output(name):
    """Read a Terraform output, so the bucket/table/region are never hardcoded here."""
    try:
        out = subprocess.run(
            ["terraform", f"-chdir={ROOT / 'terraform'}", "output", "-raw", name],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        sys.exit("terraform is not on PATH — set BUCKET/TABLE_NAME/AWS_REGION instead")
    except subprocess.CalledProcessError as e:
        sys.exit(f"terraform output {name} failed — has the infra been applied?\n"
                 f"{e.stderr.strip()[:200]}")
    return out.stdout.strip()


def local_images():
    """Newest img/<id>-<epoch>.<ext> per item id."""
    best = {}
    for f in sorted(IMG_DIR.glob("*")) if IMG_DIR.is_dir() else []:
        m = re.match(r"(.+?)-(?:plated-)?(\d{10})\.(webp|svg)$", f.name)
        if not m:
            continue
        iid, ts = m.group(1), m.group(2)
        if iid not in best or ts > best[iid][0]:
            best[iid] = (ts, f)
    return {iid: f for iid, (_, f) in best.items()}


def ids_added_since(ref):
    """Item ids present in items.json now but not at `ref`.

    Reads the file out of git rather than diffing text, so a reformat or a moved entry
    doesn't register as an addition.
    """
    try:
        old = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{ref}:backend/seed/items.json"],
            check=True, capture_output=True, text=True,
        ).stdout
    except subprocess.CalledProcessError:
        sys.exit(f"cannot read backend/seed/items.json at {ref}")
    return {i["id"] for i in json.loads(SEED.read_text())} - {i["id"] for i in json.loads(old)}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="item ids to publish (default: whatever the "
                                           "table is missing)")
    ap.add_argument("--since", metavar="REF",
                    help="publish only ids that items.json gained since REF, e.g. HEAD~1")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    args = ap.parse_args()

    if args.ids and args.since:
        ap.error("give ids or --since, not both")

    seeded = {i["id"]: i for i in json.loads(SEED.read_text())}
    images = local_images()

    bucket = os.environ.get("BUCKET") or tf_output("bucket")
    table = os.environ.get("TABLE_NAME") or tf_output("table_name")
    region = os.environ.get("AWS_REGION") or tf_output("region")

    # app.db must import with production settings: a stray DDB_ENDPOINT would send every
    # write to DynamoDB Local and report a cheerful success against the wrong table.
    os.environ["TABLE_NAME"] = table
    os.environ.pop("DDB_ENDPOINT", None)
    os.environ.setdefault("AWS_DEFAULT_REGION", region)
    sys.path.insert(0, str(ROOT / "backend"))
    from app import db

    if args.ids:
        unknown = [i for i in args.ids if i not in seeded]
        if unknown:
            sys.exit(f"not in {SEED.relative_to(ROOT)}: {', '.join(unknown)}")
        wanted = list(args.ids)
    elif args.since:
        wanted = [i for i in seeded if i in ids_added_since(args.since)]
    else:
        print(f"==> checking {table} for items it is missing")
        wanted = [i for i in seeded if db.get_item(i) is None]

    # Keep seed order: the deck is built from it, and a predictable order makes the log
    # easy to compare against a previous run.
    wanted = [i for i in seeded if i in set(wanted)]
    if not wanted:
        print("nothing to publish — production already has every seeded item")
        return

    live = [i for i in wanted if db.get_item(i) is not None]
    if live:
        print(f"{len(live)} of these are already in the table and will be left alone: "
              f"{', '.join(live)}")
    todo = [i for i in wanted if i not in set(live)]
    unpictured = [i for i in todo if i not in images]
    if unpictured:
        print(f"{len(unpictured)} have no picture in site/img/ and will fall back to "
              f"their emoji: {', '.join(unpictured)}")
    if not todo:
        return

    verb = "would publish" if args.dry_run else "publishing"
    print(f"\n==> {verb} {len(todo)} item(s) to {table} / s3://{bucket}/img/")
    for iid in todo:
        it = seeded[iid]
        pic = images.get(iid)
        size = f"{pic.stat().st_size // 1024} KB" if pic else "no picture"
        print(f"  {'·' if args.dry_run else '+'} {iid:24} {it['category']:9} "
              f"{it['name']}  ({size})")
    if args.dry_run:
        print("\ndry run — nothing was written")
        return

    import boto3
    s3 = boto3.client("s3", region_name=region)
    published = 0
    for iid in todo:
        it = seeded[iid]
        key = None
        if iid in images:
            pic = images[iid]
            key = f"img/{pic.name}"
            s3.upload_file(str(pic), bucket, key, ExtraArgs={
                "ContentType": CONTENT_TYPES[pic.suffix.lower()]})
        try:
            db.create_item(iid, it["name"], it.get("emoji", ""),
                           image_key=key, category=it.get("category", "other"))
        except Exception as e:
            # A race with the admin page, or a second run started before the first
            # finished. The picture is already in S3 and harmless; the item stands.
            if "ConditionalCheckFailed" not in str(e):
                raise
            print(f"  = {iid} appeared in the table meanwhile, left alone")
            continue
        published += 1
        print(f"  ✓ {iid}" + (f" → {key}" if key else ""))

    print(f"\npublished {published} item(s) to {table}")
    print(f"verify: curl -s https://realvote.latnook.com/api/items | "
          f"python3 -c \"import sys,json; print(len(json.load(sys.stdin)['items']))\"")


if __name__ == "__main__":
    main()
