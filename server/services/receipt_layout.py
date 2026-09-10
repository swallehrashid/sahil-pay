"""
services/receipt_layout.py — how a landlord's receipts are laid out.

Landlords print receipts on whatever they have. Some run a thermal till roll at
the gate; some cut three receipts out of a single A4 sheet to save paper; some
want the full page. One fixed layout serves none of them well, so the layout is
theirs to choose.

CHOOSING A PAPER CHANGES THE ARRANGEMENT, NOT THE SCALE
-------------------------------------------------------
This is the part that was wrong before. Every paper used the same stacked
arrangement — header, then details, then one table per charge group, then
totals, then signature — and only the @page size and the font size changed.
Stack that down a 99mm-tall band and it does not fit; stack it down a 99mm-wide
slip and every table column is squeezed to a few millimetres. The receipt did
not become a band, it became an A4 receipt that had been shrunk, with the
content marooned in the middle of the paper.

So a paper now names a FLOW, and the flow decides the arrangement:

  full    a full page. Detail tables with all four money columns.
  band    short and wide. The body is dealt into three columns side by side —
          details | charges | totals — so the height stays inside the band and
          the width is actually used. Charge tables drop to description + paid,
          because four money columns in a third of a page is unreadable anyway.
  column  narrow and tall (a cut slip, a till roll). One column, condensed,
          two money columns.

A NOTE ON PRINTING, BECAUSE IT LOOKS LIKE A BUG AND IS NOT
----------------------------------------------------------
The PDF is generated at exactly the chosen size — a 210×99mm band really is a
210×99mm page. If it is then printed with the print dialog set to "Fit to page"
(the default nearly everywhere), the printer scales that small page up onto the
A4 sheet and centres it, producing a shrunken receipt surrounded by white
margin. That is the printer, not the layout. Print at "Actual size" / 100%.

    paper         a4 | a4_third_band | a4_third_slip | a4_third_landscape | thermal_80
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

FLOW_FULL = "full"
FLOW_BAND = "band"
FLOW_COLUMN = "column"

# How a band is typeset, as a proportion of the height it has.
#
# Both numbers were measured, not guessed: receipts were rendered at each
# candidate value and the resulting PDF was scanned for how much of the page the
# ink actually spans. Together these put a typical receipt at 85-93% of the band
# height on a single page — filling the paper, with enough headroom that a
# busier-than-average receipt still fits.
#
#   BAND_PT_PER_MM       base font size. On its own it cannot fill a band: a
#                        wide band holds few rows, and sizing up to reach the
#                        bottom produces an ugly receipt that still doesn't.
#   BAND_ROW_PAD_PER_MM  vertical row padding. THIS is what fills the height —
#                        it spreads the rows down the paper instead of leaving
#                        a strip of text at the top. Because padding does the
#                        filling, the FONT can stay small enough that labels
#                        like "Received from" do not wrap inside a third-width
#                        column. Raising the pair together tips the 70mm
#                        landscape band, which is the tightest, onto a second
#                        page — 0.090/0.018 is the last safe step.
BAND_PT_PER_MM = 0.090
BAND_ROW_PAD_PER_MM = 0.018

# Charge rows a band will print before summarising the remainder.
#
# A fixed-height band cannot grow, so a tenant with a dozen line items would
# push it onto a second page — and the second page of a 99mm band is a mostly
# empty slip that looks like a printing fault. Capping the rows and saying how
# many were folded away keeps the receipt honest and keeps it on one band; the
# full breakdown is on the statement, which is what a statement is for.
BAND_MAX_CHARGE_ROWS = 7

# A4 is 210 × 297mm. A "third" can be cut two ways, and landlords mean both:
# across the page (a wide band, three stacked down the sheet) or down the page
# (a tall slip, three side by side). Both are offered rather than guessed at.
PAPERS: dict[str, dict] = {
    "a4": {
        "label": "A4 (full page)",
        "width_mm": 210, "height_mm": 297,
        "flow": FLOW_FULL,
        "description": "A full sheet. Roomiest, and what most offices file.",
        "cut_hint": None,
    },
    "a4_third_band": {
        "label": "A4 third — wide band",
        "width_mm": 210, "height_mm": 99,
        "flow": FLOW_BAND,
        "description": "Full A4 width, one third of the height. Three stacked "
                       "down a portrait sheet — cut across the page.",
        "cut_hint": "Three of these stack down one portrait A4 (cut across).",
    },
    "a4_third_slip": {
        "label": "A4 third — tall slip",
        "width_mm": 99, "height_mm": 297,
        "flow": FLOW_COLUMN,
        "description": "One third of the A4 width, full height. Three side by "
                       "side across a portrait sheet — cut down the page.",
        "cut_hint": "Three of these sit side by side on one portrait A4 (cut down).",
    },
    "a4_third_landscape": {
        "label": "Landscape A4 third — wide band",
        "width_mm": 297, "height_mm": 70,
        "flow": FLOW_BAND,
        "description": "Full landscape-A4 width, one third of the height. "
                       "Three stacked down a landscape sheet.",
        "cut_hint": "Three of these stack down one landscape A4.",
    },
    "thermal_80": {
        "label": "Thermal roll (80mm)",
        # Continuous stationery, but the page still needs a real height.
        #
        # This used to be None, which produced the CSS `size: 80mm auto`.
        # `auto` is not a valid SECOND value in an @page size, so WeasyPrint
        # rejected the whole declaration — logging "Ignored `size: 80mm auto`,
        # invalid value" where nobody would see it — and fell back to A4. Every
        # thermal receipt ever generated came out 210mm wide, which is two and a
        # half times the width of the roll it was meant for.
        #
        # 297mm is a full roll-length page. A till printer set to cut at the end
        # of content ignores the unused remainder; one set to form-feed will
        # advance to the end of the page, so set the driver to receipt/cut mode.
        "width_mm": 80, "height_mm": 297,
        "flow": FLOW_COLUMN,
        "description": "For a till/receipt printer at the gate or office. "
                       "Set the printer to cut at the end of content.",
        "cut_hint": None,
    },
}

# The old key for the 99×210 slip. Renamed to a4_third_slip when the wide band
# was added, because "third portrait" described both and meant neither. Anything
# already saved in the database still resolves — silently changing a landlord's
# paper because we renamed a constant would be worse than the original bug.
PAPER_ALIASES = {"a4_third_portrait": "a4_third_slip"}

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


def resolve_paper(key: str) -> str:
    """The current key for a paper, following renames."""
    key = PAPER_ALIASES.get(key, key)
    return key if key in PAPERS else DEFAULT_LAYOUT["paper"]


def spec(layout: dict) -> dict:
    """The PAPERS entry for a layout."""
    return PAPERS[resolve_paper(layout.get("paper", "a4"))]


def flow_of(layout: dict) -> str:
    """Which arrangement this layout's paper calls for."""
    return spec(layout)["flow"]


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


