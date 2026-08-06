import pytest

from app import db


@pytest.fixture()
def item(fresh_table):
    db.create_item("soy-coffee", "קפה עם חלב סויה", "🥛")
    return "soy-coffee"


def test_vote_increments_counter_and_returns_counts(item):
    result = db.record_vote("uid1", item, "left")
    assert result["votes_left"] == 1 and result["votes_right"] == 0


def test_three_uids_three_choices(item):
    db.record_vote("u1", item, "left")
    db.record_vote("u2", item, "right")
    db.record_vote("u3", item, "neutral")
    got = db.get_item(item)
    assert (got["votes_left"], got["votes_right"], got["votes_neutral"]) == (1, 1, 1)


def test_double_vote_rejected_and_not_counted(item):
    db.record_vote("u1", item, "left")
    with pytest.raises(db.AlreadyVoted):
        db.record_vote("u1", item, "right")
    assert db.get_item(item)["votes_right"] == 0


def test_vote_on_missing_or_archived_item(fresh_table):
    with pytest.raises(db.NotFound):
        db.record_vote("u1", "ghost", "left")
    db.create_item("old", "ישן", "🗿")
    db.update_item("old", status="archived")
    with pytest.raises(db.NotFound):
        db.record_vote("u1", "old", "left")


def test_bad_choice_raises_keyerror(item):
    with pytest.raises(KeyError):
        db.record_vote("u1", item, "center")


def test_get_user_votes(item):
    db.create_item("magnets", "מגנטים על המקרר", "🧲")
    db.record_vote("u9", item, "left")
    db.record_vote("u9", "magnets", "right")
    assert db.get_user_votes("u9") == {item: "left", "magnets": "right"}
    assert db.get_user_votes("stranger") == {}


def test_rejected_vote_leaves_no_record(fresh_table):
    db.create_item("old", "ישן", "🗿")
    db.update_item("old", status="archived")
    with pytest.raises(db.NotFound):
        db.record_vote("u1", "old", "left")
    assert db.get_user_votes("u1") == {}
