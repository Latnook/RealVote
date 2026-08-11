import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "backfill-image-source.py"


def load():
    """The filename has a hyphen, so it cannot be imported by name."""
    spec = importlib.util.spec_from_file_location("backfill", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plans_only_pictured_items_with_a_source():
    backfill = load()
    rows = [
        {"id": "picanto", "image_url": "https://example.org/picanto.jpg"},
        {"id": "lotr", "image_url": ""},                                  # no source recorded
        {"id": "ghost", "image_url": "https://example.org/ghost.jpg"},    # not in the table
        {"id": "emoji-only", "image_url": "https://example.org/e.jpg"},   # no picture
    ]
    items = {
        "picanto": {"id": "picanto", "image_key": "img/picanto-1.webp"},
        "lotr": {"id": "lotr", "image_key": "img/lotr-1.webp"},
        "emoji-only": {"id": "emoji-only"},
    }
    assert backfill.plan_backfill(rows, items) == [
        ("picanto", "https://example.org/picanto.jpg")
    ]


def test_skips_items_that_already_have_a_source():
    backfill = load()
    rows = [{"id": "done", "image_url": "https://example.org/new.jpg"}]
    items = {"done": {"id": "done", "image_key": "img/done-1.webp",
                      "image_source": "https://example.org/old.jpg"}}
    assert backfill.plan_backfill(rows, items) == []


def test_whitespace_is_stripped():
    backfill = load()
    rows = [{"id": "  picanto  ", "image_url": "  https://example.org/p.jpg  "}]
    items = {"picanto": {"id": "picanto", "image_key": "img/p-1.webp"}}
    assert backfill.plan_backfill(rows, items) == [("picanto", "https://example.org/p.jpg")]
