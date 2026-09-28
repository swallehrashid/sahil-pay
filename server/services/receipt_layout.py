"""
services/receipt_layout.py — how a landlord's receipts are laid out.

Landlords print receipts on whatever they have. Some run a thermal till roll at
the gate; most cut receipts out of an A4 sheet; some want the full page. One
fixed layout serves none of them well, so the layout is theirs to choose.

THE PDF IS THE SHEET OF PAPER — WHAT YOU PREVIEW IS WHAT PRINTS
---------------------------------------------------------------
This is the part that was wrong before, and it was wrong in a way no print
setting could fix. A "third of A4" receipt used to be generated as a PDF whose
PAGE was 210 × 99 mm. A 210 × 99 page is wider than it is tall, so every print
dialog does the same thing with it: turns it to landscape and scales it up to
fill an A4 sheet. The receipt came out rotated, covering the whole page, with
the text shrunk to fit and enormous gaps between the columns — while the
on-screen preview, which shows the page as it is, looked fine.

Now the PDF page is ALWAYS the physical sheet that goes into the printer — A4
portrait for the A4 papers — and the receipt is drawn in its place on that
sheet: the top third, full width, with a dashed cut line under it. "Fit to
page", "Actual size", auto-rotate: all of them print an A4 page onto A4 paper
at 100%, so there is nothing left for the dialog to get wrong. The preview is
the same A4 page, so it is literally what comes out.

The one exception is the thermal roll, which is not cut from A4: a till
printer prints an 80 mm page as an 80 mm page.

CHOOSING A PAPER CHANGES THE ARRANGEMENT, NOT THE SCALE
-------------------------------------------------------
A paper names a FLOW, and the flow decides the arrangement:

  full    a full page. Detail tables with all four money columns.
  band    short and wide. Three tables side by side — details | charges |
          summary — so the height stays inside the third and the width is used.
  column  narrow and tall (a cut strip, a till roll). One column.

THE LETTERHEAD IS SIZED BY THE LANDLORD
---------------------------------------
Logo, company name and contact details each have their own size (50–250%),
because the right size depends on the logo: a wide lockup needs less height
than a square badge. See `letterhead` below.

    paper         a4 | a4_third_band | a4_third_slip | a4_third_landscape | thermal_80
    header_slots  which of logo / letterhead / address sits left, centre, right
    density       normal | compact
    font_scale    0.8 – 1.3
    letterhead    {logo, title, contact} size multipliers, title_align
    sections      which optional blocks appear

NULL in the database means "the built-in default".
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

FLOW_FULL = "full"
FLOW_BAND = "band"
FLOW_COLUMN = "column"

# Charge rows a band will print before summarising the remainder. A third of a
# page cannot grow; a tenant with a dozen lines would push it past the cut line.
BAND_MAX_CHARGE_ROWS = 7

A4 = (210, 297)
A4_LANDSCAPE = (297, 210)

# `sheet` is the page the PDF is — the paper in the printer. `box` is the
# receipt drawn on it, at the top-left. For a4 and the thermal roll they are
# the same thing.
PAPERS: dict[str, dict] = {
    "a4": {
        "label": "A4 (full page)",
        "width_mm": 210, "height_mm": 297,
        "sheet": A4,
        "flow": FLOW_FULL,
        "description": "A full sheet. Roomiest, and what most offices file.",
        "cut_hint": None,
    },
    "a4_third_band": {
        "label": "A4 third — portrait (top third of the page)",
        "width_mm": 210, "height_mm": 99,
        "sheet": A4,
        "flow": FLOW_BAND,
        "description": "The receipt fills the top third of an upright A4 sheet, "
                       "full width. Big letterhead, three tables across.",
        "cut_hint": "Prints on an upright A4 sheet. Cut along the dashed line "
                    "under the receipt.",
    },
    "a4_third_slip": {
        # A third of the WIDTH of portrait A4 is 70 mm. This used to be 99 mm,
        # which cannot be cut three times from a 210 mm sheet at all — so every
        # printer had to rescale it.
        "label": "A4 third — narrow strip",
        "width_mm": 70, "height_mm": 297,
        "sheet": A4,
        "flow": FLOW_COLUMN,
        "description": "One third of the width of an upright A4 sheet, full "
                       "height. One column, like a till receipt.",
        "cut_hint": "Prints on the left third of an upright A4 sheet. Cut along "
                    "the dashed line.",
    },
    "a4_third_landscape": {
        "label": "Landscape A4 third — wide band",
        "width_mm": 297, "height_mm": 70,
        "sheet": A4_LANDSCAPE,
        "flow": FLOW_BAND,
        "description": "The top third of a sideways (landscape) A4 sheet.",
        "cut_hint": "Prints on a landscape A4 sheet. Cut along the dashed line.",
    },
    "thermal_80": {
        "label": "Thermal roll (80mm)",
        # Continuous stationery, but a page needs a real height: `80mm auto` is
        # not a valid @page size and WeasyPrint silently fell back to A4.
        "width_mm": 80, "height_mm": 297,
        "sheet": (80, 297),
        "flow": FLOW_COLUMN,
        "description": "For a till/receipt printer at the gate or office. "
                       "Set the printer to cut at the end of content.",
        "cut_hint": None,
    },
}

# Older keys still resolve. "a4_third_portrait" is what owners call the
# top-third receipt, and it is what they mean by it.
PAPER_ALIASES = {"a4_third_portrait": "a4_third_band"}

COMPONENTS: dict[str, str] = {
    "logo":       "Your logo",
    "letterhead": "Company name and receipt title",
    "address":    "Address, P.O. Box, phone and email",
}

SLOTS = ("left", "center", "right")
DENSITIES = ("normal", "compact")
SECTIONS = ("deposits", "notes", "signature", "balance")
ALIGNS = ("left", "center", "right")

# Letterhead size multipliers — 1.0 is the built-in size for the paper.
LETTERHEAD_MIN, LETTERHEAD_MAX = 0.5, 2.5
DEFAULT_LETTERHEAD = {"logo": 1.0, "title": 1.0, "contact": 1.0, "title_align": "left"}

DEFAULT_LAYOUT: dict = {
    "paper": "a4",
    "header_slots": {"left": "logo", "center": "letterhead", "right": "address"},
    "hidden_components": [],
    "density": "normal",
    "font_scale": 1.0,
    "letterhead": dict(DEFAULT_LETTERHEAD),
    "sections": {"deposits": True, "notes": True, "signature": True, "balance": True},
}


def resolve_paper(key: str) -> str:
    """The current key for a paper, following renames."""
    key = PAPER_ALIASES.get(key, key)
    return key if key in PAPERS else DEFAULT_LAYOUT["paper"]


def spec(layout: dict) -> dict:
    return PAPERS[resolve_paper(layout.get("paper", "a4"))]


def flow_of(layout: dict) -> str:
    return spec(layout)["flow"]


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(float(value), hi))
    except (TypeError, ValueError):
        return default


def normalise(raw) -> dict:
    """
    Coerce anything into a valid layout, falling back to the default per field.

    Never raises: a corrupted value must degrade to the standard receipt, not a
    500 when somebody asks for a receipt.
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

    if raw.get("paper"):
        resolved = PAPER_ALIASES.get(raw["paper"], raw["paper"])
        if resolved in PAPERS:
            layout["paper"] = resolved

    slots = raw.get("header_slots")
    if isinstance(slots, dict):
        chosen: dict[str, str | None] = {}
        used: set[str] = set()
        for slot in SLOTS:
            value = slots.get(slot)
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

    layout["font_scale"] = _clamp(raw.get("font_scale", 1.0), 0.8, 1.3, 1.0)

    lh = raw.get("letterhead")
    if isinstance(lh, dict):
        for key in ("logo", "title", "contact"):
            layout["letterhead"][key] = round(
                _clamp(lh.get(key, 1.0), LETTERHEAD_MIN, LETTERHEAD_MAX, 1.0), 2)
        if lh.get("title_align") in ALIGNS:
            layout["letterhead"]["title_align"] = lh["title_align"]

    sections = raw.get("sections")
    if isinstance(sections, dict):
        layout["sections"] = {
            name: bool(sections.get(name, DEFAULT_LAYOUT["sections"][name]))
            for name in SECTIONS
        }

    return layout


