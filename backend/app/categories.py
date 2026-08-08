"""Canonical category list. Single source of truth — the frontend renders whatever this serves."""

CATEGORIES = [
    {"slug": "events", "label": "אירועים"},
    {"slug": "travel", "label": "חופשות וטיולים"},
    {"slug": "food", "label": "אוכל"},
    {"slug": "home", "label": "בית"},
    {"slug": "consumer", "label": "צרכנות"},
    {"slug": "social", "label": "חברתי"},
    {"slug": "sport", "label": "ספורט"},
    {"slug": "games", "label": "משחקים"},
    {"slug": "movies", "label": "סרטים"},
    {"slug": "tv", "label": "תוכניות טלוויזיה"},
    {"slug": "conspiracy", "label": "תיאוריות קונספירציה"},
    {"slug": "other", "label": "אחר"},
]

SLUGS = {c["slug"] for c in CATEGORIES}
DEFAULT = "other"


def is_valid(slug):
    return isinstance(slug, str) and slug in SLUGS
