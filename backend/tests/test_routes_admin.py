import json

from app import db
from app.handler import lambda_handler
from conftest import apigw_event


def call(event):
    resp = lambda_handler(event, None)
    return resp, json.loads(resp["body"])


def test_admin_routes_require_auth(fresh_table):
    resp, body = call(apigw_event("GET", "/api/admin/suggestions"))
    assert resp["statusCode"] == 401


def test_env_flag_authorizes(fresh_table, monkeypatch):
    monkeypatch.setenv("ALLOW_ADMIN", "1")
    resp, _ = call(apigw_event("GET", "/api/admin/suggestions"))
    assert resp["statusCode"] == 200


def test_list_approve_reject_flow(fresh_table):
    s1 = db.add_suggestion("u1", "פיצה עם תירס")
    s2 = db.add_suggestion("u1", "משהו גרוע")
    resp, body = call(apigw_event("GET", "/api/admin/suggestions", admin=True))
    assert [s["sid"] for s in body["suggestions"]] == [s1, s2]

    resp, _ = call(apigw_event("POST", f"/api/admin/suggestions/{s1}/approve", admin=True,
                               body={"item_id": "corn-pizza", "name": "פיצה עם תירס", "emoji": "🌽"}))
    assert resp["statusCode"] == 200
    assert db.get_item("corn-pizza")["status"] == "active"

    call(apigw_event("POST", f"/api/admin/suggestions/{s2}/reject", admin=True))
    assert call(apigw_event("GET", "/api/admin/suggestions", admin=True))[1]["suggestions"] == []


def test_approve_unknown_sid_404(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/suggestions/nope/approve", admin=True,
                               body={"item_id": "x", "name": "א", "emoji": "🅰️"}))
    assert resp["statusCode"] == 404


def test_create_item_without_image(fresh_table):
    resp, body = call(apigw_event("POST", "/api/admin/items", admin=True,
                                  body={"item_id": "sup", "name": "סאפ בכנרת", "emoji": "🏄"}))
    assert resp["statusCode"] == 200 and body["upload_url"] is None
    assert db.get_item("sup")["name"] == "סאפ בכנרת"


def test_create_item_with_image_returns_presigned(fresh_table, monkeypatch):
    monkeypatch.setenv("IMG_BUCKET", "lr-fake-bucket")
    resp, body = call(apigw_event("POST", "/api/admin/items", admin=True,
                                  body={"item_id": "bbq", "name": "מנגל", "emoji": "🍖",
                                        "want_image": True}))
    assert body["image_key"].startswith("img/bbq-") and body["image_key"].endswith(".webp")
    assert "lr-fake-bucket" in body["upload_url"] and body["image_key"] in body["upload_url"]


def test_patch_item(fresh_table):
    db.create_item("a", "א", "🅰️")
    resp, _ = call(apigw_event("PATCH", "/api/admin/items/a", admin=True,
                               body={"status": "archived"}))
    assert resp["statusCode"] == 200
    assert db.get_item("a")["status"] == "archived"


def test_duplicate_item_id_409(fresh_table):
    db.create_item("a", "א", "🅰️")
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True,
                               body={"item_id": "a", "name": "ב", "emoji": "🅱️"}))
    assert resp["statusCode"] == 409


def test_approve_existing_item_409_reverts_suggestion_to_pending(fresh_table):
    db.create_item("a", "א", "🅰️")
    sid = db.add_suggestion("u1", "עוד א")
    resp, _ = call(apigw_event("POST", f"/api/admin/suggestions/{sid}/approve", admin=True,
                               body={"item_id": "a", "name": "א2", "emoji": "🅰️"}))
    assert resp["statusCode"] == 409
    _, body = call(apigw_event("GET", "/api/admin/suggestions", admin=True))
    pending = {s["sid"]: s["status"] for s in body["suggestions"]}
    assert pending.get(sid) == "pending"


def test_create_item_with_category(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True,
                               body={"item_id": "bbq", "name": "מנגל", "emoji": "🍖",
                                     "category": "food"}))
    assert resp["statusCode"] == 200
    assert db.get_item("bbq")["category"] == "food"


def test_create_item_bad_category_400(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/admin/items", admin=True,
                               body={"item_id": "x", "name": "א", "emoji": "🅰️",
                                     "category": "nope"}))
    assert resp["statusCode"] == 400


def test_create_item_without_category_defaults_other(fresh_table):
    call(apigw_event("POST", "/api/admin/items", admin=True,
                     body={"item_id": "x", "name": "א", "emoji": "🅰️"}))
    assert db.get_item("x")["category"] == "other"