def for_landlord(landlord) -> dict:
    settings = getattr(landlord, "landlord_settings", None)
    return normalise(getattr(settings, "receipt_layout_json", None))


# ---------------------------------------------------------------------------
# Typesetting
# ---------------------------------------------------------------------------
#
# Sizes per flow, at 100%. Chosen against a real, owner-supplied receipt cut
# from the top third of an A4 sheet: a ~20 mm logo, a 13 pt "OFFICIAL
# RECEIPT", an 11 pt company name, 9 pt contacts and 9.5 pt body text with rows
# only a hair apart. The old band spread its rows down the paper with padding
# to "fill" the height; that is where the big gaps came from, and it is gone.
#
#               body  logo  title  company  contact   row pad (mm)
_TYPE = {
    FLOW_BAND:   (10.0, 22,   15.0,  12.5,    9.5,      0.40),
    FLOW_FULL:   (10.5, 24,   16.0,  13.0,    9.5,      0.9),
    FLOW_COLUMN: (8.5,  14,   11.0,  9.5,     7.5,      0.35),
}
# The landscape band is 70 mm tall, not 99: everything scaled to the height.
_LANDSCAPE_SHRINK = 0.78


def _type_for(layout: dict) -> dict:
    paper = spec(layout)
    flow = paper["flow"]
    body, logo, title, company, contact, pad = _TYPE[flow]
    if flow == FLOW_BAND and paper["height_mm"] < 90:
        body, logo, title, company, contact, pad = (
            v * _LANDSCAPE_SHRINK for v in (body, logo, title, company, contact, pad))
    if paper["width_mm"] <= 80 and flow == FLOW_COLUMN:
        logo = min(logo, 14)
    compact = layout["density"] == "compact"
    scale = layout["font_scale"]
    lh = layout.get("letterhead") or DEFAULT_LETTERHEAD
    body = (body - (0.8 if compact else 0)) * scale
    return {
        "body": round(body, 2),
        "small": round(body * 0.86, 2),
        "heading": round(body * 1.05, 2),
        "logo_mm": round(logo * lh.get("logo", 1.0), 1),
        "title": round(title * lh.get("title", 1.0), 2),
        "company": round(company * lh.get("title", 1.0), 2),
        "contact": round(contact * lh.get("contact", 1.0), 2),
        "pad_mm": round(pad * (0.6 if compact else 1.0), 2),
    }


