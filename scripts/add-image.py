#!/usr/bin/env python3
"""Attach pictures to items while developing locally.

In production the admin page uploads straight to S3 via a presigned URL. Locally there is
no bucket, so this does the same job against the filesystem: convert to WebP, drop it in
site/img/ (which the local server already serves), and point the item at it through the
same admin API the UI uses.

The local server must be running (./scripts/local-dev.sh) — this talks to its API rather
than to DynamoDB directly, so item validation and the PATCH behave exactly as in the UI.

    # one item, from a file
    ./scripts/add-image.py borekas ~/Pictures/borekas.jpg

    # one item, from a URL — fetched once and stored in our own bucket, never hotlinked
    ./scripts/add-image.py borekas https://example.com/borekas.jpg

    # a whole folder: each file's NAME (minus extension) must match an item id,
    # e.g. borekas.jpg, chess.png, goldstar-beer.webp
    ./scripts/add-image.py --batch ~/Pictures/lr-items/

    # a list file: one "item-id  source" pair per line, source = path or URL,
    # '#' starts a comment
    ./scripts/add-image.py --from-list images.txt

    # see which items still have no picture
    ./scripts/add-image.py --missing

Why URLs are downloaded rather than referenced: remote links expire, and tracker
blockers drop requests to social/CDN hosts outright, so a hotlinked picture is
invisible to many visitors while curl fetches it happily. Storing a copy keeps every
image on one origin with one cache policy.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "site" / "img"
MAX_DIM = 1200          # matches the browser-side resize in site/admin/admin.js
QUALITY = 85
MAX_BYTES = 25 * 1024 * 1024   # refuse absurd downloads before converting
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".avif", ".svg"}


def api(base, path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{base}{path}", data=data, method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except urllib.error.URLError as e:
        sys.exit(f"cannot reach {base} ({e.reason}). Is ./scripts/local-dev.sh running?")


def load_items(base):
    status, body = api(base, "/api/admin/items")
    if status != 200:
        sys.exit(f"admin API returned {status} — is the server running with ALLOW_ADMIN=1?")
    return {i["id"]: i for i in body["items"]}


def convert(src, dest):
    """Resize-to-fit and encode as WebP. '>' means never upscale a small original."""
    subprocess.run(
        ["magick", str(src), "-auto-orient", "-resize", f"{MAX_DIM}x{MAX_DIM}>",
         "-quality", str(QUALITY), str(dest)],
        check=True, capture_output=True,
    )


def sanitize_svg(src, dest):
    """Copy an SVG through, stripping anything that could execute.

    SVG is a document format, not just a picture: it can carry <script>, on* handlers and
    external references. Rendered through <img> a browser won't run any of that — but a
    visitor who opens the file's URL directly gets a document on our own origin, where it
    would. Only the admin can add images, so this is defence in depth rather than a hole
    being plugged; it also fails closed, rejecting anything that won't parse.
    """
    BAD_TAGS = {"script", "foreignObject", "handler", "animate", "set", "audio", "video", "iframe"}

    # Reject entity declarations before parsing. Python's stdlib XML parser is not hardened
    # against XXE (external entity) or billion-laughs (recursive entity expansion) attacks —
    # and BOTH require a DOCTYPE/ENTITY declaration to work at all. Icon and logo SVGs never
    # need one, so refusing them removes the entire attack class without a dependency.
    head = src.read_bytes()[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("SVG declares a DOCTYPE/ENTITY — refused (entity-expansion risk)")

    try:
        tree = ET.parse(src)
    except ET.ParseError as e:
        raise ValueError(f"unparseable SVG ({e})")
    root = tree.getroot()
    if not root.tag.endswith("svg"):
        raise ValueError("not an SVG root element")

    def strip(el):
        for child in list(el):
            tag = child.tag.rsplit("}", 1)[-1]
            if tag in BAD_TAGS:
                el.remove(child)
                continue
            strip(child)
        for attr in list(el.attrib):
            name = attr.rsplit("}", 1)[-1].lower()
            value = el.attrib[attr]
            # event handlers, javascript: payloads, and off-origin references
            if name.startswith("on") or re.match(r"\s*javascript:", value, re.I):
                del el.attrib[attr]
            elif name in ("href", "xlink:href") and re.match(r"\s*(https?:)?//", value, re.I):
                del el.attrib[attr]

    strip(root)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    tree.write(dest, encoding="utf-8", xml_declaration=True)


def fetch(url, tmpdir):
    """Download a remote image to a temp file. Never referenced remotely at serve time."""
    req = urllib.request.Request(url, headers={"user-agent": "lr-add-image/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
        if ctype and not ctype.startswith("image/"):
            raise ValueError(f"not an image (content-type: {ctype})")
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"larger than {MAX_BYTES // 1024 // 1024} MB")
    dest = tmpdir / "download"
    dest.write_bytes(data)
    return dest


def attach(base, items, item_id, src, tmpdir=None):
    if item_id not in items:
        print(f"  ✗ {item_id}: no such item")
        return False
    if isinstance(src, str) and src.startswith(("http://", "https://")):
        try:
            src = fetch(src, tmpdir)
        except (urllib.error.URLError, ValueError, OSError) as e:
            print(f"  ✗ {item_id}: download failed — {e}")
            return False
    src = pathlib.Path(src)
    if not src.is_file():
        print(f"  ✗ {item_id}: no such file — {src}")
        return False
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    # SVG is kept as SVG — rasterising vector artwork to WebP throws away the whole point.
    is_svg = src.suffix.lower() == ".svg" or src.read_bytes()[:512].lstrip()[:5].lower().startswith(b"<svg") \
        or b"<svg" in src.read_bytes()[:512].lower()
    ext = "svg" if is_svg else "webp"
    key = f"img/{item_id}-{int(time.time())}.{ext}"   # timestamped, like production
    dest = ROOT / "site" / key
    try:
        if is_svg:
            sanitize_svg(src, dest)
        else:
            convert(src, dest)
    except subprocess.CalledProcessError as e:
        print(f"  ✗ {item_id}: convert failed — {e.stderr.decode(errors='replace').strip()[:120]}")
        return False
    except ValueError as e:
        print(f"  ✗ {item_id}: {e}")
        return False
    status, _ = api(base, f"/api/admin/items/{item_id}", "PATCH", {"image_key": key})
    if status != 200:
        dest.unlink(missing_ok=True)     # don't leave an orphan the item doesn't reference
        print(f"  ✗ {item_id}: PATCH returned {status}")
        return False
    kb = dest.stat().st_size // 1024
    print(f"  ✓ {item_id}: {src.name} → {key} ({kb} KB)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("item_id", nargs="?", help="item id to attach the picture to")
    ap.add_argument("image", nargs="?", type=pathlib.Path, help="source image file")
    ap.add_argument("--batch", type=pathlib.Path, metavar="DIR",
                    help="attach every file in DIR whose name matches an item id")
    ap.add_argument("--from-list", type=pathlib.Path, metavar="FILE",
                    help="lines of 'item-id  source', source = file path or URL")
    ap.add_argument("--missing", action="store_true", help="list items with no picture and exit")
    ap.add_argument("--base", default="http://localhost:8080", help="local server base URL")
    args = ap.parse_args()

    items = load_items(args.base)

    if args.missing:
        gaps = [i for i in items.values() if not i.get("image_key") and i["status"] == "active"]
        print(f"{len(gaps)} of {len(items)} items have no picture:")
        for i in sorted(gaps, key=lambda x: (x["category"], x["id"])):
            print(f"  {i['category']:11} {i['id']:24} {i['name']}")
        return

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)

        if args.batch:
            files = sorted(f for f in args.batch.iterdir() if f.suffix.lower() in SUFFIXES)
            if not files:
                sys.exit(f"no images found in {args.batch}")
            print(f"{len(files)} image(s) in {args.batch}:")
            ok = sum(attach(args.base, items, f.stem, f, tmp) for f in files)
            print(f"\nattached {ok}/{len(files)}")
            unmatched = [f.stem for f in files if f.stem not in items]
            if unmatched:
                print("unmatched filenames (rename them to an item id):", ", ".join(unmatched))
            return

        if args.from_list:
            pairs = []
            for lineno, raw in enumerate(args.from_list.read_text(encoding="utf-8").splitlines(), 1):
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    print(f"  ✗ line {lineno}: expected 'item-id  source' — {raw.strip()!r}")
                    continue
                pairs.append((parts[0], parts[1].strip()))
            if not pairs:
                sys.exit(f"no usable lines in {args.from_list}")
            print(f"{len(pairs)} entr(ies) in {args.from_list}:")
            ok = sum(attach(args.base, items, iid, src, tmp) for iid, src in pairs)
            print(f"\nattached {ok}/{len(pairs)}")
            return

        if not args.item_id or not args.image:
            ap.error("give an item id and an image, or use --batch / --from-list / --missing")
        attach(args.base, items, args.item_id, args.image, tmp)


if __name__ == "__main__":
    main()