def test_approve_with_category(fresh_table):
    sid = db.add_suggestion("u1", "פיצה עם תירס")
    resp, _ = call(apigw_event("POST", f"/api/admin/suggestions/{sid}/approve", admin=True,
                               body={"item_id": "corn-pizza", "name": "פיצה עם תירס",
                                     "emoji": "🌽", "category": "food"}))
    assert resp["statusCode"] == 200
    assert db.get_item("corn-pizza")["category"] == "food"


def test_patch_category_and_restore(fresh_table):
    db.create_item("a", "א", "🅰️", category="home")
    call(apigw_event("PATCH", "/api/admin/items/a", admin=True, body={"category": "food"}))
    assert db.get_item("a")["category"] == "food"
    call(apigw_event("PATCH", "/api/admin/items/a", admin=True, body={"status": "archived"}))
    assert db.get_item("a")["status"] == "archived"
    resp, _ = call(apigw_event("PATCH", "/api/admin/items/a", admin=True,
                               body={"status": "active"}))
    assert resp["statusCode"] == 200
    assert db.get_item("a")["status"] == "active"


def test_patch_bad_category_400(fresh_table):
    db.create_item("a", "א", "🅰️")
    assert call(apigw_event("PATCH", "/api/admin/items/a", admin=True,
                            body={"category": "nope"}))[0]["statusCode"] == 400


def test_admin_items_includes_archived(fresh_table):
    db.create_item("a", "א", "🅰️")
    db.create_item("b", "ב", "🅱️")
    db.update_item("b", status="archived")
    resp, body = call(apigw_event("GET", "/api/admin/items", admin=True))
    assert resp["statusCode"] == 200
    assert resp["headers"]["cache-control"] == "no-store"
    assert [i["id"] for i in body["items"]] == ["a", "b"]
    _, public = call(apigw_event("GET", "/api/items"))
    assert [i["id"] for i in public["items"]] == ["a"]


def test_admin_items_requires_auth(fresh_table):
    assert call(apigw_event("GET", "/api/admin/items"))[0]["statusCode"] == 401


def test_image_endpoint_returns_timestamped_key(fresh_table, monkeypatch):
    monkeypatch.setenv("IMG_BUCKET", "lr-fake-bucket")
    db.create_item("bbq", "מנגל", "🍖")
    resp, body = call(apigw_event("POST", "/api/admin/items/bbq/image", admin=True))
    assert resp["statusCode"] == 200
    assert body["image_key"].startswith("img/bbq-") and body["image_key"].endswith(".webp")
    assert "lr-fake-bucket" in body["upload_url"]


def test_image_endpoint_without_bucket(fresh_table):
    db.create_item("bbq", "מנגל", "🍖")
    _, body = call(apigw_event("POST", "/api/admin/items/bbq/image", admin=True))
    assert body["upload_url"] is None
    assert body["image_key"].startswith("img/bbq-")


def test_image_endpoint_unknown_item_404(fresh_table):
    assert call(apigw_event("POST", "/api/admin/items/ghost/image", admin=True))[0]["statusCode"] == 404


def test_create_item_image_key_is_timestamped(fresh_table):
    _, body = call(apigw_event("POST", "/api/admin/items", admin=True,
                               body={"item_id": "bbq", "name": "מנגל", "emoji": "🍖",
                                     "want_image": True}))
    assert body["image_key"].startswith("img/bbq-") and body["image_key"].endswith(".webp")


def test_admin_votes_requires_auth(fresh_table):
    resp, _ = call(apigw_event("GET", "/api/admin/votes"))
    assert resp["statusCode"] == 401


def test_admin_votes_returns_summary_and_voters(fresh_table):
    db.create_item("katan", "קטאן", "🎲")
    db.set_affiliation("u1", "left")
    db.record_vote("u1", "katan", "left")
    db.record_vote("u2", "katan", "right")

    resp, body = call(apigw_event("GET", "/api/admin/votes", admin=True))

    assert resp["statusCode"] == 200
    assert body["summary"]["voters"] == 2
    assert body["summary"]["ballots"] == 2
    assert body["summary"]["affiliations"] == {
        "right": 0, "left": 1, "center": 0, "unknown": 1
    }
    assert body["detail_truncated"] is False
    assert {v["uid"] for v in body["voters"]} == {"u1", "u2"}
    assert body["voters"][0]["ballots"][0]["item_id"] == "katan"


def test_admin_votes_empty_table(fresh_table):
    resp, body = call(apigw_event("GET", "/api/admin/votes", admin=True))
    assert resp["statusCode"] == 200
    assert body["summary"]["voters"] == 0
    assert body["voters"] == []
