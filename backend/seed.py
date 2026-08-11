"""Create the local table and seed it from the live site. Optionally add demo votes.

Items live in DynamoDB, not in this repo — the deck you get locally is whatever the
public feed is currently serving. That needs no AWS credentials and no admin token,
so a fresh clone can seed itself over plain HTTPS.

Usage: TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 python seed.py \
           [--feed URL] [--with-images] [--votes N]
"""
import argparse
import json
import os
import pathlib
import random
import sys
import urllib.request

from app import db

FEED = "https://realvote.latnook.com/api/items"
IMG_DIR = pathlib.Path(__file__).resolve().parent.parent / "site" / "img"


def fetch_items(feed_url):
    with urllib.request.urlopen(feed_url, timeout=30) as resp:
        return json.load(resp)["items"]


def seed_items(items):
    """Create every item that is not already there. Returns how many were created."""
    created = 0
    for it in items:
        try:
            db.create_item(
                it["id"], it["name"], it.get("emoji", ""),
                image_key=it.get("image_key"),
                category=it.get("category", "other"),
                image_source=it.get("image_source"),
            )
            created += 1
        except Exception:
            pass  # already seeded — idempotent
    return created


def fetch_images(items, base):
    """Pull pictures from the CDN into site/img/ so local cards are not emoji-only."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    got = 0
    for it in items:
        key = it.get("image_key")
        if not key:
            continue
        dest = IMG_DIR.parent / key
        if dest.exists():
            continue
        try:
            urllib.request.urlretrieve(f"{base}/{key}", dest)
            got += 1
        except Exception as e:
            print(f"  ✗ {it['id']}: {e}")
    return got


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", default=FEED, help="public /api/items URL to seed from")
    parser.add_argument("--with-images", action="store_true",
                        help="also download the pictures into site/img/")
    parser.add_argument("--votes", type=int, default=0)
    args = parser.parse_args()

    db.ensure_table(os.environ["TABLE_NAME"])
    try:
        items = fetch_items(args.feed)
    except Exception as e:
        print(f"could not read {args.feed}: {e}\n"
              f"seeding an empty deck — add items from /admin/", file=sys.stderr)
        items = []

    created = seed_items(items)
    print(f"items: {created} created, {len(items) - created} already existed")

    if args.with_images and items:
        base = args.feed.rsplit("/api/", 1)[0]
        print(f"images: {fetch_images(items, base)} downloaded")

    for n in range(args.votes):
        uid = f"demo-{n}"
        if not items:
            break
        for it in random.sample(items, k=random.randint(3, len(items))):
            choice = random.choices(["left", "right", "neutral"], weights=[45, 45, 10])[0]
            try:
                db.record_vote(uid, it["id"], choice)
            except db.AlreadyVoted:
                pass
    if args.votes:
        print(f"demo votes: {args.votes} visitors")


if __name__ == "__main__":
    sys.exit(main())
