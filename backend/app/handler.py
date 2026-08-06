import os

from app import db, http


def is_admin(event):
    if os.environ.get("ALLOW_ADMIN") == "1":
        return True
    return "jwt" in (event.get("requestContext", {}).get("authorizer") or {})


def _uid(event):
    """Returns (uid, new_cookie_or_None)."""
    uid = http.get_cookie(event, "lr_uid")
    if uid:
        return uid, None
    uid = http.new_uid()
    return uid, http.uid_set_cookie(uid)


def get_items(event):
    return http.response(200, {"items": db.list_active_items()},
                         cache="public, max-age=30")


def get_me(event):
    uid, cookie = _uid(event)
    votes = {} if cookie else db.get_user_votes(uid)
    return http.response(200, {"votes": votes},
                         cookies=[cookie] if cookie else None)


def post_vote(event):
    body = http.read_json(event)
    if body is None or not isinstance(body.get("item_id"), str):
        return http.response(400, {"error": "bad_request"})
    uid, cookie = _uid(event)
    cookies = [cookie] if cookie else None
    try:
        item = db.record_vote(uid, body["item_id"], body.get("choice"))
    except KeyError:
        return http.response(400, {"error": "bad_choice"}, cookies=cookies)
    except db.NotFound:
        return http.response(404, {"error": "unknown_item"}, cookies=cookies)
    except db.AlreadyVoted:
        return http.response(409, {"error": "already_voted"}, cookies=cookies)
    return http.response(200, {"item": item, "your_choice": body["choice"]},
                         cookies=cookies)


def post_suggest(event):
    body = http.read_json(event)
    text = (body or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        return http.response(400, {"error": "empty_text"})
    uid, cookie = _uid(event)
    cookies = [cookie] if cookie else None
    try:
        db.add_suggestion(uid, text)
    except db.RateLimited:
        return http.response(429, {"error": "rate_limited"}, cookies=cookies)
    return http.response(202, {"ok": True}, cookies=cookies)


PUBLIC_ROUTES = {
    ("GET", "/api/items"): get_items,
    ("GET", "/api/me"): get_me,
    ("POST", "/api/vote"): post_vote,
    ("POST", "/api/suggest"): post_suggest,
}


def lambda_handler(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"].rstrip("/") or "/"
    route = PUBLIC_ROUTES.get((method, path))
    if route:
        return route(event)
    if path.startswith("/api/admin/"):
        from app import admin_routes  # imported lazily; added in Task 7
        return admin_routes.dispatch(event, method, path, is_admin(event))
    return http.response(404, {"error": "not_found"})
