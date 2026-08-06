from app import db


def test_ensure_table_is_idempotent(fresh_table):
    db.ensure_table(fresh_table)  # second call must not raise
    assert db.table().item_count == 0
