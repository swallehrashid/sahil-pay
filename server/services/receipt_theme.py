"""
services/receipt_theme.py — the two colours a landlord's documents are drawn in.

A landlord picks a PRIMARY and a SECONDARY colour once, and every receipt,
statement and report they issue is drawn in them. Two colours rather than a
free-form stylesheet, for the same reason receipt_layout.py is a validated
dictionary: a landlord cannot produce an unreadable document, and how each role
is used can be changed later without breaking anything they saved.

WHAT EACH COLOUR DOES
---------------------
  primary    the ink. Headings, the company name, table-header text, the
             signature rule. Everything a reader has to READ, so the palette
             below only offers colours dark enough to be read on white.
  secondary  the accent. Rules under the letterhead, the line above a total,
             the emphasis on the amount paid. Seen, not read.

Table-header and total-row FILLS are not palette entries — they are the primary
colour tinted towards white by tint() below. Letting someone choose a fill
directly is how you get white text on a yellow band; deriving it means the
contrast is right for all 36 choices without anyone checking 36 combinations.

WHY EVERY COLOUR HERE IS DARK
-----------------------------
These are printed on white paper, often on a cheap office laser, and then
photographed by a tenant. A pastel that looks fine on a backlit screen is
illegible in all three of those places. Every entry is chosen to hold up as
ink — which is why there is no white, no yellow, and no pale tint in the list.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Sahil Pay's own palette, and the default for every account that has never
# opened the screen — so nothing changes for them.
DEFAULT_PRIMARY = "#0f0246"     # brand navy
DEFAULT_SECONDARY = "#200497"   # brand violet

# 36 colours, grouped so the picker can show them in families rather than as an
# undifferentiated grid. Every one is dark enough to read as ink on white.
PALETTE: list[dict] = [
    # --- Blues -------------------------------------------------------------
    {"key": "navy",         "label": "Navy",          "hex": "#0f0246", "family": "Blue"},
    {"key": "violet",       "label": "Violet",        "hex": "#200497", "family": "Blue"},
    {"key": "royal_blue",   "label": "Royal blue",    "hex": "#1d4ed8", "family": "Blue"},
    {"key": "azure",        "label": "Azure",         "hex": "#0369a1", "family": "Blue"},
    {"key": "steel_blue",   "label": "Steel blue",    "hex": "#33608c", "family": "Blue"},
    {"key": "midnight",     "label": "Midnight",      "hex": "#111a3a", "family": "Blue"},
    # --- Teals & greens ----------------------------------------------------
    {"key": "teal",         "label": "Teal",          "hex": "#0f766e", "family": "Green"},
    {"key": "deep_teal",    "label": "Deep teal",     "hex": "#134e4a", "family": "Green"},
    {"key": "emerald",      "label": "Emerald",       "hex": "#047857", "family": "Green"},
    {"key": "forest",       "label": "Forest",        "hex": "#14532d", "family": "Green"},
    {"key": "olive",        "label": "Olive",         "hex": "#4d7c0f", "family": "Green"},
    {"key": "sage",         "label": "Sage",          "hex": "#3f6212", "family": "Green"},
    # --- Reds & pinks ------------------------------------------------------
    {"key": "crimson",      "label": "Crimson",       "hex": "#b91c1c", "family": "Red"},
    {"key": "brick",        "label": "Brick",         "hex": "#9a3412", "family": "Red"},
    {"key": "maroon",       "label": "Maroon",        "hex": "#7f1d1d", "family": "Red"},
    {"key": "rose",         "label": "Rose",          "hex": "#be123c", "family": "Red"},
    {"key": "wine",         "label": "Wine",          "hex": "#881337", "family": "Red"},
    {"key": "coral_deep",   "label": "Deep coral",    "hex": "#c2410c", "family": "Red"},
    # --- Purples -----------------------------------------------------------
    {"key": "purple",       "label": "Purple",        "hex": "#6b21a8", "family": "Purple"},
    {"key": "indigo",       "label": "Indigo",        "hex": "#4338ca", "family": "Purple"},
    {"key": "plum",         "label": "Plum",          "hex": "#701a75", "family": "Purple"},
    {"key": "aubergine",    "label": "Aubergine",     "hex": "#4a044e", "family": "Purple"},
    {"key": "mauve",        "label": "Mauve",         "hex": "#86198f", "family": "Purple"},
    {"key": "grape",        "label": "Grape",         "hex": "#581c87", "family": "Purple"},
    # --- Warm neutrals -----------------------------------------------------
    {"key": "amber_deep",   "label": "Deep amber",    "hex": "#b45309", "family": "Warm"},
    {"key": "bronze",       "label": "Bronze",        "hex": "#92400e", "family": "Warm"},
    {"key": "coffee",       "label": "Coffee",        "hex": "#78350f", "family": "Warm"},
    {"key": "ochre",        "label": "Ochre",         "hex": "#a16207", "family": "Warm"},
    {"key": "sienna",       "label": "Sienna",        "hex": "#7c2d12", "family": "Warm"},
    {"key": "taupe",        "label": "Taupe",         "hex": "#57534e", "family": "Warm"},
    # --- Greys -------------------------------------------------------------
    {"key": "charcoal",     "label": "Charcoal",      "hex": "#1f2937", "family": "Grey"},
    {"key": "graphite",     "label": "Graphite",      "hex": "#374151", "family": "Grey"},
    {"key": "slate",        "label": "Slate",         "hex": "#475569", "family": "Grey"},
    {"key": "gunmetal",     "label": "Gunmetal",      "hex": "#334155", "family": "Grey"},
    {"key": "ink",          "label": "Ink",           "hex": "#0b0b12", "family": "Grey"},
    {"key": "stone",        "label": "Stone",         "hex": "#44403c", "family": "Grey"},
]

BY_HEX = {entry["hex"].lower(): entry for entry in PALETTE}
BY_KEY = {entry["key"]: entry for entry in PALETTE}

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULT_THEME = {"primary": DEFAULT_PRIMARY, "secondary": DEFAULT_SECONDARY}


def _coerce_colour(value, fallback: str) -> str:
    """
    A palette key, a palette hex, or anything else → a usable hex.

    Accepting a key as well as a hex means the stored value stays meaningful if
    a palette entry is ever re-tuned, and means the client can post either.
    Anything not in the palette falls back rather than being honoured: this
    colour is about to be printed on documents a landlord shows to tenants and
    owners, and "#ffff00 on white" is not a choice worth preserving.
    """
    if not value:
        return fallback
    text = str(value).strip()
    if text in BY_KEY:
        return BY_KEY[text]["hex"]
    if _HEX_RE.match(text) and text.lower() in BY_HEX:
        return BY_HEX[text.lower()]["hex"]
    if _HEX_RE.match(text):
        logger.info("receipt theme: %s is not a palette colour — using the default", text)
    return fallback


def normalise(raw) -> dict:
    """Coerce anything into a valid {'primary', 'secondary'} pair."""
    import json

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return dict(DEFAULT_THEME)
    if not isinstance(raw, dict):
        return dict(DEFAULT_THEME)

    primary = _coerce_colour(raw.get("primary"), DEFAULT_PRIMARY)
    secondary = _coerce_colour(raw.get("secondary"), DEFAULT_SECONDARY)

    # Two identical colours means no accent at all — every rule and total
    # disappears into the body text. Fall the secondary back rather than
    # rendering a document with no visible structure.
    if primary.lower() == secondary.lower():
        secondary = DEFAULT_SECONDARY if primary.lower() != DEFAULT_SECONDARY else DEFAULT_PRIMARY

    return {"primary": primary, "secondary": secondary}


def resolve(theme=None) -> dict:
    """The colours to draw with — the given theme, or the Sahil Pay default."""
    return normalise(theme) if theme is not None else dict(DEFAULT_THEME)


def for_landlord(landlord) -> dict:
    """The landlord's saved theme, or the default when they've never set one."""
    settings = getattr(landlord, "landlord_settings", None)
    if settings is None:
        return dict(DEFAULT_THEME)
    return normalise({
        "primary": getattr(settings, "theme_primary", None),
        "secondary": getattr(settings, "theme_secondary", None),
    })


def tint(hex_colour: str, amount: float) -> str:
    """
    Mix a colour towards white. amount=0 returns it unchanged, 1.0 returns white.

    Used for table-header and total-row fills. Deriving them from the primary
    rather than offering them as choices is what keeps every one of the 36
    palette colours legible without anyone auditing 36 combinations by eye.
    """
    if not _HEX_RE.match(hex_colour or ""):
        hex_colour = DEFAULT_PRIMARY
    amount = max(0.0, min(float(amount), 1.0))
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    mix = lambda c: round(c + (255 - c) * amount)  # noqa: E731
    return f"#{mix(r):02x}{mix(g):02x}{mix(b):02x}"


def to_public_dict() -> dict:
    """The palette the settings screen renders."""
    families: dict[str, list] = {}
    for entry in PALETTE:
        families.setdefault(entry["family"], []).append(entry)
    return {
        "palette": PALETTE,
        "families": [{"name": name, "colors": colors} for name, colors in families.items()],
        "default": dict(DEFAULT_THEME),
        "roles": {
            "primary": "Headings, company name, table header text and the signature rule — "
                       "everything a reader has to read.",
            "secondary": "Rules, the line above a total and the emphasis on the amount paid — "
                         "the accent, seen rather than read.",
        },
    }
