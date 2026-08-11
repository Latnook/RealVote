import seed
from app import db


def test_seed_items_creates_and_is_idempotent(fresh_table):
    items = [
        {"id": "a", "name": "א", "emoji": "🅰️", "category": "food"},
        {"id": "b", "name": "ב", "emoji": "🅱️", "category": "nonsense"},
    ]
    assert seed.seed_items(items) == 2
    assert db.get_item("a")["name"] == "א"
    # An unknown category falls back rather than raising, matching create_item.
    assert db.get_item("b")["category"] == "other"
    # Second run creates nothing and does not raise.
    assert seed.seed_items(items) == 0


def test_seed_items_carries_image_fields(fresh_table):
    seed.seed_items([{
        "id": "pic", "name": "תמונה", "emoji": "🖼️", "category": "food",
        "image_key": "img/pic-1.webp", "image_source": "https://example.org/p.jpg",
    }], with_images=True)
    item = db.get_item("pic")
    assert item["image_key"] == "img/pic-1.webp"
    assert item["image_source"] == "https://example.org/p.jpg"


def test_seed_items_omits_image_key_without_images(fresh_table):
    seed.seed_items([{
        "id": "pic", "name": "תמונה", "emoji": "🖼️", "category": "food",
        "image_key": "img/pic-1.webp", "image_source": "https://example.org/p.jpg",
    }])
    item = db.get_item("pic")
    assert "image_key" not in item          # no bytes on disk — fall back to the emoji
    assert item["image_source"] == "https://example.org/p.jpg"
