"""
A receipt printed on a third of a page must BE a third of a page.

WHY THESE ASSERT ON THE RENDERED PDF
------------------------------------
The previous layout tests checked the generated CSS string, and every one of
them passed while thermal receipts were coming out on A4 — the stylesheet said
`size: 80mm auto`, which reads correctly and is invalid, so WeasyPrint threw the
declaration away without anyone noticing. A test that reads the CSS cannot see
that. These read the page box out of the PDF itself.

The two properties that matter, and that a landlord actually complained about:

  1. The page is the size that was asked for.
  2. The content FILLS it — it is rearranged into the rectangle, not shrunk and
     stranded in the middle of it with white margin on either side.

A note on (2): a full page, a tall slip and a till roll are all content-length
papers — a short receipt legitimately ends partway down and the rest is blank.
Only a BAND has a fixed height it is supposed to occupy, so only a band is held
to a fill ratio.
"""

import re
import subprocess

import pytest

from services import receipt_layout as rl
from services import receipt_service as rs

pytestmark = pytest.mark.usefixtures("app")

MM_PER_PT = 25.4 / 72


class _Landlord:
    company_name = "Mwangi Property Management Ltd"
    abbreviated_name = "MPM"
    company_address = "P.O. Box 4521-00100, Westlands, Nairobi"
    logo_url = None
    signature_url = None
    currency = "KES"
    mpesa_number = "247247"
    landlord_settings = None


def _render(paper, theme=None, tmp_path=None):
    layout = rl.normalise({"paper": paper})
    pdf = rs.render_sample_receipt_pdf(_Landlord(), layout, theme)
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


def _ink_extent(path):
    """(vertical, horizontal) fraction of the page the ink actually spans."""
    from PIL import Image

    subprocess.run(["pdftoppm", "-r", "110", "-png", "-singlefile",
                    str(path), str(path.with_suffix(""))], check=True)
    image = Image.open(path.with_suffix(".png")).convert("L")
    width, height = image.size
    px = image.load()
    rows = [y for y in range(height) if any(px[x, y] < 240 for x in range(0, width, 2))]
    cols = [x for x in range(width) if any(px[x, y] < 240 for y in range(0, height, 2))]
    assert rows and cols, "the receipt rendered blank"
    return (max(rows) + 1) / height, (max(cols) - min(cols) + 1) / width


# ---------------------------------------------------------------------------
# 1. The page is the size that was asked for
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("paper", list(rl.PAPERS))
def test_the_page_is_exactly_the_chosen_size(paper, tmp_path):
    spec = rl.PAPERS[paper]
    width, height, _ = _page_geometry(_render(paper, tmp_path=tmp_path))

    assert abs(width - spec["width_mm"]) <= 1, \
        f"{paper} asked for {spec['width_mm']}mm wide and got {width}mm"
    assert abs(height - spec["height_mm"]) <= 1, \
        f"{paper} asked for {spec['height_mm']}mm tall and got {height}mm"


@pytest.mark.parametrize("paper", list(rl.PAPERS))
def test_a_receipt_fits_on_one_page(paper, tmp_path):
    """
    The second page of a 99mm band is a near-empty slip that reads as a printing
    fault, so a receipt spilling onto one is a defect, not a detail.
    """
    _, _, pages = _page_geometry(_render(paper, tmp_path=tmp_path))
    assert pages == 1, f"{paper} produced {pages} pages"


def test_the_wide_band_is_wider_than_it_is_tall(tmp_path):
    """The landlord's own words: a third of a page is a RECTANGLE, full width
    and a third of the height — not an A4 receipt squeezed into a corner."""
    width, height, _ = _page_geometry(_render("a4_third_band", tmp_path=tmp_path))

    assert width == 210, "the band must span the full A4 width"
    assert 95 <= height <= 100, "the band must be one third of the A4 height"
    assert width > height


def test_the_tall_slip_is_taller_than_it_is_wide(tmp_path):
    """The other way of cutting a third, offered alongside rather than instead."""
    width, height, _ = _page_geometry(_render("a4_third_slip", tmp_path=tmp_path))

    assert width == 99 and height == 297
    assert height > width


def test_three_bands_stack_down_one_a4_sheet(tmp_path):
    """The point of the band: three of them come out of one sheet."""
    width, height, _ = _page_geometry(_render("a4_third_band", tmp_path=tmp_path))

    assert width == 210                      # the full A4 width
    assert abs(height * 3 - 297) <= 3        # three of them make a page