def page_css(layout: dict, theme: dict | None = None) -> str:
    """
    The complete receipt stylesheet: the sheet, the receipt box on it, and the
    receipt's own typography. Self-contained on purpose — the shared report
    stylesheet sized the label column of every details table at 38% of the
    width, which is exactly the gap between "Paid by" and the name.
    """
    from services import receipt_theme

    paper = spec(layout)
    flow = paper["flow"]
    sheet_w, sheet_h = paper["sheet"]
    box_w, box_h = paper["width_mm"], paper["height_mm"]
    t = _type_for(layout)
    compact = layout["density"] == "compact"

    colours = receipt_theme.resolve(theme)
    primary = colours["primary"]
    secondary = colours["secondary"]
    head_fill = receipt_theme.tint(primary, 0.93)
    grid_rule = receipt_theme.tint(primary, 0.78)
    zebra = receipt_theme.tint(primary, 0.97)
    total_fill = receipt_theme.tint(secondary, 0.94)
    muted = receipt_theme.tint(primary, 0.40)

    is_cut = (sheet_w, sheet_h) != (box_w, box_h)

    if flow == FLOW_FULL:
        page = f"@page {{ size: A4 portrait; margin: {'8mm' if compact else '12mm'}; }}"
        box = ""
    elif not is_cut:                           # thermal roll
        page = f"@page {{ size: {sheet_w}mm {sheet_h}mm; margin: 2mm; }}"
        box = ""
    else:
        # The receipt is a fixed box on the sheet. Its height never changes,
        # so a busy receipt can never spill over the cut line onto the next.
        pad = "4mm 6mm" if flow == FLOW_BAND else "4mm 3.5mm"
        if compact:
            pad = "3mm 4.5mm" if flow == FLOW_BAND else "3mm 2.5mm"
        cut_edge = "border-bottom" if flow == FLOW_BAND else "border-right"
        orientation = "landscape" if sheet_w > sheet_h else "portrait"
        page = f"@page {{ size: A4 {orientation}; margin: 0; }}"
        box = (f".sheet {{ width: {box_w}mm; height: {box_h}mm; padding: {pad}; "
               f"box-sizing: border-box; overflow: hidden; "
               f"{cut_edge}: 0.35mm dashed #9a9a9a; }}")

    css = f"""
    {page}
    html, body {{ margin: 0; padding: 0; }}
    body {{ font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
           font-size: {t['body']}pt; line-height: 1.22; color: {primary}; }}
    {box}
    .muted {{ color: {muted}; }}

    /* ---- letterhead ---- */
    table.receipt-header {{ width: 100%; border-collapse: collapse;
                           border-bottom: 0.5mm solid {secondary}; margin: 0 0 1.6mm; }}
    table.receipt-header td {{ vertical-align: middle; padding: 0 0 1.4mm; border: none; }}
    td.slot-logo {{ width: 1%; white-space: nowrap; padding-right: 3mm !important; }}
    td.slot-address {{ width: 36%; }}
    .receipt-logo img {{ height: {t['logo_mm']}mm; max-width: {t['logo_mm'] * 3.2:.1f}mm;
                        object-fit: contain; display: block; }}
    .receipt-letterhead img {{ max-height: {t['logo_mm']}mm; max-width: 100%; object-fit: contain; }}
    .doc-kind {{ font-size: {t['title']}pt; font-weight: 800; letter-spacing: .02em;
                text-transform: uppercase; margin: 0; line-height: 1.1; }}
    .company-name {{ font-size: {t['company']}pt; font-weight: 700; text-transform: uppercase;
                    margin: 0.4mm 0 0; line-height: 1.12; }}
    .contact {{ font-size: {t['contact']}pt; line-height: 1.3; }}
    .letterhead-rule {{ border-top: 0.3mm solid {primary}; margin: 0.5mm 0 0.6mm; width: 100%; }}

    /* ---- tables ---- */
    h2 {{ font-size: {t['heading']}pt; font-weight: 700; margin: 0 0 0.8mm;
         color: {secondary}; text-transform: uppercase; letter-spacing: .03em; }}
    table {{ border-collapse: collapse; }}
    table.grid {{ width: 100%; border: 0.25mm solid {grid_rule}; }}
    table.grid th, table.grid td {{ border: 0.25mm solid {grid_rule};
                                    padding: {t['pad_mm']}mm 1.4mm;
                                    font-size: {t['body']}pt; vertical-align: top; }}
    table.grid thead th {{ background: {primary}; color: #fff; text-align: left;
                          font-weight: 700; border-color: {primary}; }}
    table.grid tbody tr:nth-child(even) td {{ background: {zebra}; }}
    table.grid tr.group-row td {{ background: {head_fill}; color: {secondary}; font-weight: 700;
                                  text-transform: uppercase; font-size: {t['small']}pt; }}
    table.grid tr.total-row td {{ font-weight: 800; background: {total_fill};
                                  border-top: 0.5mm solid {secondary}; }}
    .right {{ text-align: right; }}
    td.right, th.right {{ white-space: nowrap; }}
    /* Details: the label is as wide as its words and no wider, and the value
       sits right after it — "Paid by  Jonathan Kehumba", not a page apart. */
    table.kv td.k {{ width: 1%; white-space: nowrap; font-weight: 700;
                    background: {head_fill}; }}
    table.kv td.v {{ text-align: left; }}
    .month {{ color: {muted}; white-space: nowrap; }}
    .receipt-small {{ font-size: {t['small']}pt; }}
    .receipt-footnote {{ margin-top: 1mm; font-size: {t['small']}pt; }}
    .receipt-footnote p {{ margin: 0.3mm 0 0; }}
    .owed-line {{ font-size: {t['small']}pt; margin: 1mm 0 0; }}
    .owed-line strong {{ color: {secondary}; }}

    /* ---- signature ---- */
    .signature {{ margin-top: 2mm; text-align: center; }}
    .signature img {{ max-height: {max(6, t['logo_mm'] * 0.45):.1f}mm; max-width: 100%; }}
    .signature .line {{ border-top: 0.3mm solid {primary}; padding-top: 0.6mm;
                       font-size: {t['small']}pt; }}
    .credit {{ font-size: {round(t['small'] * 0.85, 2)}pt; color: {muted}; }}
    """

    if flow == FLOW_BAND:
        css += """
    table.receipt-body { width: 100%; table-layout: fixed; }
    table.receipt-body > tbody > tr > td, table.receipt-body > tr > td {
        vertical-align: top; padding: 0 2.2mm 0 0; border: none; }
    td.col-totals { padding-right: 0 !important; }
    /* Thanks and the credit share ONE line: the space under the tables is the
       last few millimetres before the cut. */
    .receipt-footnote p { display: inline; margin: 0 1.5mm 0 0; }
    .col-details { width: 35%; }
    .col-charges { width: 36%; }
    .col-totals  { width: 29%; }
    table.charges td, table.totals td { white-space: nowrap; }
    /* A long property name or receipt number wraps INSIDE its own column —
       it must never run across into the charges beside it. */
    table.kv { table-layout: fixed; }
    table.kv td.k { width: 36%; }
    table.kv td.v { white-space: normal; overflow-wrap: anywhere; }
    """
    elif flow == FLOW_COLUMN:
        css += """
    table.receipt-body { width: 100%; }
    table.receipt-body td.stack { padding: 0; border: none; }
    table.receipt-body td.stack > * + * { margin-top: 1.4mm; }
    table.receipt-header td { display: block; width: 100% !important; text-align: center !important; }
    td.slot-logo .receipt-logo img { margin: 0 auto; }
    """
    else:
        css += """
    table.receipt-body { width: 100%; }
    table.receipt-body td.stack { padding: 0; border: none; }
    table.receipt-body td.stack > h2 { margin-top: 3mm; }
    """
    return css


