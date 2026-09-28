"""
What is previewed is what prints.

WHY THESE ASSERT ON THE RENDERED PDF
------------------------------------
A test that reads the CSS cannot see what a printer will do with the result.
These read the page box out of the PDF and scan the rendered image for ink.

THE BUG THIS FILE EXISTS FOR
----------------------------
The "A4 third" receipt used to be a PDF whose page was 210 × 99 mm. A page wider
than it is tall is turned to landscape by every print dialog and scaled up to
fill an A4 sheet — so the owner's receipts came out rotated, covering the whole
page, with tiny text and huge gaps, while the preview (which shows the page as
it is) looked right. Photographs of both are in the September-2026 release notes.

So the properties that matter now:

  1. The PDF page IS the sheet in the printer — A4 portrait for every A4 paper
     (A4 landscape for the landscape band), 80 mm for a till roll. There is
     nothing left for a print dialog to rotate or rescale.
  2. The receipt stays in its place on that sheet: every mark of a top-third
     receipt is above the cut line, every mark of a strip is left of it.
  3. It fills its third: full width, and most of the height — not a strip of
     tiny text at the top.
  4. A busy receipt still fits; what does not is summarised, never cut off.
"""

import re
import subprocess

import pytest

from services import receipt_layout as rl
from services import receipt_service as rs

pytestmark = pytest.mark.usefixtures("app")

MM_PER_PT = 25.4 / 72


class _Landlord:
    company_name = "Rawa Estates and Managing Agents"
    abbreviated_name = "RAWA"
    company_address = "Anju Plaza, Opp Mathai Supermarket\nP.O Box 2932-10140"
    logo_url = None
    letterhead_url = None
    signature_url = None
    currency = "KES"
    mpesa_number = "0710351891"
    contact_phone = "0710 351 891"
    contact_email = "info@rawaestatesagent.com"
    website = "https://rawaestatesagent.com"
    landlord_settings = None
    user = None


def _render(paper, tmp_path, data=None):
    layout = rl.normalise({"paper": paper})
    if data is None:
        pdf = rs.render_sample_receipt_pdf(_Landlord(), layout, None)
    else:
        from services import receipt_theme
        pdf = rs._render(_Landlord(), layout, receipt_theme.resolve(None), data)
    path = tmp_path / f"{paper}.pdf"
    path.write_bytes(pdf)
    return path


def _page_geometry(path):
    """(width_mm, height_mm, page_count) straight out of the PDF."""
    info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
    size = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", info)
    pages = re.search(r"Pages:\s+(\d+)", info)
    assert size and pages, f"pdfinfo could not read the document:\n{info}"
    return (round(float(size.group(1)) * MM_PER_PT),
            round(float(size.group(2)) * MM_PER_PT),
            int(pages.group(1)))


def _ink(path, dpi=110):
    """(image, [(x, y) of ink]) — ink is anything darker than the paper, ignoring the grey cut line."""
    from PIL import Image
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-singlefile",
                    str(path), str(path.with_suffix(""))], check=True)
    image = Image.open(path.with_suffix(".png")).convert("L")
    return image


def _ink_box_mm(image, dpi=110, threshold=140):
    """Bounding box (left, top, right, bottom) in mm of DARK ink (text, rules, tables)."""
    w, h = image.size
    px = image.load()
    rows = [y for y in range(h) if any(px[x, y] < threshold for x in range(0, w, 2))]
    cols = [x for x in range(w) if any(px[x, y] < threshold for y in range(0, h, 2))]
    assert rows and cols, "the receipt rendered blank"
    mm = 25.4 / dpi
    return min(cols) * mm, min(rows) * mm, (max(cols) + 1) * mm, (max(rows) + 1) * mm


def _busy_data(rows=10, owed=5):
    def row(i):
        return {"description": f"Charge {i}", "item": f"Charge {i}", "month": "2026-09-01",
                "month_label": "September 2026", "invoice_number": "X", "is_deposit": False,
                "amount_due": 1000.0, "paid_this_receipt": 1000.0, "balance_cf": 0.0}
    return {
        "payment_ref": "PAY-6-000070", "payment_date": "2026-09-25", "method": "M-Pesa (Co-pilot)",
        "reference": "UIPRH7P2U5", "tenant_name": "Jonah Alex Mwendwa", "unit_name": "MN 4",
        "property_name": "Kingongo Court", "currency": "KES", "period_label": "September 2026",
        "rent_section": [row(i) for i in range(rows)], "utilities_section": [],
        "deposits_section": [], "other_section": [],
        "outstanding_items": [{"base": f"Owed {i}", "label": f"Owed {i} — October 2026",
                               "month": "2026-10-01", "amount": 500.0} for i in range(owed)],
        "total_due": rows * 1000.0 + owed * 500, "amount_paid": rows * 1000.0,
        "advance_credit": 0.0, "balance_remaining": owed * 500.0, "deposit_held_total": 6000.0,
    }


# ---------------------------------------------------------------------------
# 1. The PDF page is the sheet in the printer
# ---------------------------------------------------------------------------

