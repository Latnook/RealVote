import json

from app import db
from app.handler import lambda_handler
from conftest import apigw_event


def call(event):
    resp = lambda_handler(event, None)
    return resp, json.loads(resp["body"])


def seeded(fresh_table):
    db.create_item("keter", "כיסאות כתר", "🪑")
    db.create_item("soy", "חלב סויה", "🥛")


def test_get_items_lists_active_with_cache(fresh_table):
    seeded(fresh_table)
    resp, body = call(apigw_event("GET", "/api/items"))
    assert resp["statusCode"] == 200
    assert resp["headers"]["cache-control"] == "public, max-age=30"
    assert [i["id"] for i in body["items"]] == ["keter", "soy"]


def test_me_without_cookie_sets_one(fresh_table):
    resp, body = call(apigw_event("GET", "/api/me"))
    assert body == {"votes": {}}
    assert resp["cookies"][0].startswith("lr_uid=")
    assert resp["headers"]["cache-control"] == "no-store"


def test_vote_flow_and_dedup(fresh_table):
    seeded(fresh_table)
    resp, body = call(apigw_event("POST", "/api/vote",
                                  body={"item_id": "keter", "choice": "right"}))
    assert resp["statusCode"] == 200
    assert body["item"]["votes_right"] == 1 and body["your_choice"] == "right"
    uid_cookie = resp["cookies"][0].split(";")[0]  # lr_uid=<uid>
    resp2, _ = call(apigw_event("POST", "/api/vote", cookies=[uid_cookie],
                                body={"item_id": "keter", "choice": "left"}))
    assert resp2["statusCode"] == 409
    resp3, body3 = call(apigw_event("GET", "/api/me", cookies=[uid_cookie]))
    assert body3["votes"] == {"keter": "right"}


def test_vote_validation_errors(fresh_table):
    seeded(fresh_table)
    assert call(apigw_event("POST", "/api/vote", body={"item_id": "keter", "choice": "center"}))[0]["statusCode"] == 400
    assert call(apigw_event("POST", "/api/vote", body={"choice": "left"}))[0]["statusCode"] == 400
    assert call(apigw_event("POST", "/api/vote", body={"item_id": "ghost", "choice": "left"}))[0]["statusCode"] == 404
    bad = apigw_event("POST", "/api/vote")
    bad["body"] = "{oops"
    assert call(bad)[0]["statusCode"] == 400


def test_suggest_and_rate_limit(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/suggest", body={"text": "פיצה עם תירס"}))
    assert resp["statusCode"] == 202
    uid_cookie = resp["cookies"][0].split(";")[0]
    for _ in range(4):
        call(apigw_event("POST", "/api/suggest", cookies=[uid_cookie], body={"text": "עוד"}))
    resp429, _ = call(apigw_event("POST", "/api/suggest", cookies=[uid_cookie], body={"text": "עוד"}))
    assert resp429["statusCode"] == 429
    assert call(apigw_event("POST", "/api/suggest", body={"text": "  "}))[0]["statusCode"] == 400


def test_unknown_route_404(fresh_table):
    assert call(apigw_event("GET", "/api/nope"))[0]["statusCode"] == 404
