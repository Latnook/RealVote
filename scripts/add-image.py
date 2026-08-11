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
import csv
import json
import os
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
# Wikimedia's robot policy (https://w.wiki/4wJS) wants a real user-agent naming the tool
# and a way to contact whoever runs it. Override with LR_USER_AGENT if you prefer.
USER_AGENT = os.environ.get(
    "LR_USER_AGENT",
    "lr-add-image/1.0 (+https://latnook.com; item pictures for a Hebrew polling site)",
)
DELAY = float(os.environ.get("LR_FETCH_DELAY", "1.0"))   # polite pause between downloads
RETRIES = 4
BACKOFF = 5.0                                            # seconds, doubled per retry
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".avif", ".svg"}


_fetched = [0]   # remote downloads so far, for spacing requests


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

    # Python's stdlib XML parser is not hardened against XXE (external entity) or
    # billion-laughs (recursive entity expansion). Both need an ENTITY declaration, which
    # can only appear in a DOCTYPE's internal subset — so reject those, and drop the plain
    # `<!DOCTYPE svg PUBLIC ...>` that Illustrator and Inkscape emit, which is harmless and
    # would be discarded on re-serialisation anyway.
    raw = src.read_bytes()
    if b"<!ENTITY" in raw.upper():
        raise ValueError("SVG declares an ENTITY — refused (entity-expansion risk)")
    doctype = re.search(rb"<!DOCTYPE[^>\[]*(\[.*?\])?\s*>", raw, re.I | re.S)
    if doctype and doctype.group(1):
        raise ValueError("SVG has a DOCTYPE internal subset — refused (entity-expansion risk)")
    if doctype:
        raw = raw[:doctype.start()] + raw[doctype.end():]

    try:
        tree = ET.ElementTree(ET.fromstring(raw))
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



PLATE = (242, 243, 245)          # --ink #F2F3F5, the light plate behind logo artwork
PLATE_BOX = (1200, 800)          # 3:2, so object-fit:cover never crops a plated image
PLATE_PAD = 0.82                 # artwork occupies this much of the plate
BACKUP = IMG_DIR / ".replate-backup.json"


