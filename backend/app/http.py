import base64
import json
import uuid


def get_cookie(event, name):
    for c in event.get("cookies") or []:
        k, _, v = c.partition("=")
        if k == name:
            return v
    return None


def new_uid():
    return uuid.uuid4().hex


def uid_set_cookie(uid):
    return (
        f"lr_uid={uid}; Max-Age=31536000; Path=/; Secure; HttpOnly; SameSite=Lax"
    )


def read_json(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def response(status, body=None, cookies=None, cache=None):
    result = {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": cache or "no-store",
        },
        "body": json.dumps(body if body is not None else {}, ensure_ascii=False),
    }
    if cookies:
        result["cookies"] = cookies
    return result
