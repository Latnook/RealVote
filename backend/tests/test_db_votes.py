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


def test_list_all_votes_groups_by_uid(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.create_item("magnets", "מגנטים על המקרר", "🧲")
    db.record_vote("u1", "katan", "left")
    db.record_vote("u1", "magnets", "right")
    db.record_vote("u2", "katan", "neutral")

    got = db.list_all_votes()

    assert got["summary"]["voters"] == 2
    assert got["summary"]["ballots"] == 3
    assert got["summary"]["choices"] == {"left": 1, "right": 1, "neutral": 1}
    assert got["detail_truncated"] is False
    # sorted by ballot_count descending
    assert [v["uid"] for v in got["voters"]] == ["u1", "u2"]
    assert got["voters"][0]["ballot_count"] == 2
    assert {b["item_id"] for b in got["voters"][0]["ballots"]} == {"katan", "magnets"}


def test_list_all_votes_attaches_affiliation(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.set_affiliation("u1", "left")
    db.record_vote("u1", "katan", "left")
    db.record_vote("u2", "katan", "right")

    voters = {v["uid"]: v for v in db.list_all_votes()["voters"]}

    assert voters["u1"]["affiliation"] == "left"
    assert voters["u2"]["affiliation"] is None


def test_list_all_votes_affiliation_buckets_sum_to_voters(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.set_affiliation("u1", "left")
    db.set_affiliation("u2", "right")
    for uid in ("u1", "u2", "u3"):
        db.record_vote(uid, "katan", "left")

    summary = db.list_all_votes()["summary"]

    assert summary["affiliations"] == {"left": 1, "right": 1, "center": 0, "unknown": 1}
    assert sum(summary["affiliations"].values()) == summary["voters"]


def test_list_all_votes_ignores_profile_without_ballots(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.set_affiliation("lurker", "center")  # answered the card, never voted
    db.record_vote("u1", "katan", "left")

    got = db.list_all_votes()

    assert got["summary"]["voters"] == 1
    assert got["summary"]["affiliations"]["center"] == 0
    assert [v["uid"] for v in got["voters"]] == ["u1"]


def test_list_all_votes_truncates_detail_but_not_counts(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.create_item("magnets", "מגנטים על המקרר", "🧲")
    db.record_vote("u1", "katan", "left")
    db.record_vote("u1", "magnets", "right")

    got = db.list_all_votes(detail_cap=1)

    assert got["detail_truncated"] is True
    assert got["summary"]["ballots"] == 2          # counts stay exact
    assert got["voters"][0]["ballot_count"] == 2   # per-voter count stays exact
    assert len(got["voters"][0]["ballots"]) == 1   # only detail is cut


def test_list_all_votes_empty_table(fresh_table):
    got = db.list_all_votes()

    assert got["summary"] == {
        "voters": 0,
        "ballots": 0,
        "choices": {"left": 0, "right": 0, "neutral": 0},
        "affiliations": {"right": 0, "left": 0, "center": 0, "unknown": 0},
    }
    assert got["voters"] == []
    assert got["detail_truncated"] is False
