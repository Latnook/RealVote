import json

from app import http
from conftest import apigw_event


def test_get_cookie():
    e = apigw_event("GET", "/api/me", cookies=["a=1", "lr_uid=abc123"])
    assert http.get_cookie(e, "lr_uid") == "abc123"
    assert http.get_cookie(e, "missing") is None


def test_uid_set_cookie_attributes():
    c = http.uid_set_cookie("abc")
    assert c.startswith("lr_uid=abc;")
    for part in ("Max-Age=31536000", "Path=/", "Secure", "HttpOnly", "SameSite=Lax"):
        assert part in c


def test_read_json_valid_invalid_and_base64():
    import base64
    assert http.read_json(apigw_event("POST", "/x", body={"a": 1})) == {"a": 1}
    bad = apigw_event("POST", "/x")
    bad["body"] = "{not json"
    assert http.read_json(bad) is None
    b64 = apigw_event("POST", "/x")
    b64["body"] = base64.b64encode(b'{"b":2}').decode()
    b64["isBase64Encoded"] = True
    assert http.read_json(b64) == {"b": 2}


def test_response_defaults_and_hebrew():
    r = http.response(200, {"name": "שמאלני"})
    assert r["statusCode"] == 200
    assert r["headers"]["cache-control"] == "no-store"
    assert "שמאלני" in r["body"]  # not \u escaped


def test_response_cache_and_cookies():
    r = http.response(200, {}, cookies=["lr_uid=x; Path=/"], cache="public, max-age=30")
    assert r["headers"]["cache-control"] == "public, max-age=30"
    assert r["cookies"] == ["lr_uid=x; Path=/"]
