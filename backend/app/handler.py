import os
import re
import traceback

from app import categories, db, http

_UID_RE = re.compile(r"^[0-9a-f]{32}$")


def is_admin(event):
    if os.environ.get("ALLOW_ADMIN") == "1" and not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return True
    return "jwt" in (event.get("requestContext", {}).get("authorizer") or {})


def _uid(event):
    """Returns (uid, new_cookie_or_None)."""
    uid = http.get_cookie(event, "lr_uid")
    if uid and _UID_RE.match(uid):
        return uid, None
    uid = http.new_uid()
    return uid, http.uid_set_cookie(uid)


def get_items(event):
    return http.response(
        200,
        {"items": db.list_active_items(), "categories": categories.CATEGORIES},
        cache="public, max-age=30",
    )


def get_me(event):
    uid, cookie = _uid(event)
    votes = {} if cookie else db.get_user_votes(uid)
    affiliation = None if cookie else db.get_affiliation(uid)
    return http.response(
        200,
        {"votes": votes, "affiliation": affiliation},
        cookies=[cookie] if cookie else None,
    )


def post_vote(event):
    uid, cookie = _uid(event)
    cookies = [cookie] if cookie else None
    body = http.read_json(event)
    if body is None or not isinstance(body.get("item_id"), str):
        return http.response(400, {"error": "bad_request"}, cookies=cookies)
    choice = body.get("choice")
    if not isinstance(choice, str) or choice not in db.CHOICES:
        return http.response(400, {"error": "bad_choice"}, cookies=cookies)
    try:
        item = db.record_vote(uid, body["item_id"], body.get("choice"))
    except db.NotFound:
        return http.response(404, {"error": "unknown_item"}, cookies=cookies)
    except db.AlreadyVoted:
        return http.response(409, {"error": "already_voted"}, cookies=cookies)
    return http.response(200, {"item": item, "your_choice": body["choice"]},
                         cookies=cookies)


def post_suggest(event):
    uid, cookie = _uid(event)
    cookies = [cookie] if cookie else None
    body = http.read_json(event)
    text = (body or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        return http.response(400, {"error": "empty_text"}, cookies=cookies)
    try:
        db.add_suggestion(uid, text)
    except db.RateLimited:
        return http.response(429, {"error": "rate_limited"}, cookies=cookies)
    return http.response(202, {"ok": True}, cookies=cookies)


def post_affiliation(event):
    uid, cookie = _uid(event)
    cookies = [cookie] if cookie else None
    body = http.read_json(event) or {}
    choice = body.get("choice")
    if not isinstance(choice, str) or choice not in db.AFFILIATIONS:
        return http.response(400, {"error": "bad_choice"}, cookies=cookies)
    try:
        stats = db.set_affiliation(uid, choice)
    except db.AlreadyVoted:
        return http.response(409, {"error": "already_answered"}, cookies=cookies)
    return http.response(200, {"affiliation": choice, "stats": stats}, cookies=cookies)


PUBLIC_ROUTES = {
    ("GET", "/api/items"): get_items,
    ("GET", "/api/me"): get_me,
    ("POST", "/api/vote"): post_vote,
    ("POST", "/api/suggest"): post_suggest,
    ("POST", "/api/affiliation"): post_affiliation,
}


def _route(event):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"].rstrip("/") or "/"
    route = PUBLIC_ROUTES.get((method, path))
    if route:
        return route(event)
    if path.startswith("/api/admin/"):
        from app import admin_routes  # imported lazily; added in Task 7
        return admin_routes.dispatch(event, method, path, is_admin(event))
    return http.response(404, {"error": "not_found"})


def lambda_handler(event, context):
    try:
        return _route(event)
    except Exception:
        traceback.print_exc()  # goes to CloudWatch
        return http.response(500, {"error": "internal"})
