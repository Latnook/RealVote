import pytest

from app import db


def test_add_and_list_pending(fresh_table):
    sid = db.add_suggestion("u1", "  פיצה עם תירס  ")
    pending = db.list_suggestions("pending")
    assert [s["sid"] for s in pending] == [sid]
    assert pending[0]["text"] == "פיצה עם תירס"


def test_daily_cap_five(fresh_table):
    for n in range(5):
        db.add_suggestion("u1", f"הצעה {n}")
    with pytest.raises(db.RateLimited):
        db.add_suggestion("u1", "אחת יותר מדי")
    db.add_suggestion("u2", "משתמש אחר בסדר")


def test_text_trimmed_to_120_chars(fresh_table):
    db.add_suggestion("u1", "א" * 300)
    assert len(db.list_suggestions("pending")[0]["text"]) == 120


def test_status_transitions(fresh_table):
    sid = db.add_suggestion("u1", "משהו")
    db.set_suggestion_status(sid, "approved")
    assert db.list_suggestions("pending") == []
    assert db.list_suggestions("approved")[0]["sid"] == sid


def test_set_status_unknown_sid_raises(fresh_table):
    with pytest.raises(db.NotFound):
        db.set_suggestion_status("nope", "rejected")


def test_rate_counter_carries_ttl(fresh_table):
    """The table's TTL is configured on `expires_at`; without it these rows never expire."""
    import time

    db.add_suggestion("u1", "משהו")
    row = db._resource().Table(fresh_table).scan(
        FilterExpression="begins_with(PK, :r)",
        ExpressionAttributeValues={":r": "RATE#"},
    )["Items"][0]
    assert int(row["expires_at"]) > int(time.time())
    assert int(row["expires_at"]) <= int(time.time()) + db.RATE_TTL_SECONDS
