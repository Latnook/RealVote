import pytest

from app import db


def test_ensure_table_is_idempotent(fresh_table):
    db.ensure_table(fresh_table)  # second call must not raise
    assert db.table().item_count == 0


def test_create_and_get_item(fresh_table):
    db.create_item("keter-chairs", "כיסאות כתר בגינה", "🪑")
    item = db.get_item("keter-chairs")
    assert item["name"] == "כיסאות כתר בגינה"
    assert item["status"] == "active"
    assert item["votes_left"] == 0 and item["votes_right"] == 0 and item["votes_neutral"] == 0


def test_get_missing_item_returns_none(fresh_table):
    assert db.get_item("nope") is None


def test_create_duplicate_raises(fresh_table):
    db.create_item("x", "א", "🅰️")
    with pytest.raises(Exception):
        db.create_item("x", "ב", "🅱️")


def test_list_active_excludes_archived(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.create_item("b", "ב", "🅱️")
    db.update_item("b", status="archived")
    ids = [i["id"] for i in db.list_active_items()]
    assert ids == ["a"]


def test_update_item_fields(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.update_item("a", name="אלף", image_key="img/a.webp")
    item = db.get_item("a")
    assert item["name"] == "אלף" and item["image_key"] == "img/a.webp"


def test_create_item_records_image_source(fresh_table):
    db.create_item("picanto", "קיה פיקנטו", "🚗",
                   image_key="img/picanto-1786477356.webp",
                   image_source="https://upload.wikimedia.org/wikipedia/commons/1/11/x.JPG")
    item = db.get_item("picanto")
    assert item["image_source"] == "https://upload.wikimedia.org/wikipedia/commons/1/11/x.JPG"


def test_image_source_absent_when_not_supplied(fresh_table):
    db.create_item("plain", "פשוט", "🙂")
    assert "image_source" not in db.get_item("plain")


def test_update_item_can_set_image_source(fresh_table):
    db.create_item("plain", "פשוט", "🙂")
    db.update_item("plain", image_source="https://example.org/pic.jpg")
    assert db.get_item("plain")["image_source"] == "https://example.org/pic.jpg"


def test_list_active_items_carries_image_source(fresh_table):
    db.create_item("a", "א", "🅰️", image_source="https://example.org/a.jpg")
    db.create_item("b", "ב", "🅱️")
    by_id = {i["id"]: i for i in db.list_active_items()}
    assert by_id["a"]["image_source"] == "https://example.org/a.jpg"
    assert "image_source" not in by_id["b"]