def header_html(layout: dict, meta: dict) -> str:
    """
    The letterhead: logo, company name under the receipt title, contacts —
    each in the slot the landlord chose. One table row, so it lands the same in
    WeasyPrint as in a browser.
    """
    from html import escape

    hidden = set(layout.get("hidden_components") or [])
    align = (layout.get("letterhead") or DEFAULT_LETTERHEAD).get("title_align", "left")

    def render(component: str | None) -> str:
        if not component or component in hidden:
            return ""
        if component == "logo":
            url = meta.get("logo_url")
            return f'<div class="receipt-logo"><img src="{escape(str(url))}"></div>' if url else ""
        if component == "letterhead":
            kind = escape(str(meta.get("report_title") or "Official Receipt"))
            if meta.get("letterhead_url"):
                return (f'<div class="receipt-letterhead"><img src="{escape(str(meta["letterhead_url"]))}"></div>'
                        f'<p class="doc-kind">{kind}</p>')
            name = escape(str(meta.get("company_name") or ""))
            web = (meta.get("website") or "").strip()
            email = (meta.get("email") or "").strip()
            lines = []
            if email:
                lines.append(f"EMAIL: {escape(email)}")
            if web:
                lines.append(f"WEBSITE: {escape(web)}")
            contact = f'<div class="contact">{"<br>".join(lines)}</div>' if lines else ""
            return (f'<p class="doc-kind">{kind}</p>'
                    f'<div class="letterhead-rule"></div>'
                    f'<p class="company-name">{name}</p>{contact}')
        if component == "address":
            parts = [meta.get("company_address")]
            phone = meta.get("phone")
            if phone:
                parts.append(f"MOB: {phone}")
            # Email and website sit under the company name when the letterhead
            # is shown; repeat them here only when it is not.
            if "letterhead" in hidden or "letterhead" not in (layout.get("header_slots") or {}).values():
                parts += [meta.get("email"), meta.get("website")]
            lines = "<br>".join(escape(str(p)).replace("\n", "<br>") for p in parts if p)
            return f'<div class="contact">{lines}</div>' if lines else ""
        return ""

    slots = layout.get("header_slots") or DEFAULT_LAYOUT["header_slots"]
    cells = ""
    for slot in SLOTS:
        component = slots.get(slot)
        content = render(component)
        text_align = align if component == "letterhead" else slot
        klass = f"slot-{component}" if component else "slot-empty"
        style = f"text-align:{text_align}"
        if not content:
            # An empty slot takes no room — the logo and title close up.
            style += ";width:0"
        cells += f'<td class="{klass}" style="{style}">{content}</td>'

    return f'<table class="receipt-header"><tr>{cells}</tr></table>'


