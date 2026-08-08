"""Seed affiliated demo voters so cross-attribution lines have something to show.

Unlike a direct counter poke, this goes through the real code path — set_affiliation()
then record_vote() — so the main bar, the neutral count and the nine xt_* counters all
stay consistent with each other, exactly as they would in production.

Voter ids are deterministic (`xt-<camp>-<n>`), so re-running is a no-op rather than
doubling every tally.

Usage (from backend/):
    TABLE_NAME=lr-local DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python seed_crosstab.py
"""

import os
import random
import sys

from app import db

# How each camp votes on an item, as P(says "left" | says something decisive).
# 0.85 means 85% of that camp calls the item שמאלני.
#
# The display rule needs >70% of a camp attributing an item to the OPPOSITE camp,
# on 25+ decisive votes from that camp — so these profiles are chosen to land
# clearly above or clearly below that line.
PROFILES = {
    # Righties overwhelmingly call these left-wing; lefties are merely split.
    "soy-milk-coffee": {"right": 0.88, "left": 0.55, "center": 0.70},
    "vegan-food": {"right": 0.86, "left": 0.52, "center": 0.68},
    "going-to-theatre": {"right": 0.82, "left": 0.50, "center": 0.64},
    "berlin-vacation": {"right": 0.84, "left": 0.58, "center": 0.70},
    "homemade-kombucha": {"right": 0.87, "left": 0.60, "center": 0.72},
    # Lefties overwhelmingly call these right-wing (low P(left) = high P(right)).
    "keter-chairs": {"right": 0.45, "left": 0.14, "center": 0.30},
    "home-sign": {"right": 0.40, "left": 0.12, "center": 0.26},
    "kitchen-sign": {"right": 0.42, "left": 0.15, "center": 0.28},
    "fridge-magnets": {"right": 0.46, "left": 0.18, "center": 0.32},
    "dubai-vacation": {"right": 0.38, "left": 0.13, "center": 0.25},
    "stepup-competition": {"right": 0.44, "left": 0.16, "center": 0.30},
    # Both camps disown these onto each other — the two-line case.
    "friday-noon-wedding": {"right": 0.80, "left": 0.22, "center": 0.50},
    "corn-pizza": {"right": 0.78, "left": 0.20, "center": 0.48},
    "zimmer-jacuzzi": {"right": 0.76, "left": 0.24, "center": 0.52},
    # Deliberately unremarkable: both camps hover near the middle, so these should
    # normally stay below the threshold and show nothing. "Normally" is doing real
    # work — with ~50 item×camp cells, ordinary sampling noise pushes one over the
    # line now and then (sup-kinneret landed at 71% on the committed seed). That is
    # honest behaviour for a threshold rule, not a defect.
    "adopted-dog": {"right": 0.58, "left": 0.44, "center": 0.50},
    "sup-kinneret": {"right": 0.55, "left": 0.46, "center": 0.50},
    "6am-workout": {"right": 0.52, "left": 0.48, "center": 0.50},
    "park-bbq": {"right": 0.47, "left": 0.55, "center": 0.50},
}

CAMP_SIZES = {"right": 45, "left": 45, "center": 30}
P_NEUTRAL = 0.08  # chance a voter shrugs instead of picking a side
P_SKIP = 0.05  # chance a voter never reaches a given item


def main():
    if "TABLE_NAME" not in os.environ:
        sys.exit("TABLE_NAME must be set")
    rng = random.Random(20260807)  # fixed seed: same demo data every time

    known = {i["id"] for i in db.list_active_items()}
    missing = [k for k in PROFILES if k not in known]
    if missing:
        print(f"note: {len(missing)} profiled item(s) not in this table, skipping: {missing}")

    votes_cast = 0
    for camp, size in CAMP_SIZES.items():
        for n in range(size):
            uid = f"xt-{camp}-{n}"
            try:
                db.set_affiliation(uid, camp)
            except db.AlreadyVoted:
                pass  # already seeded on a previous run
            for item_id, profile in PROFILES.items():
                if item_id not in known or rng.random() < P_SKIP:
                    continue
                if rng.random() < P_NEUTRAL:
                    choice = "neutral"
                else:
                    choice = "left" if rng.random() < profile[camp] else "right"
                try:
                    db.record_vote(uid, item_id, choice)
                    votes_cast += 1
                except (db.AlreadyVoted, db.NotFound):
                    pass

    print(f"affiliated voters: {sum(CAMP_SIZES.values())}, votes cast this run: {votes_cast}")

    # Report which items now qualify, using the same rule the frontend applies.
    MIN_CAMP, THRESHOLD = 25, 0.70
    print("\nitems that will show a cross-attribution line:")
    any_line = False
    for item in db.list_active_items():
        lines = []
        for camp, opposite, label in (
            ("right", "left", "מהימנים חושבים שזה שמאלני"),
            ("left", "right", "מהשמאלנים חושבים שזה ימני"),
        ):
            decisive = item[f"xt_{camp}_left"] + item[f"xt_{camp}_right"]
            if decisive >= MIN_CAMP:
                pct = item[f"xt_{camp}_{opposite}"] / decisive
                if pct > THRESHOLD:
                    lines.append(f"{round(pct * 100)}% {label}")
        if lines:
            any_line = True
            print(f"  {item['name']}")
            for line in lines:
                print(f"      {line}")
    if not any_line:
        print("  (none yet — run again or widen the profiles)")


if __name__ == "__main__":
    main()