def looks_like_logo(path):
    """Artwork-on-a-background rather than a scene: transparent, or a flat uniform border.

    Photos want the full-bleed dark treatment; logos and wordmarks get cropped by it
    (רולדין rendered as "OLAI") or vanish into the card when the artwork is dark.
    """
    from PIL import Image
    if path.suffix.lower() == ".svg":
        return True, "svg"
    im = Image.open(path)
    if im.mode in ("RGBA", "LA") or "transparency" in im.info:
        a = list(im.convert("RGBA").getchannel("A").getdata())
        if sum(1 for v in a if v < 250) / len(a) > 0.05:
            return True, "transparent"
    rgb = im.convert("RGB"); w, h = rgb.size
    step_x, step_y = max(1, w // 60), max(1, h // 60)
    edge = ([rgb.getpixel((x, 0)) for x in range(0, w, step_x)]
            + [rgb.getpixel((x, h - 1)) for x in range(0, w, step_x)]
            + [rgb.getpixel((0, y)) for y in range(0, h, step_y)]
            + [rgb.getpixel((w - 1, y)) for y in range(0, h, step_y)])
    mean = tuple(sum(c) / len(c) for c in zip(*edge))
    flat = sum(max(abs(px[i] - mean[i]) for i in range(3)) for px in edge) / len(edge) < 12
    plain = min(mean) > 225 or max(mean) < 32
    return (flat and plain), ("flat-bg" if (flat and plain) else "photo")


def plate_raster(src, dest):
    from PIL import Image
    im = Image.open(src).convert("RGBA")
    canvas = Image.new("RGB", PLATE_BOX, PLATE)
    s = min(PLATE_BOX[0] / im.width, PLATE_BOX[1] / im.height) * PLATE_PAD
    r = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    canvas.paste(r, ((PLATE_BOX[0] - r.width) // 2, (PLATE_BOX[1] - r.height) // 2), r)
    canvas.save(dest, "WEBP", quality=QUALITY)


def plate_svg(src, dest):
    """Nest the artwork inside a 3:2 outer SVG with a light background — stays vector."""
    root = ET.fromstring(src.read_bytes())
    vb = root.get("viewBox")
    if vb:
        nums = [float(x) for x in vb.replace(",", " ").split()]
        vw, vh = nums[2], nums[3]
    else:
        num = lambda v: float(re.sub(r"[^0-9.]", "", v or "") or 100)
        vw, vh = num(root.get("width")), num(root.get("height"))
        root.set("viewBox", f"0 0 {vw} {vh}")
    W, H = 300, 200
    pad = (1 - PLATE_PAD) / 2
    inner_w, inner_h = W * PLATE_PAD, H * PLATE_PAD
    root.set("x", str(W * pad)); root.set("y", str(H * pad))
    root.set("width", str(inner_w)); root.set("height", str(inner_h))
    root.set("preserveAspectRatio", "xMidYMid meet")
    NS = "http://www.w3.org/2000/svg"
    outer = ET.Element(f"{{{NS}}}svg", {"viewBox": f"0 0 {W} {H}",
                                        "width": str(W), "height": str(H)})
    ET.SubElement(outer, f"{{{NS}}}rect", {"width": str(W), "height": str(H),
                                           "fill": "#%02X%02X%02X" % PLATE})
    outer.append(root)
    ET.register_namespace("", NS)
    ET.ElementTree(outer).write(dest, encoding="utf-8", xml_declaration=True)


def fetch(url, tmpdir):
    """Download a remote image to a temp file. Never referenced remotely at serve time.

    Wikimedia — where most of these images live — enforces a robot policy: a generic
    user-agent and back-to-back requests earn an immediate 429. So we identify the tool
    properly, pause between downloads, and back off when asked to.
    """
    last = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, headers={
            "user-agent": USER_AGENT,
            "accept": "image/*,*/*;q=0.8",
        })
        try:
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
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 503) or attempt == RETRIES - 1:
                raise
            wait = float(e.headers.get("retry-after") or 0) or BACKOFF * (2 ** attempt)
            print(f"      rate-limited, waiting {wait:.0f}s and retrying…")
            time.sleep(wait)
    raise last


def attach(base, items, item_id, src, tmpdir=None):
    if item_id not in items:
        print(f"  ✗ {item_id}: no such item")
        return False
    source_url = None
    if isinstance(src, str) and src.startswith(("http://", "https://")):
        source_url = src   # captured before src gets reassigned to the downloaded temp path
        if _fetched[0]:
            time.sleep(DELAY)   # rate-limit ourselves, not just react to 429s
        _fetched[0] += 1
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
    patch_body = {"image_key": key}
    if source_url:
        patch_body["image_source"] = source_url
    status, _ = api(base, f"/api/admin/items/{item_id}", "PATCH", patch_body)
    if status != 200:
        dest.unlink(missing_ok=True)     # don't leave an orphan the item doesn't reference
        print(f"  ✗ {item_id}: PATCH returned {status}")
        return False
    kb = dest.stat().st_size // 1024
    print(f"  ✓ {item_id}: {src.name} → {key} ({kb} KB)")
    return True



def replate(base, items):
    """Re-render logo-like images onto a light plate. Reversible via --unplate."""
    backup = json.loads(BACKUP.read_text()) if BACKUP.exists() else {}
    done = skipped = 0
    for iid, item in sorted(items.items()):
        key = item.get("image_key")
        if not key:
            continue
        src = ROOT / "site" / key
        if not src.is_file():
            print(f"  ? {iid}: {key} missing on disk, skipped")
            continue
        logo, why = looks_like_logo(src)
        if not logo:
            skipped += 1
            continue
        ext = "svg" if src.suffix.lower() == ".svg" else "webp"
        new_key = f"img/{iid}-plated-{int(time.time())}.{ext}"
        dest = ROOT / "site" / new_key
        try:
            (plate_svg if ext == "svg" else plate_raster)(src, dest)
        except Exception as e:
            print(f"  x {iid}: plating failed — {e}")
            continue
        status, _ = api(base, f"/api/admin/items/{iid}", "PATCH", {"image_key": new_key})
        if status != 200:
            dest.unlink(missing_ok=True)
            print(f"  x {iid}: PATCH returned {status}")
            continue
        backup.setdefault(iid, key)      # remember the ORIGINAL, not an intermediate
        print(f"  + {iid}: plated ({why})")
        done += 1
    BACKUP.write_text(json.dumps(backup, indent=2))
    print(f"\nplated {done}, left {skipped} photo(s) full-bleed")
    print(f"revert any time with:  ./scripts/add-image.py --unplate")


def unplate(base, items):
    if not BACKUP.exists():
        sys.exit("nothing to revert — no backup file")
    backup = json.loads(BACKUP.read_text())
    n = 0
    for iid, old_key in backup.items():
        if iid not in items:
            continue
        status, _ = api(base, f"/api/admin/items/{iid}", "PATCH", {"image_key": old_key})
        if status == 200:
            print(f"  - {iid}: back to {old_key}")
            n += 1
        else:
            print(f"  x {iid}: PATCH returned {status}")
    BACKUP.unlink()
    print(f"\nreverted {n} item(s) to their original images")



def relink(base, items):
    """Re-point items at images already on disk.

    DynamoDB Local keeps everything in memory, so stopping the container loses every
    image_key while site/img/ still holds the files. Filenames start with the item id,
    so the link can be rebuilt without re-downloading anything.
    """
    best = {}
    for f in sorted(IMG_DIR.glob("*")):
        if f.name.startswith("."):
            continue
        m = re.match(r"(.+?)-(?:plated-)?(\d{10})\.(webp|svg)$", f.name)
        if not m:
            continue
        iid, ts, _ = m.groups()
        if iid in items and (iid not in best or ts > best[iid][0]):
            best[iid] = (ts, f"img/{f.name}")
    n = 0
    for iid, (_, key) in sorted(best.items()):
        if items[iid].get("image_key") == key:
            continue
        status, _ = api(base, f"/api/admin/items/{iid}", "PATCH", {"image_key": key})
        n += status == 200
    print(f"relinked {n} item(s) to images already on disk ({len(best)} matched)")


CSV_FIELDS = ["id", "name", "category", "emoji", "current_image", "image_url", "notes"]


def make_csv(path, items):
    """A fill-in-the-blanks sheet: one row per item, image_url left empty.

    Written UTF-8 with a BOM so Excel renders the Hebrew instead of mojibake;
    LibreOffice and the reader below are both happy either way.
    """
    rows = sorted(items.values(), key=lambda i: (i["category"], i["id"]))
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for i in rows:
            w.writerow({
                "id": i["id"],
                "name": i["name"],
                "category": i["category"],
                "emoji": i.get("emoji", ""),
                "current_image": i.get("image_key", ""),
                "image_url": "",
                "notes": "",
            })
    print(f"wrote {path} — {len(rows)} rows")
    print("Fill the image_url column (a URL or a local file path) and run:")
    print(f"  ./scripts/add-image.py --from-csv {path}")


def read_csv(path, items):
    """Return [(item_id, source)] for rows with a non-empty image_url."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "id" not in reader.fieldnames or "image_url" not in reader.fieldnames:
            sys.exit(f"{path}: needs at least 'id' and 'image_url' columns "
                     f"(found: {reader.fieldnames})")
        pairs, unknown, blank = [], [], 0
        for lineno, row in enumerate(reader, 2):
            iid = (row.get("id") or "").strip()
            src = (row.get("image_url") or "").strip()
            if not iid:
                continue
            if not src:
                blank += 1
                continue
            if iid not in items:
                unknown.append(f"line {lineno}: {iid}")
                continue
            pairs.append((iid, src))
    if unknown:
        print(f"skipping {len(unknown)} row(s) with an unknown item id:")
        for u in unknown[:10]:
            print(f"  {u}")
    if blank:
        print(f"{blank} row(s) have no image_url yet — left alone")
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("item_id", nargs="?", help="item id to attach the picture to")
    # Left as a plain string: pathlib.Path("https://x/y") collapses the double slash to
    # "https:/", so attach()'s URL branch never fires and a perfectly good URL is reported
    # as a missing file. attach() does its own Path() once it knows the source is local.
    ap.add_argument("image", nargs="?", help="source image file or URL")
    ap.add_argument("--batch", type=pathlib.Path, metavar="DIR",
                    help="attach every file in DIR whose name matches an item id")
    ap.add_argument("--from-list", type=pathlib.Path, metavar="FILE",
                    help="lines of 'item-id  source', source = file path or URL")
    ap.add_argument("--make-csv", type=pathlib.Path, metavar="FILE",
                    help="write a spreadsheet of every item with a blank image_url column")
    ap.add_argument("--from-csv", type=pathlib.Path, metavar="FILE",
                    help="attach images listed in the image_url column of that spreadsheet")
    ap.add_argument("--missing", action="store_true", help="list items with no picture and exit")
    ap.add_argument("--replate", action="store_true",
                    help="render logo-like images onto a light plate (reversible)")
    ap.add_argument("--unplate", action="store_true",
                    help="undo --replate, restoring the original images")
    ap.add_argument("--relink", action="store_true",
                    help="re-point items at images already in site/img/ (after a DB reset)")
    ap.add_argument("--only-missing", action="store_true",
                    help="skip items that already have a picture (handy when retrying failures)")
    ap.add_argument("--base", default="http://localhost:8080", help="local server base URL")
    args = ap.parse_args()

    items = load_items(args.base)

    if args.make_csv:
        make_csv(args.make_csv, items)
        return

    if args.relink:
        relink(args.base, items)
        return

    if args.replate:
        replate(args.base, items)
        return

    if args.unplate:
        unplate(args.base, items)
        return

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

        if args.from_csv:
            pairs = read_csv(args.from_csv, items)
            if args.only_missing:
                before = len(pairs)
                pairs = [(i, s) for i, s in pairs if not items[i].get("image_key")]
                if before - len(pairs):
                    print(f"skipping {before - len(pairs)} item(s) that already have a picture")
            if not pairs:
                print("nothing to attach — no rows have an image_url filled in")
                return
            print(f"\nattaching {len(pairs)} image(s):")
            ok = sum(attach(args.base, items, iid, src, tmp) for iid, src in pairs)
            print(f"\nattached {ok}/{len(pairs)}")
            if ok < len(pairs):
                print("re-run after fixing the failures above; successful rows are safe to re-run too")
            return

        if not args.item_id or not args.image:
            ap.error("give an item id and an image, or use "
                     "--make-csv / --from-csv / --batch / --from-list / --missing")
        attach(args.base, items, args.item_id, args.image, tmp)


if __name__ == "__main__":
    main()
