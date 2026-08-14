"""
services/receipt_layout.py — how a landlord's receipts are laid out.

Landlords print receipts on whatever they have. Some run a thermal till roll at
the gate; some print three receipts down a single A4 sheet to save paper; some
want the full page. One fixed layout serves none of them well, so the layout is
theirs to choose.

The shape is a small, VALIDATED dictionary rather than free-form CSS: a landlord
choosing "logo on the left, address on the right, thermal roll" cannot produce a
broken document, and we can change how each option renders later without
breaking anything they saved.

    paper         a4 | a4_third_portrait | a4_third_landscape | thermal_80
    header_slots  which of logo / letterhead / address sits left, centre, right
    density       normal | compact
    font_scale    0.8 – 1.25
    sections      which optional blocks appear

NULL in the database means "the built-in default", so every landlord who never
opens this screen keeps exactly the receipt they have today.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# (key, label, width mm, height mm or None for continuous, description)
PAPERS: dict[str, dict] = {
    "a4": {
        "label": "A4 (full page)",
        "width_mm": 210, "height_mm": 297,
        "description": "A full sheet. Roomiest, and what most offices file.",
    },
    "a4_third_portrait": {
        "label": "A4 third — tall slip",
        "width_mm": 99, "height_mm": 210,
        "description": "A narrow slip, three down a portrait A4. Saves paper.",
    },
    "a4_third_landscape": {
        "label": "A4 third — wide slip",
        "width_mm": 297, "height_mm": 99,
        "description": "A wide band, three across a landscape A4.",
    },
    "thermal_80": {
        "label": "Thermal roll (80mm)",
        "width_mm": 80, "height_mm": None,   # continuous — grows with content
        "description": "For a till/receipt printer at the gate or office.",
    },
}

COMPONENTS: dict[str, str] = {
    "logo":       "Your logo",
    "letterhead": "Company name and receipt title",
    "address":    "Address, P.O. Box, phone and email",
}

SLOTS = ("left", "center", "right")
DENSITIES = ("normal", "compact")
SECTIONS = ("deposits", "notes", "signature", "balance")

DEFAULT_LAYOUT: dict = {
    "paper": "a4",
    "header_slots": {"left": "logo", "center": "letterhead", "right": "address"},
    "hidden_components": [],
    "density": "normal",
    "font_scale": 1.0,
    "sections": {"deposits": True, "notes": True, "signature": True, "balance": True},
}


def normalise(raw) -> dict:
    """
    Coerce anything into a valid layout, falling back to the default per field.

    Never raises and never returns something the renderer can't draw: a
    corrupted or hand-edited value must degrade to the standard receipt, not
    produce a broken document or a 500 when somebody asks for a receipt.
    """
    layout = json.loads(json.dumps(DEFAULT_LAYOUT))   # deep copy

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("receipt layout: unparseable JSON, using the default")
            return layout
    if not isinstance(raw, dict):
        return layout

    if raw.get("paper") in PAPERS:
        layout["paper"] = raw["paper"]

    slots = raw.get("header_slots")
    if isinstance(slots, dict):
        chosen: dict[str, str | None] = {}
        used: set[str] = set()
        for slot in SLOTS:
            value = slots.get(slot)
            # A component may appear in at most one slot — the same logo drawn
            # twice is a mistake, not a choice.
            if value in COMPONENTS and value not in used:
                chosen[slot] = value
                used.add(value)
            else:
                chosen[slot] = None
        layout["header_slots"] = chosen

    hidden = raw.get("hidden_components")
    if isinstance(hidden, list):
        layout["hidden_components"] = [c for c in hidden if c in COMPONENTS]

    if raw.get("density") in DENSITIES:
        layout["density"] = raw["density"]

    try:
        scale = float(raw.get("font_scale", 1.0))
        layout["font_scale"] = max(0.8, min(scale, 1.25))
    except (TypeError, ValueError):
        pass

    sections = raw.get("sections")
    if isinstance(sections, dict):
        layout["sections"] = {
            name: bool(sections.get(name, DEFAULT_LAYOUT["sections"][name]))
            for name in SECTIONS
        }

    return layout


def for_landlord(landlord) -> dict:
    """The landlord's saved layout, or the default when they've never set one."""
    settings = getattr(landlord, "landlord_settings", None)
    return normalise(getattr(settings, "receipt_layout_json", None))


def page_css(layout: dict) -> str:
    """
    The @page rule and size-dependent styling for a layout.

    A thermal roll is continuous stationery: giving it a fixed height would
    either cut a long receipt off or spit out blank paper after a short one, so
    its height is left to the content.
    """
    paper = PAPERS.get(layout["paper"], PAPERS["a4"])
    width, height = paper["width_mm"], paper["height_mm"]
    compact = layout["density"] == "compact"
    scale = layout["font_scale"]

    if height is None:
        size = f"{width}mm auto"
        margin = "4mm"
    elif layout["paper"] == "a4":
        size = "A4"
        margin = "12mm" if not compact else "8mm"
    else:
        size = f"{width}mm {height}mm"
        margin = "6mm" if not compact else "4mm"

    base_pt = round((8.5 if compact else 10) * scale, 2)
    heading_pt = round(base_pt * 1.45, 2)
    small_pt = round(base_pt * 0.82, 2)
    row_padding = "2px 4px" if compact else "5px 8px"

    return f"""
    @page {{ size: {size}; margin: {margin}; }}
    body {{ font-size: {base_pt}pt; }}
    h1, h2, .receipt-title {{ font-size: {heading_pt}pt; }}
    .receipt-meta, .receipt-small {{ font-size: {small_pt}pt; }}
    table td, table th {{ padding: {row_padding}; }}
    .receipt-header {{ width: 100%; }}
    .receipt-header td {{ vertical-align: top; }}
    .receipt-logo img {{ max-height: {round(46 * scale)}px; max-width: 100%; }}
    """


def header_html(layout: dict, meta: dict) -> str:
    """
    The three-slot header, drawn in the order the landlord chose.

    Slots are rendered as one table row rather than floats so it lands the same
    way in WeasyPrint as it does in a browser preview.
    """
    from html import escape

    hidden = set(layout.get("hidden_components") or [])

    def render(component: str | None) -> str:
        if not component or component in hidden:
            return ""
        if component == "logo":
            url = meta.get("logo_url")
            return f'<div class="receipt-logo"><img src="{escape(str(url))}"></div>' if url else ""
        if component == "letterhead":
            name = escape(str(meta.get("company_name") or ""))
            title = escape(str(meta.get("report_title") or "Receipt"))
            return (
                f'<div class="receipt-title"><strong>{name}</strong></div>'
                f'<div class="receipt-meta">{title}</div>'
            )
        if component == "address":
            parts = [meta.get(k) for k in ("company_address", "phone", "email")]
            lines = "<br>".join(escape(str(p)) for p in parts if p)
            return f'<div class="receipt-meta">{lines}</div>' if lines else ""
        return ""

    slots = layout.get("header_slots") or DEFAULT_LAYOUT["header_slots"]
    cells = ""
    for slot in SLOTS:
        content = render(slots.get(slot))
        align = {"left": "left", "center": "center", "right": "right"}[slot]
        cells += f'<td style="text-align:{align};width:33.33%">{content}</td>'

    return f'<table class="receipt-header"><tr>{cells}</tr></table>'


def to_public_dict() -> dict:
    """The option catalogue the settings screen renders."""
    return {
        "papers": [
            {"key": key, **{k: v for k, v in spec.items()}}
            for key, spec in PAPERS.items()
        ],
        "components": [{"key": k, "label": v} for k, v in COMPONENTS.items()],
        "slots": list(SLOTS),
        "densities": list(DENSITIES),
        "sections": list(SECTIONS),
        "default": DEFAULT_LAYOUT,
    }