def compose_body(layout: dict, blocks: dict) -> str:
    """
    Arrange the receipt's blocks for this layout's flow, wrapped in the sheet.

    `blocks`: details, charges, totals, owed, notes, etims, signature, credit.
    """
    details = blocks.get("details", "")
    charges = blocks.get("charges", "")
    totals = blocks.get("totals", "")
    owed = blocks.get("owed", "")
    notes = blocks.get("notes", "")
    etims = blocks.get("etims", "")
    signature = blocks.get("signature", "")
    credit = blocks.get("credit", "")

    if flow_of(layout) == FLOW_BAND:
        # "Still owed" sits in the summary column, under the totals it
        # explains — that column is the shortest of the three, so the space
        # is there, and nothing has to go below the tables near the cut line.
        return (
            '<table class="receipt-body"><tr>'
            f'<td class="col-details">{details}</td>'
            f'<td class="col-charges">{charges}</td>'
            f'<td class="col-totals">{totals}{owed}{signature}</td>'
            "</tr></table>"
            f'<div class="receipt-footnote">{notes}{etims}{credit}</div>'
        )

    return (
        '<table class="receipt-body"><tr>'
        f'<td class="stack">{details}{charges}{totals}{owed}{notes}{etims}{signature}{credit}</td>'
        "</tr></table>"
    )