SHEETS = {
    "a4": (210, 297),
    "a4_third_band": (210, 297),
    "a4_third_slip": (210, 297),
    "a4_third_landscape": (297, 210),
    "thermal_80": (80, 297),
}


@pytest.mark.parametrize("paper", list(rl.PAPERS))
def test_the_pdf_page_is_the_physical_sheet(paper, tmp_path):
    width, height, pages = _page_geometry(_render(paper, tmp_path))
    assert (width, height) == SHEETS[paper], f"{paper}: {width}×{height} mm"
    assert pages == 1


def test_the_top_third_receipt_is_a_portrait_page(tmp_path):
    """THE complaint: it must never be a landscape-shaped page a dialog will rotate."""
    width, height, _ = _page_geometry(_render("a4_third_band", tmp_path))
    assert height > width


# ---------------------------------------------------------------------------
# 2 + 3. It stays in its third, and fills it
# ---------------------------------------------------------------------------

def test_the_top_third_receipt_stays_above_the_cut_and_fills_the_width(tmp_path):
    left, top, right, bottom = _ink_box_mm(_ink(_render("a4_third_band", tmp_path)))
    assert bottom <= 99, f"ink runs to {bottom:.0f} mm — past the cut line at 99 mm"
    assert right - left >= 0.9 * 210, "the receipt must use the full width of the sheet"
    assert bottom >= 0.55 * 99, "the receipt should fill its third, not sit as a strip at the top"


def test_a_busy_receipt_still_fits_above_the_cut(tmp_path):
    path = _render("a4_third_band", tmp_path, _busy_data(rows=12, owed=6))
    _, _, pages = _page_geometry(path)
    _, _, _, bottom = _ink_box_mm(_ink(path))
    assert pages == 1 and bottom <= 99


def test_the_landscape_band_stays_in_its_third(tmp_path):
    path = _render("a4_third_landscape", tmp_path, _busy_data(rows=12, owed=6))
    _, _, _, bottom = _ink_box_mm(_ink(path))
    assert bottom <= 70


def test_the_strip_stays_left_of_its_cut(tmp_path):
    left, _, right, _ = _ink_box_mm(_ink(_render("a4_third_slip", tmp_path)))
    assert right <= 70, f"ink runs to {right:.0f} mm — past the strip's cut at 70 mm"


# ---------------------------------------------------------------------------
# The arrangement
# ---------------------------------------------------------------------------

def test_a_band_lays_its_body_out_in_three_tables_across():
    layout = rl.normalise({"paper": "a4_third_band"})
    body = rl.compose_body(layout, {
        "details": "<p>D</p>", "charges": "<p>C</p>", "totals": "<p>T</p>",
        "notes": "", "etims": "", "signature": "", "credit": "",
    })
    assert body.index("col-details") < body.index("col-charges") < body.index("col-totals")


def test_a_full_page_still_stacks():
    layout = rl.normalise({"paper": "a4"})
    body = rl.compose_body(layout, {"details": "<p>D</p>", "charges": "<p>C</p>",
                                    "totals": "<p>T</p>"})
    assert "col-charges" not in body


# ---------------------------------------------------------------------------
# 4. Not fitting is summarised, never cut off
# ---------------------------------------------------------------------------

def test_a_band_caps_its_charge_rows_and_says_so():
    layout = rl.normalise({"paper": "a4_third_band"})
    cap = rl.max_charge_rows(layout)
    assert cap and cap > 0
    rows = [{"description": f"Item {i}", "item": f"Item {i}", "month": None,
             "amount_due": 100, "paid_this_receipt": 100, "balance_cf": 0} for i in range(cap + 5)]
    html = rs._charge_groups_html([("Rent", rows)], "KES", 2, cap)
    assert "Item 0" in html
    assert "+5 more items" in html


def test_a_full_page_never_caps_rows():
    layout = rl.normalise({"paper": "a4"})
    assert rl.max_charge_rows(layout) is None
    rows = [{"description": f"Item {i}", "item": f"Item {i}", "month": None,
             "amount_due": 100, "paid_this_receipt": 100, "balance_cf": 0} for i in range(30)]
    html = rs._charge_groups_html([("Rent", rows)], "KES", 4, None)
    assert "Item 29" in html and "more item" not in html


def test_a_small_paper_drops_to_two_money_columns():
    assert rl.money_columns(rl.normalise({"paper": "a4"})) == 4
    assert rl.money_columns(rl.normalise({"paper": "a4_third_band"})) == 2
    assert rl.money_columns(rl.normalise({"paper": "thermal_80"})) == 2


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def test_the_portrait_third_key_means_the_top_third_receipt():
    """
    Owners call the top-third receipt "the 1/3 page portrait layout", and an
    older build saved it as `a4_third_portrait`. It resolves to the top third
    of an upright A4 sheet.
    """
    layout = rl.normalise({"paper": "a4_third_portrait"})
    assert layout["paper"] == "a4_third_band"
    assert rl.flow_of(layout) == rl.FLOW_BAND


def test_an_unknown_paper_falls_back_to_a4():
    assert rl.normalise({"paper": "papyrus"})["paper"] == "a4"
