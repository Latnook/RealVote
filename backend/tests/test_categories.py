from app import categories, db


def test_category_list_shape():
    assert categories.DEFAULT == "other"
    assert len(categories.CATEGORIES) == 13
    assert categories.CATEGORIES[0] == {"slug": "events", "label": "אירועים"}
    assert {c["slug"] for c in categories.CATEGORIES} == categories.SLUGS
    assert all(c["label"].strip() for c in categories.CATEGORIES)


def test_is_valid():
    assert categories.is_valid("food")
    assert categories.is_valid("other")
    assert not categories.is_valid("nope")
    assert not categories.is_valid(None)
    assert not categories.is_valid(123)


def test_create_item_defaults_to_other(fresh_table):
    db.create_item("a", "א", "🅰️")
    assert db.get_item("a")["category"] == "other"


def test_create_item_with_category(fresh_table):
    db.create_item("bbq", "מנגל", "🍖", category="food")
    assert db.get_item("bbq")["category"] == "food"


def test_update_item_can_refile(fresh_table):
    db.create_item("bbq", "מנגל", "🍖", category="food")
    db.update_item("bbq", category="events")
    assert db.get_item("bbq")["category"] == "events"


def test_legacy_record_without_category_reads_as_other(fresh_table):
    db.table().put_item(
        Item={
            "PK": "ITEM#legacy", "SK": "META", "name": "ישן", "emoji": "🗿",
            "status": "active", "votes_left": 0, "votes_right": 0, "votes_neutral": 0,
        }
    )
    assert db.get_item("legacy")["category"] == "other"
