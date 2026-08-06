import os
import re

import boto3
from botocore.exceptions import ClientError

from app import db, http

_SLUG = re.compile(r"^[a-z0-9-]{1,64}$")


def _presign(image_key):
    bucket = os.environ.get("IMG_BUCKET")
    if not bucket:
        return None
    s3 = boto3.client("s3")
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": image_key, "ContentType": "image/webp"},
        ExpiresIn=300,
    )


def list_pending(event):
    return http.response(200, {"suggestions": db.list_suggestions("pending")})


def approve(event, sid):
    body = http.read_json(event) or {}
    item_id, name = body.get("item_id"), body.get("name")
    if not (isinstance(item_id, str) and _SLUG.match(item_id) and name):
        return http.response(400, {"error": "bad_request"})
    try:
        db.set_suggestion_status(sid, "approved")
    except db.NotFound:
        return http.response(404, {"error": "unknown_suggestion"})
    try:
        db.create_item(item_id, name, body.get("emoji", ""))
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return http.response(409, {"error": "item_exists"})
        raise
    return http.response(200, {"ok": True})


def reject(event, sid):
    try:
        db.set_suggestion_status(sid, "rejected")
    except db.NotFound:
        return http.response(404, {"error": "unknown_suggestion"})
    return http.response(200, {"ok": True})


def create_item(event):
    body = http.read_json(event) or {}
    item_id, name = body.get("item_id"), body.get("name")
    if not (isinstance(item_id, str) and _SLUG.match(item_id) and name):
        return http.response(400, {"error": "bad_request"})
    image_key = f"img/{item_id}.webp" if body.get("want_image") else None
    try:
        db.create_item(item_id, name, body.get("emoji", ""), image_key=image_key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return http.response(409, {"error": "item_exists"})
        raise
    return http.response(200, {"ok": True, "image_key": image_key,
                               "upload_url": _presign(image_key) if image_key else None})


def patch_item(event, item_id):
    body = http.read_json(event) or {}
    fields = {k: v for k, v in body.items()
              if k in {"name", "emoji", "status", "image_key"}}
    if not fields or ("status" in fields and fields["status"] not in {"active", "archived"}):
        return http.response(400, {"error": "bad_request"})
    try:
        db.update_item(item_id, **fields)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return http.response(404, {"error": "unknown_item"})
        raise
    return http.response(200, {"ok": True})


def dispatch(event, method, path, authorized):
    if not authorized:
        return http.response(401, {"error": "unauthorized"})
    parts = path.split("/")  # ['', 'api', 'admin', ...]
    if (method, path) == ("GET", "/api/admin/suggestions"):
        return list_pending(event)
    if method == "POST" and len(parts) == 6 and parts[3] == "suggestions":
        if parts[5] == "approve":
            return approve(event, parts[4])
        if parts[5] == "reject":
            return reject(event, parts[4])
    if (method, path) == ("POST", "/api/admin/items"):
        return create_item(event)
    if method == "PATCH" and len(parts) == 5 and parts[3] == "items":
        return patch_item(event, parts[4])
    return http.response(404, {"error": "not_found"})