def page_css(layout: dict, theme: dict | None = None) -> str:
    """
    The @page rule and flow-dependent styling for a layout.

    A thermal roll is continuous stationery: giving it a fixed height would
    either cut a long receipt off or spit out blank paper after a short one, so
    its height is left to the content.

    `theme` is the landlord's colour pair (services/receipt_theme.py). Omitted,
    the Sahil Pay palette is used, so an account that has never opened the
    screen renders exactly as before.
    """
    from services import receipt_theme

    paper = spec(layout)
    flow = paper["flow"]
    width, height = paper["width_mm"], paper["height_mm"]
    compact = layout["density"] == "compact"
    scale = layout["font_scale"]
    colours = receipt_theme.resolve(theme)
    primary = colours["primary"]
    secondary = colours["secondary"]
    primary_soft = receipt_theme.tint(primary, 0.90)
    primary_faint = receipt_theme.tint(primary, 0.96)

    # Margins are small on the cut papers on purpose. A 12mm margin on a 99mm
    # band spends a quarter of the height on white — the whole complaint.
    if width <= 80:
        # A till roll: no side margin to speak of, the paper is the margin.
        size, margin = f"{width}mm {height}mm", "2mm"
    elif flow == FLOW_FULL:
        size, margin = "A4", ("8mm" if compact else "12mm")
    elif flow == FLOW_BAND:
        size, margin = f"{width}mm {height}mm", ("3mm 4mm" if compact else "4mm 6mm")
    else:
        size, margin = f"{width}mm {height}mm", ("3mm" if compact else "5mm")

    # Base type is set per flow, and for a band it is scaled to the height the
    # band actually has. A 70mm band is not a 99mm band in a smaller font — it
    # has 30% less room, and typesetting both at the same size is precisely how
    # the shorter one silently spilled onto a second page. The floor stops the
    # scaling from producing something nobody can read: below about 5pt a
    # printed receipt is illegible, and the honest answer is a taller paper.
    if flow == FLOW_BAND:
        base_default = max(5.2, round(BAND_PT_PER_MM * height, 2))
    else:
        base_default = {FLOW_FULL: 10, FLOW_COLUMN: 8}[flow]
    base_pt = round((base_default - (1 if compact else 0)) * scale, 2)
    heading_pt = round(base_pt * (1.2 if flow != FLOW_FULL else 1.45), 2)
    small_pt = round(base_pt * 0.85, 2)
    if flow == FLOW_BAND:
        # Row spacing is how a band FILLS its height. A wide band holds only a
        # handful of rows, and no readable type size alone will reach the bottom
        # of the paper — pushing the font up just makes an ugly receipt that
        # still ends two-thirds of the way down. Spreading the rows down the
        # available height is what turns the content into a band rather than a
        # strip of text sitting at the top of one.
        band_pad = max(0.6, round(height * BAND_ROW_PAD_PER_MM, 2))
        row_padding = f"{band_pad}mm 1.5mm" if not compact else f"{band_pad * 0.6:.2f}mm 1.2mm"
    elif flow == FLOW_COLUMN or compact:
        row_padding = "1px 3px"
    else:
        row_padding = "5px 8px"
    # The logo is boxed to the paper too — a 46px mark on a 70mm band is a
    # sixth of the total height spent on the letterhead.
    if flow == FLOW_BAND:
        logo_px = max(16, round(30 * (height / 99.0)))
    else:
        logo_px = {FLOW_FULL: 46, FLOW_COLUMN: 38}[flow]

    css = f"""
    @page {{ size: {size}; margin: {margin}; }}
    body {{ font-size: {base_pt}pt; margin: 0; color: {primary}; }}
    h1, h2, .receipt-title {{ font-size: {heading_pt}pt; color: {primary}; }}
    h2 {{ margin: 4px 0 2px; }}
    .receipt-meta, .receipt-small {{ font-size: {small_pt}pt; }}
    table {{ width: 100%; border-collapse: collapse; }}
    /* font-size MUST be restated here. report_style() sets `th, td` to 11px,
       which otherwise wins over the inherited body size and leaves a band's
       table text at a fixed 8pt while its headings scale with the paper — the
       headings end up twice the size of the figures they head. */
    table td, table th {{ padding: {row_padding}; font-size: {base_pt}pt; }}
    /* A money value must never be broken across two lines. "KES" on one line
       and "26,500.00" on the next is not a tidier receipt, it is one that has
       to be read twice. */
    td.right, th.right {{ white-space: nowrap; }}
    th {{ background: {primary_soft}; color: {primary}; text-align: left; }}
    td {{ border-bottom: 1px solid {primary_faint}; }}
    .right {{ text-align: right; }}
    tr.total-row td {{ font-weight: 700; border-top: 1.5px solid {secondary}; background: {primary_faint}; }}
    .receipt-header {{ width: 100%; border-bottom: 1.5px solid {secondary}; padding-bottom: 2mm; }}
    .receipt-header td {{ vertical-align: top; border-bottom: none; }}
    .receipt-logo img {{ max-height: {round(logo_px * scale)}px; max-width: 100%; object-fit: contain; }}
    .signature img {{ max-height: {round(logo_px * scale * 0.9)}px; }}
    .signature .line {{ border-top: 1px solid {primary}; padding-top: 2px; }}
    /* report_style() gives the signature block a 220px floor, which is right on
       a full page and wider than the whole totals column on a band — the
       company name then runs off the edge of the paper and is cut off. The
       block has to be free to shrink to whatever column it lands in. */
    .signature {{ display: block; margin-top: 2mm; }}
    .signature .block {{ min-width: 0; max-width: 100%; text-align: center; }}
    """

    if flow == FLOW_BAND:
        # THE POINT OF THE BAND. Three columns across the full width, so the
        # content grows sideways into the paper it was given instead of
        # downwards off the bottom of it.
        css += f"""
    .receipt-body {{ width: 100%; table-layout: fixed; }}
    .receipt-body > tr > td {{ vertical-align: top; border-bottom: none; padding: 0 2mm 0 0; }}
    .receipt-body > tr > td:last-child {{ padding-right: 0; }}
    /* The totals column carries the widest single thing on the receipt — a
       currency-prefixed amount next to its label — so it gets the room. */
    .col-details {{ width: 25%; }}
    .col-charges {{ width: 43%; }}
    .col-totals  {{ width: 32%; }}
    .receipt-footnote {{ margin-top: 0.5mm; }}
    .receipt-footnote p {{ margin: 0; }}
    h2 {{ margin: 0 0 1px; }}
    /* The letterhead is one compact strip on a band; the rule under it and the
       padding around it are height this paper does not have to spare. */
    .receipt-header {{ padding-bottom: 1mm; margin-bottom: 1mm; }}
    .receipt-header .receipt-title {{ font-size: {round(base_pt * 1.15, 2)}pt; }}
    .signature {{ margin-top: 1mm; }}
    .signature img {{ max-height: {max(12, round(logo_px * 0.7))}px; }}
    table {{ margin: 0; }}
    """
    elif flow == FLOW_COLUMN:
        css += """
    .receipt-body { width: 100%; }
    .receipt-body > tr > td { display: block; width: 100%; padding: 0; border-bottom: none; }
    .receipt-header td { display: block; width: 100%; text-align: center; }
    .receipt-header td + td { margin-top: 1mm; }
    """
    else:
        css += """
    .receipt-body { width: 100%; }
    .receipt-body > tr > td { display: block; width: 100%; padding: 0; border-bottom: none; }
    """
    return css


