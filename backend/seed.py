"""Create the local table and load seed items. Optionally add demo votes.

Usage: TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 python seed.py [--votes N]
"""
import argparse
import json
import pathlib
import random
import sys

from app import db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--votes", type=int, default=0)
    args = parser.parse_args()

    import os
    db.ensure_table(os.environ["TABLE_NAME"])
    items = json.loads((pathlib.Path(__file__).parent / "seed" / "items.json").read_text())
    created = 0
    for it in items:
        try:
            db.create_item(it["id"], it["name"], it["emoji"],
                           category=it.get("category", "other"))
            created += 1
        except Exception:
            pass  # already seeded — idempotent
    print(f"items: {created} created, {len(items) - created} already existed")

    for n in range(args.votes):
        uid = f"demo-{n}"
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
