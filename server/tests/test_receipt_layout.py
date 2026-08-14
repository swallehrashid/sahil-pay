"""
Phase 9 — the receipt layout designer.

Landlords print on whatever they have: a thermal roll at the gate, three slips
down an A4 sheet, or the full page. The layout is theirs to choose — but a
choice must never be able to produce a receipt that fails to render, and a
landlord who never opens the screen must keep exactly the receipt they have.
"""

import json

import pytest

from services import receipt_layout as rl


# ---------------------------------------------------------------------------
# Validation — a bad value must degrade, never break
# ---------------------------------------------------------------------------

def test_default_is_the_original_a4_receipt():
    layout = rl.normalise(None)
    assert layout["paper"] == "a4"
    assert layout["header_slots"] == {
        "left": "logo", "center": "letterhead", "right": "address",
    }
    assert layout["density"] == "normal"
    assert layout["font_scale"] == 1.0


@pytest.mark.parametrize("junk", [
    None, "", "not json", "{]", 12, [], {"paper": "papyrus"},
    {"header_slots": "nonsense"}, {"font_scale": "big"}, {"density": "airy"},
])
def test_anything_unusable_falls_back_to_the_default(junk):
    """
    A corrupted or hand-edited value must produce the standard receipt — never
    an exception at the moment a tenant asks for their receipt.
    """
    layout = rl.normalise(junk)
    assert layout["paper"] in rl.PAPERS
    assert layout["density"] in rl.DENSITIES
    assert 0.8 <= layout["font_scale"] <= 1.25


def test_font_scale_is_clamped():
    assert rl.normalise({"font_scale": 99})["font_scale"] == 1.25
    assert rl.normalise({"font_scale": 0.1})["font_scale"] == 0.8


def test_a_component_cannot_be_placed_in_two_slots():
    """The same logo drawn twice is a mistake, not a layout."""
    layout = rl.normalise({
        "header_slots": {"left": "logo", "center": "logo", "right": "address"},
    })
    placed = [v for v in layout["header_slots"].values() if v]
    assert placed.count("logo") == 1


def test_unknown_components_are_dropped():
    layout = rl.normalise({
        "header_slots": {"left": "watermark", "center": "letterhead", "right": None},
    })
    assert layout["header_slots"]["left"] is None
    assert layout["header_slots"]["center"] == "letterhead"


# ---------------------------------------------------------------------------
# Paper sizes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("paper", list(rl.PAPERS))
def test_every_paper_produces_usable_css(paper):
    css = rl.page_css(rl.normalise({"paper": paper}))
    assert "@page" in css and "size:" in css


def test_thermal_roll_has_no_fixed_height():
    """
    A till roll is continuous stationery. A fixed height would either cut a long
    receipt off or spit out blank paper after a short one.
    """
    css = rl.page_css(rl.normalise({"paper": "thermal_80"}))
    assert "80mm auto" in css


def test_compact_density_tightens_the_page():
    normal = rl.page_css(rl.normalise({"density": "normal"}))
    compact = rl.page_css(rl.normalise({"density": "compact"}))
    assert normal != compact
    assert "2px 4px" in compact, "compact should reduce row padding"


# ---------------------------------------------------------------------------
# Header rendering
# ---------------------------------------------------------------------------

META = {
    "company_name": "Riverside Apartments Ltd",
    "report_title": "Payment Receipt",
    "company_address": "Kilimani, Nairobi",
    "logo_url": "https://example.test/logo.png",
    "phone": "+254700000000",
    "email": "accounts@example.test",
}


def test_header_renders_components_in_the_chosen_slots():
    html = rl.header_html(
        rl.normalise({"header_slots": {"left": "address", "center": "logo", "right": "letterhead"}}),
        META,
    )
    # Address must appear before the logo, which appears before the letterhead.
    assert html.index("Kilimani") < html.index("logo.png") < html.index("Riverside")


def test_hidden_components_are_not_drawn():
    html = rl.header_html(rl.normalise({"hidden_components": ["logo"]}), META)
    assert "logo.png" not in html
    assert "Riverside" in html, "hiding the logo must not hide everything else"


def test_header_survives_a_landlord_with_no_logo_or_address():
    html = rl.header_html(rl.normalise(None), {"company_name": "Small Landlord"})
    assert "Small Landlord" in html
    assert "<table" in html, "the header must still render a valid structure"


def test_header_escapes_company_details():
    """A company name is user input and ends up in HTML."""
    html = rl.header_html(rl.normalise(None), {**META, "company_name": '<script>x</script>'})
    assert "<script>" not in html


# ---------------------------------------------------------------------------
# Option catalogue + persistence shape
# ---------------------------------------------------------------------------

def test_option_catalogue_describes_every_choice():
    options = rl.to_public_dict()
    assert {p["key"] for p in options["papers"]} == set(rl.PAPERS)
    assert {c["key"] for c in options["components"]} == set(rl.COMPONENTS)
    assert options["default"]["paper"] == "a4"
    for paper in options["papers"]:
        assert paper["label"] and paper["description"], (
            "every paper option needs a label and an explanation — the landlord "
            "is choosing stationery, not a config key"
        )


def test_a_saved_layout_round_trips():
    chosen = {
        "paper": "thermal_80",
        "header_slots": {"left": "letterhead", "center": None, "right": None},
        "density": "compact",
        "font_scale": 0.9,
        "sections": {"deposits": False, "notes": False, "signature": False, "balance": True},
    }
    stored = json.dumps(rl.normalise(chosen))
    restored = rl.normalise(stored)

    assert restored["paper"] == "thermal_80"
    assert restored["density"] == "compact"
    assert restored["font_scale"] == 0.9
    assert restored["sections"]["deposits"] is False
    assert restored["sections"]["balance"] is True