def header_html(layout: dict, meta: dict) -> str:
    """
    The three-slot header, drawn in the order the landlord chose.

    Slots are rendered as one table row rather than floats so it lands the same
    way in WeasyPrint as it does in a browser preview. On a narrow paper the CSS
    above turns the same markup into stacked, centred blocks, because three
    columns across 80mm leaves no room for any of them.
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


def compose_body(layout: dict, blocks: dict) -> str:
    """
    Arrange the receipt's blocks for this layout's flow.

    `blocks` is what the receipt is made of, named rather than pre-joined:
        details   the receipt number / date / payer / method table
        charges   the charge-group tables
        totals    the summary table
        notes     the thank-you line
        etims     the KRA block, or ""
        signature the signature block, or ""
        credit    the "generated by" credit

    A band deals them into three columns; everything else stacks them. Keeping
    the blocks separate is what makes that possible at all — the previous code
    concatenated them into one string before anything could rearrange them.
    """
    details = blocks.get("details", "")
    charges = blocks.get("charges", "")
    totals = blocks.get("totals", "")
    notes = blocks.get("notes", "")
    etims = blocks.get("etims", "")
    signature = blocks.get("signature", "")
    credit = blocks.get("credit", "")

    if flow_of(layout) == FLOW_BAND:
        return (
            '<table class="receipt-body"><tr>'
            f'<td class="col-details">{details}</td>'
            f'<td class="col-charges">{charges}</td>'
            f'<td class="col-totals">{totals}{signature}</td>'
            "</tr></table>"
            f'<div class="receipt-footnote receipt-small">{notes}{etims}{credit}</div>'
        )

    return (
        '<table class="receipt-body"><tr>'
        f"<td>{details}{charges}{totals}{notes}{etims}{signature}{credit}</td>"
        "</tr></table>"
    )


def max_charge_rows(layout: dict) -> int | None:
    """
    How many charge rows this paper will print, or None for "all of them".

    Only a band is capped: it is the one paper with a fixed height that cannot
    grow with the content. A full page, a tall slip and a till roll all have
    room to run on.
    """
    return BAND_MAX_CHARGE_ROWS if flow_of(layout) == FLOW_BAND else None


def money_columns(layout: dict) -> int:
    """
    How many money columns a charge table can carry on this paper.

    Four (due / paid / balance c/f, plus the description) is right on a full
    page and unreadable on a 99mm band — the columns end up two characters
    wide, which is how a "smaller" receipt becomes an illegible one.
    """
    return 4 if flow_of(layout) == FLOW_FULL else 2


def to_public_dict() -> dict:
    """The option catalogue the settings screen renders."""
    return {
        "papers": [
            {"key": key, **{k: v for k, v in spec_.items()}}
            for key, spec_ in PAPERS.items()
        ],
        "components": [{"key": k, "label": v} for k, v in COMPONENTS.items()],
        "slots": list(SLOTS),
        "densities": list(DENSITIES),
        "sections": list(SECTIONS),
        "default": DEFAULT_LAYOUT,
        # Said once, here, so the settings screen and the docs cannot drift:
        # this is the single most common reason a correct layout prints wrong.
        "print_note": (
            "Print at Actual size (100%), not Fit to page. The PDF is generated "
            "at exactly the size you choose, so 'Fit to page' scales it onto the "
            "sheet and surrounds it with white margin."
        ),
    }
