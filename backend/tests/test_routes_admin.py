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
    assert body["image_key"] == "img/bbq.webp"
    assert "lr-fake-bucket" in body["upload_url"] and "img/bbq.webp" in body["upload_url"]


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
