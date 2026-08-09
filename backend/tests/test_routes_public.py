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
    assert body == {"votes": {}, "affiliation": None}
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


def test_vote_bad_choice_type_400(fresh_table):
    seeded(fresh_table)
    resp, _ = call(apigw_event("POST", "/api/vote",
                               body={"item_id": "keter", "choice": ["left"]}))
    assert resp["statusCode"] == 400


def test_vote_malformed_cookie_treated_as_absent(fresh_table):
    seeded(fresh_table)
    huge_uid = "x" * 3000
    resp, body = call(apigw_event("POST", "/api/vote",
                                  cookies=["lr_uid=" + huge_uid],
                                  body={"item_id": "keter", "choice": "left"}))
    assert resp["statusCode"] == 200
    assert "cookies" in resp and resp["cookies"]
    new_uid_cookie = resp["cookies"][0]
    assert new_uid_cookie.startswith("lr_uid=")
    new_uid = new_uid_cookie.split(";")[0].split("=", 1)[1]
    assert new_uid != huge_uid
    resp2, body2 = call(apigw_event("GET", "/api/me", cookies=[new_uid_cookie.split(";")[0]]))
    assert body2["votes"] == {"keter": "left"}


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


def test_early_400s_still_set_cookie(fresh_table):
    bad = apigw_event("POST", "/api/vote")
    bad["body"] = "{oops"
    resp = lambda_handler(bad, None)
    assert resp["statusCode"] == 400
    assert resp["cookies"][0].startswith("lr_uid=")
    resp2 = lambda_handler(apigw_event("POST", "/api/suggest", body={"text": "  "}), None)
    assert resp2["statusCode"] == 400
    assert resp2["cookies"][0].startswith("lr_uid=")


def test_allow_admin_ignored_inside_lambda(fresh_table, monkeypatch):
    from app.handler import is_admin
    monkeypatch.setenv("ALLOW_ADMIN", "1")
    assert is_admin(apigw_event("GET", "/api/admin/suggestions")) is True
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "lr-api")
    assert is_admin(apigw_event("GET", "/api/admin/suggestions")) is False


def test_items_includes_categories_and_crosstabs(fresh_table):
    db.create_item("bbq", "מנגל", "🍖", category="food")
    resp, body = call(apigw_event("GET", "/api/items"))
    assert resp["statusCode"] == 200
    assert body["items"][0]["category"] == "food"
    assert body["items"][0]["xt_right_left"] == 0
    assert {"slug": "food", "label": "אוכל"} in body["categories"]
    assert len(body["categories"]) == 13


def test_me_reports_affiliation(fresh_table):
    resp, body = call(apigw_event("GET", "/api/me"))
    assert body["affiliation"] is None
    uid_cookie = resp["cookies"][0].split(";")[0]
    call(apigw_event("POST", "/api/affiliation", cookies=[uid_cookie], body={"choice": "left"}))
    _, body2 = call(apigw_event("GET", "/api/me", cookies=[uid_cookie]))
    assert body2["affiliation"] == "left"


def test_affiliation_post_returns_stats_and_sets_cookie(fresh_table):
    resp, body = call(apigw_event("POST", "/api/affiliation", body={"choice": "center"}))
    assert resp["statusCode"] == 200
    assert body["affiliation"] == "center"
    assert body["stats"] == {"right": 0, "left": 0, "center": 1}
    assert resp["cookies"][0].startswith("lr_uid=")
    assert resp["headers"]["cache-control"] == "no-store"


def test_affiliation_second_answer_409(fresh_table):
    resp, _ = call(apigw_event("POST", "/api/affiliation", body={"choice": "right"}))
    uid_cookie = resp["cookies"][0].split(";")[0]
    resp2, body2 = call(apigw_event("POST", "/api/affiliation", cookies=[uid_cookie],
                                    body={"choice": "left"}))
    assert resp2["statusCode"] == 409 and body2["error"] == "already_answered"


def test_affiliation_bad_input_400(fresh_table):
    for bad in ({"choice": "centrist"}, {"choice": ["left"]}, {}):
        resp, body = call(apigw_event("POST", "/api/affiliation", body=bad))
        assert resp["statusCode"] == 400 and body["error"] == "bad_choice"
        assert resp["cookies"][0].startswith("lr_uid=")


def test_vote_after_affiliation_feeds_crosstab_through_api(fresh_table):
    db.create_item("bbq", "მნგל", "🍖", category="food")
    resp, _ = call(apigw_event("POST", "/api/affiliation", body={"choice": "right"}))
    uid_cookie = resp["cookies"][0].split(";")[0]
    _, body = call(apigw_event("POST", "/api/vote", cookies=[uid_cookie],
                               body={"item_id": "bbq", "choice": "left"}))
    assert body["item"]["xt_right_left"] == 1