# ---------------------------------------------------------------------------
# 2. The content fills the rectangle
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("paper", ["a4_third_band", "a4_third_landscape"])
def test_a_band_is_filled_not_shrunk(paper, tmp_path):
    """
    THE ORIGINAL COMPLAINT. Choosing a smaller paper used to keep the same
    stacked arrangement and only shrink the type, leaving the receipt marooned
    in the middle of the paper with white down both sides. The content has to be
    rearranged into the rectangle it was given.
    """
    path = _render(paper, tmp_path=tmp_path)
    vertical, horizontal = _ink_extent(path)

    assert horizontal >= 0.90, \
        f"{paper} uses only {horizontal:.0%} of its width — the receipt is shrunk, not reflowed"
    assert vertical >= 0.75, \
        f"{paper} uses only {vertical:.0%} of its height — the band is mostly empty"


def test_a_band_lays_its_body_out_in_columns(tmp_path):
    """The mechanism behind the fill: three columns across, not one down."""
    layout = rl.normalise({"paper": "a4_third_band"})
    body = rl.compose_body(layout, {
        "details": "<p>D</p>", "charges": "<p>C</p>", "totals": "<p>T</p>",
        "notes": "", "etims": "", "signature": "", "credit": "",
    })

    assert "col-details" in body and "col-charges" in body and "col-totals" in body
    assert body.index("col-details") < body.index("col-charges") < body.index("col-totals")


def test_a_full_page_still_stacks(tmp_path):
    """A4 is unchanged — a landlord who never opens the screen sees no difference."""
    layout = rl.normalise({"paper": "a4"})
    body = rl.compose_body(layout, {
        "details": "<p>D</p>", "charges": "<p>C</p>", "totals": "<p>T</p>",
        "notes": "", "etims": "", "signature": "", "credit": "",
    })

    assert "col-charges" not in body


# ---------------------------------------------------------------------------
# 3. Not fitting is handled, rather than allowed to overflow
# ---------------------------------------------------------------------------

def test_a_band_caps_its_charge_rows_and_says_so():
    """
    A band cannot grow. A tenant with a dozen charges must not silently lose
    rows OFF the receipt, and must not push it onto a second band either — so
    the receipt trims and states what it trimmed.
    """
    layout = rl.normalise({"paper": "a4_third_band"})
    cap = rl.max_charge_rows(layout)
    assert cap and cap > 0

    rows = [{"description": f"Item {i}", "amount_due": 100,
             "paid_this_receipt": 100, "balance_cf": 0} for i in range(cap + 5)]
    html = rs._charge_groups_html([("Rent", rows)], "KES", 2, cap)

    assert "Item 0" in html
    assert f"+5 more items" in html, "trimmed rows must be accounted for"


def test_a_full_page_never_caps_rows():
    layout = rl.normalise({"paper": "a4"})
    assert rl.max_charge_rows(layout) is None

    rows = [{"description": f"Item {i}", "amount_due": 100,
             "paid_this_receipt": 100, "balance_cf": 0} for i in range(30)]
    html = rs._charge_groups_html([("Rent", rows)], "KES", 4, None)

    assert "Item 29" in html
    assert "more item" not in html


def test_a_small_paper_drops_to_two_money_columns():
    """
    Four money columns across a 99mm band leaves each about two characters
    wide. That is not a smaller receipt, it is an unreadable one.
    """
    assert rl.money_columns(rl.normalise({"paper": "a4"})) == 4
    assert rl.money_columns(rl.normalise({"paper": "a4_third_band"})) == 2
    assert rl.money_columns(rl.normalise({"paper": "thermal_80"})) == 2


# ---------------------------------------------------------------------------
# 4. Renaming a paper must not silently change anyone's receipt
# ---------------------------------------------------------------------------

def test_the_old_paper_key_still_resolves():
    """
    `a4_third_portrait` was the 99×210 slip before the wide band existed. Any
    landlord who saved it keeps a tall slip — quietly moving them to a different
    paper because we renamed a constant would be worse than the original bug.
    """
    layout = rl.normalise({"paper": "a4_third_portrait"})

    assert layout["paper"] == "a4_third_slip"
    assert rl.flow_of(layout) == rl.FLOW_COLUMN


def test_an_unknown_paper_falls_back_to_a4():
    assert rl.normalise({"paper": "papyrus"})["paper"] == "a4"
