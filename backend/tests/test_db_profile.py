import pytest

from app import db


def test_affiliation_absent_by_default(fresh_table):
    assert db.get_affiliation("u1") is None


def test_set_and_get_affiliation(fresh_table):
    stats = db.set_affiliation("u1", "right")
    assert db.get_affiliation("u1") == "right"
    assert stats == {"right": 1, "left": 0, "center": 0}


def test_set_affiliation_is_once_only(fresh_table):
    db.set_affiliation("u1", "right")
    with pytest.raises(db.AlreadyVoted):
        db.set_affiliation("u1", "left")
    assert db.get_affiliation("u1") == "right"


def test_invalid_affiliation_raises(fresh_table):
    with pytest.raises(KeyError):
        db.set_affiliation("u1", "centrist")


def test_global_stats_tally(fresh_table):
    db.set_affiliation("u1", "right")
    db.set_affiliation("u2", "right")
    db.set_affiliation("u3", "center")
    assert db.get_affiliation_stats() == {"right": 2, "left": 0, "center": 1}


def test_item_exposes_zeroed_crosstab_counters(fresh_table):
    db.create_item("a", "א", "🅰️")
    item = db.get_item("a")
    for aff in ("right", "left", "center"):
        for choice in ("left", "right", "neutral"):
            assert item[f"xt_{aff}_{choice}"] == 0


def test_vote_with_affiliation_increments_crosstab(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.set_affiliation("u1", "right")
    item = db.record_vote("u1", "a", "left")
    assert item["votes_left"] == 1
    assert item["xt_right_left"] == 1
    assert item["xt_left_left"] == 0


def test_vote_without_affiliation_touches_only_main_counters(fresh_table):
    db.create_item("a", "א", "🅰️")
    item = db.record_vote("anon", "a", "left")
    assert item["votes_left"] == 1
    assert all(item[f"xt_{a}_left"] == 0 for a in ("right", "left", "center"))


def test_answering_backfills_earlier_votes(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.create_item("b", "ב", "🅱️")
    db.create_item("c", "ג", "🅲")
    db.record_vote("u1", "a", "left")
    db.record_vote("u1", "b", "right")
    db.record_vote("u1", "c", "neutral")
    db.set_affiliation("u1", "right")
    assert db.get_item("a")["xt_right_left"] == 1
    assert db.get_item("b")["xt_right_right"] == 1
    assert db.get_item("c")["xt_right_neutral"] == 1
    assert db.get_item("a")["xt_left_left"] == 0


def test_backfill_does_not_touch_other_voters_counters(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.record_vote("other", "a", "left")
    db.record_vote("u1", "a", "left")
    db.set_affiliation("u1", "left")
    assert db.get_item("a")["xt_left_left"] == 1
    assert db.get_item("a")["votes_left"] == 2
