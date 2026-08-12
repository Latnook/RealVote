"""The teardown/rebuild loop, exercised against DynamoDB Local.

destroy.sh's export existed for a long time with no counterpart that could read it back.
These tests are the reason to believe the pair actually round-trips before it is trusted
with a production table full of real votes.
"""
import importlib.util
import json
import os
import pathlib

import pytest

from app import db

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
ENDPOINT = os.environ.get("DDB_ENDPOINT", "http://localhost:8000")


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


backup = load("backup")
restore = load("restore")


def populate(uid_count=3, item_count=4):
    """A table holding one of every row kind the site writes."""
    for n in range(item_count):
        db.create_item(f"item-{n}", f"פריט {n}", "🧪",
                       image_key=f"img/item-{n}-123.webp" if n % 2 else None,
                       image_source="https://example.org/p.jpg" if n % 2 else None)
    for u in range(uid_count):
        uid = f"{u:032x}"
        db.set_affiliation(uid, ("right", "left", "center")[u % 3])
        for n in range(item_count):
            db.record_vote(uid, f"item-{n}", ("left", "right", "neutral")[n % 3])
    db.add_suggestion("f" * 32, "הצעה לבדיקה")


def export_to(tmp_path, table):
    items, _ = backup.export(table, endpoint=ENDPOINT)
    path = tmp_path / "table.json"
    path.write_text(json.dumps({"table": table, "count": len(items), "items": items},
                               ensure_ascii=False), encoding="utf-8")
    return path, items


def client():
    return restore._client(None, ENDPOINT)


def test_export_captures_every_row_kind(fresh_table, tmp_path):
    populate()
    _, items = export_to(tmp_path, fresh_table)
    kinds = backup.summarise(items)
    assert kinds["items"] == 4
    assert kinds["votes"] == 12          # 3 voters x 4 items
    assert kinds["profiles"] == 3
    assert kinds["suggestions"] == 1
    assert kinds["rate"] == 1            # the suggestion's daily counter
    assert kinds["stats"] == 1           # the affiliation tally


def test_round_trip_restores_every_row(fresh_table, tmp_path, monkeypatch):
    populate()
    path, items = export_to(tmp_path, fresh_table)
    before = {(i["PK"]["S"], i["SK"]["S"]): i for i in items}

    # Stand in for "terraform made a brand new empty table".
    fresh = f"{fresh_table}-rebuilt"
    db.ensure_table(fresh)
    try:
        c = client()
        assert restore.row_count(c, fresh) == 0
        restore.restore(c, fresh, items)
        after_items, _ = backup.export(fresh, endpoint=ENDPOINT)
        after = {(i["PK"]["S"], i["SK"]["S"]): i for i in after_items}
        assert after.keys() == before.keys()
        assert after == before, "a restored row differs from the exported one"
    finally:
        db._resource().Table(fresh).delete()


def test_restored_table_serves_identical_reads(fresh_table, tmp_path, monkeypatch):
    """Vote tallies, cross-tabs and affiliation stats must survive the trip."""
    populate()
    items_before = db.list_active_items()
    votes_before = db.list_all_votes()
    stats_before = db.get_affiliation_stats()
    _, rows = export_to(tmp_path, fresh_table)

    fresh = f"{fresh_table}-reread"
    db.ensure_table(fresh)
    try:
        restore.restore(client(), fresh, rows)
        monkeypatch.setenv("TABLE_NAME", fresh)
        assert db.list_active_items() == items_before
        assert db.list_all_votes() == votes_before
        assert db.get_affiliation_stats() == stats_before
    finally:
        db._resource().Table(fresh).delete()


def test_restore_refuses_a_populated_table(fresh_table, tmp_path):
    """A routine deploy must never overwrite live votes with a stale snapshot."""
    populate()
    _, rows = export_to(tmp_path, fresh_table)
    c = client()
    assert restore.row_count(c, fresh_table) > 0
    # restore.main() is what deploy.sh calls; it declines and exits 0 rather than writing.
    import sys
    argv = sys.argv
    sys.argv = ["restore.py", "--table", fresh_table, "--endpoint", ENDPOINT,
                "--in", str(tmp_path / "table.json")]
    try:
        assert restore.main() == 0
    finally:
        sys.argv = argv


def test_restore_detects_a_truncated_backup(fresh_table, tmp_path):
    """A file whose header disagrees with its body is a corrupt backup, not a partial one."""
    populate()
    path, rows = export_to(tmp_path, fresh_table)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["items"] = payload["items"][:-3]      # lost rows in transit
    path.write_text(json.dumps(payload), encoding="utf-8")

    import sys
    argv = sys.argv
    sys.argv = ["restore.py", "--table", fresh_table, "--endpoint", ENDPOINT, "--in", str(path)]
    try:
        with pytest.raises(SystemExit) as e:
            restore.main()
        assert "inconsistent" in str(e.value)
    finally:
        sys.argv = argv


def test_batching_handles_more_than_one_batch(fresh_table, tmp_path):
    """DynamoDB caps batch_write_item at 25, so the loop must chunk correctly."""
    populate(uid_count=8, item_count=6)          # ~60 rows, well past one batch
    _, rows = export_to(tmp_path, fresh_table)
    assert len(rows) > restore.BATCH

    fresh = f"{fresh_table}-batched"
    db.ensure_table(fresh)
    try:
        written = restore.restore(client(), fresh, rows)
        assert written == len(rows)
        assert restore.row_count(client(), fresh) == len(rows)
    finally:
        db._resource().Table(fresh).delete()