def document(layout: dict, theme: dict | None, header: str, body: str) -> str:
    """The full HTML: stylesheet, then the sheet box holding header and body."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{page_css(layout, theme)}</style></head>"
        f"<body><div class='sheet'>{header}{body}</div></body></html>"
    )


def max_charge_rows(layout: dict) -> int | None:
    """
    Only a band is capped: it is the one receipt with a fixed height. The 70 mm
    landscape band holds two rows fewer than the 99 mm portrait third.
    """
    if flow_of(layout) != FLOW_BAND:
        return None
    return BAND_MAX_CHARGE_ROWS if spec(layout)["height_mm"] >= 90 else BAND_MAX_CHARGE_ROWS - 2


def max_owed_rows(layout: dict) -> int:
    """How many 'still owed' rows fit under the summary on this paper."""
    if flow_of(layout) != FLOW_BAND:
        return 6
    return 3 if spec(layout)["height_mm"] >= 90 else 1


def money_columns(layout: dict) -> int:
    """Four money columns on a full page; item + paid everywhere else."""
    return 4 if flow_of(layout) == FLOW_FULL else 2


def to_public_dict() -> dict:
    """The option catalogue the settings screen renders."""
    return {
        "papers": [
            {"key": key, **{k: v for k, v in spec_.items() if k != "sheet"},
             "sheet_width_mm": spec_["sheet"][0], "sheet_height_mm": spec_["sheet"][1]}
            for key, spec_ in PAPERS.items()
        ],
        "components": [{"key": k, "label": v} for k, v in COMPONENTS.items()],
        "slots": list(SLOTS),
        "densities": list(DENSITIES),
        "sections": list(SECTIONS),
        "letterhead": {"min": LETTERHEAD_MIN, "max": LETTERHEAD_MAX, "aligns": list(ALIGNS)},
        "default": DEFAULT_LAYOUT,
        "print_note": (
            "The file is a full A4 page with the receipt already in place, so it "
            "prints the same whatever the print dialog is set to. Cut along the "
            "dashed line."
        ),
    }
