"""
The two colours a landlord's documents are drawn in.

The rule that matters most is the one about REPORTS: a landlord who picks their
brand colours must see them on statements and rent rolls too, not only on
receipts. A statement in Sahil Pay's violet handed to a property owner
alongside a receipt in the landlord's own green is worse than offering no
choice at all — it looks like two companies produced them.
"""

import pytest

from services import receipt_theme as rt
from services import report_builder as rb


# ---------------------------------------------------------------------------
# The palette
# ---------------------------------------------------------------------------

def test_there_are_at_least_thirty_colours():
    assert len(rt.PALETTE) >= 30


def test_every_palette_entry_is_distinct_and_well_formed():
    keys = [c["key"] for c in rt.PALETTE]
    hexes = [c["hex"].lower() for c in rt.PALETTE]

    assert len(set(keys)) == len(keys), "duplicate palette keys"
    assert len(set(hexes)) == len(hexes), "duplicate palette colours"
    for entry in rt.PALETTE:
        assert rt._HEX_RE.match(entry["hex"]), entry
        assert entry["label"] and entry["family"]


def test_every_palette_colour_is_dark_enough_to_read_on_white():
    """
    These are printed on white paper on an office laser and then photographed by
    a tenant. A pastel that looks fine on a backlit screen fails all three. The
    threshold is relative luminance — a colour needs roughly 4.5:1 against white
    to stay legible as body text.
    """
    for entry in rt.PALETTE:
        r, g, b = (int(entry["hex"][i:i + 2], 16) / 255 for i in (1, 3, 5))
        channel = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
        luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
        contrast = 1.05 / (luminance + 0.05)
        assert contrast >= 4.5, \
            f"{entry['label']} ({entry['hex']}) is only {contrast:.1f}:1 on white"


# ---------------------------------------------------------------------------
# Validation — a landlord cannot produce an unreadable document
# ---------------------------------------------------------------------------

def test_a_colour_outside_the_palette_is_refused():
    """Free-form hex is how you get yellow text on white paper."""
    theme = rt.normalise({"primary": "#ffff00", "secondary": "#ffffff"})

    assert theme["primary"] == rt.DEFAULT_PRIMARY
    assert theme["secondary"] == rt.DEFAULT_SECONDARY


def test_a_palette_key_or_a_palette_hex_both_work():
    by_key = rt.normalise({"primary": "teal", "secondary": "amber_deep"})
    by_hex = rt.normalise({"primary": "#0f766e", "secondary": "#b45309"})

    assert by_key == by_hex


def test_two_identical_colours_are_separated():
    """One colour means no accent — every rule and total vanishes into the
    body text, and the document loses all its structure."""
    theme = rt.normalise({"primary": "navy", "secondary": "navy"})

    assert theme["primary"] != theme["secondary"]


@pytest.mark.parametrize("garbage", [None, "", "not json", 42, [], {"primary": None}])
def test_anything_unusable_degrades_to_the_default(garbage):
    """A corrupted value must produce the standard document, never a 500 when
    somebody asks for a receipt."""
    assert rt.normalise(garbage) == rt.DEFAULT_THEME


def test_no_theme_at_all_is_the_sahil_pay_default():
    """Every existing account has NULL here and must be unaffected."""
    assert rt.resolve() == {"primary": rt.DEFAULT_PRIMARY, "secondary": rt.DEFAULT_SECONDARY}


# ---------------------------------------------------------------------------
# Derived fills
# ---------------------------------------------------------------------------

def test_tint_moves_towards_white():
    assert rt.tint("#000000", 0.0) == "#000000"
    assert rt.tint("#000000", 1.0) == "#ffffff"
    assert rt.tint("#000000", 0.5) == "#808080"


def test_tint_survives_a_bad_input():
    assert rt.tint("banana", 0.5).startswith("#")


# ---------------------------------------------------------------------------
# It has to reach REPORTS, not only receipts
# ---------------------------------------------------------------------------

def test_a_report_is_drawn_in_the_landlords_colours():
    css = rb.report_style({"primary": "teal", "secondary": "amber_deep"})

    assert "#0f766e" in css, "the report is not using the landlord's primary"
    assert "#b45309" in css, "the report is not using the landlord's secondary"
    assert "#200497" not in css, "the Sahil Pay violet is still hard-coded in reports"


def test_a_report_with_no_theme_is_unchanged():
    """The default stylesheet must be byte-identical to what it always was, or
    every existing account's documents change appearance on deploy."""
    assert rb.report_style() == rb.report_style(None)
    assert "#0f0246" in rb.report_style()


def test_a_receipt_is_drawn_in_the_same_colours_as_a_report():
    """
    The whole point. A receipt and a statement from the same landlord must not
    come out in different colours.
    """
    from services import receipt_layout as rl

    theme = {"primary": "crimson", "secondary": "bronze"}
    receipt_css = rl.page_css(rl.normalise({"paper": "a4"}), theme)
    report_css = rb.report_style(theme)

    for colour in ("#b91c1c", "#92400e"):
        assert colour in receipt_css, f"{colour} missing from the receipt"
        assert colour in report_css, f"{colour} missing from the report"


def test_the_public_catalogue_is_renderable():
    catalogue = rt.to_public_dict()

    assert len(catalogue["palette"]) >= 30
    assert catalogue["families"], "the picker needs colours grouped into families"
    assert set(catalogue["default"]) == {"primary", "secondary"}
    assert set(catalogue["roles"]) == {"primary", "secondary"}


# ---------------------------------------------------------------------------
# The settings API
# ---------------------------------------------------------------------------

import uuid

from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from models import Landlord, LandlordSettings, User

def _uniq():
    """See the note in tests/test_brand_assets.py — these fixtures commit, so
    identities must be unique per RUN, not merely per test."""
    return uuid.uuid4().hex[:10]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def account(db_session):
    n = _uniq()
    user = User(email=f"theme-{n}@test.sahilpay", phone=f"2547{n[:9]}",
                password_hash=generate_password_hash("Testpass1"),
                role="landlord", is_verified=True, is_active=True)
    db_session.add(user)
    db_session.flush()
    landlord = Landlord(user_id=user.id, company_name=f"Theme Ltd {n}", currency="KES")
    db_session.add(landlord)
    db_session.flush()
    db_session.add(LandlordSettings(landlord_id=landlord.id))
    db_session.commit()
    return {"user": user, "landlord": landlord}


def _auth(user):
    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
    return {"Authorization": f"Bearer {token}"}


def test_the_settings_endpoint_offers_the_palette(client, account):
    response = client.get("/api/settings/receipt-layout", headers=_auth(account["user"]))

    assert response.status_code == 200
    body = response.get_json()
    assert len(body["palette"]["palette"]) >= 30
    assert body["theme"] == rt.DEFAULT_THEME
    assert body["theme_is_default"] is True
    # Both papers the landlord asked to be able to choose between.
    papers = {p["key"] for p in body["options"]["papers"]}
    assert {"a4_third_band", "a4_third_slip"} <= papers


def test_a_saved_theme_persists(client, account, db_session):
    response = client.put(
        "/api/settings/receipt-layout",
        headers=_auth(account["user"]),
        json={"layout": {"paper": "a4_third_band"},
              "theme": {"primary": "emerald", "secondary": "bronze"}},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    settings = account["landlord"].landlord_settings
    db_session.refresh(settings)
    assert settings.theme_primary == "#047857"
    assert settings.theme_secondary == "#92400e"

    again = client.get("/api/settings/receipt-layout", headers=_auth(account["user"])).get_json()
    assert again["theme"] == {"primary": "#047857", "secondary": "#92400e"}
    assert again["theme_is_default"] is False
    assert again["layout"]["paper"] == "a4_third_band"


def test_saving_a_layout_without_a_theme_leaves_the_theme_alone(client, account, db_session):
    """A screen that does not offer colours must not reset somebody's palette."""
    client.put("/api/settings/receipt-layout", headers=_auth(account["user"]),
               json={"theme": {"primary": "crimson", "secondary": "teal"}})

    client.put("/api/settings/receipt-layout", headers=_auth(account["user"]),
               json={"layout": {"paper": "thermal_80"}})

    settings = account["landlord"].landlord_settings
    db_session.refresh(settings)
    assert settings.theme_primary == "#b91c1c", "the theme was reset by a layout-only save"


def test_a_colour_outside_the_palette_never_reaches_the_database(client, account, db_session):
    client.put("/api/settings/receipt-layout", headers=_auth(account["user"]),
               json={"theme": {"primary": "#ffff00", "secondary": "#fefefe"}})

    settings = account["landlord"].landlord_settings
    db_session.refresh(settings)
    assert settings.theme_primary == rt.DEFAULT_PRIMARY
    assert settings.theme_secondary == rt.DEFAULT_SECONDARY


def test_the_preview_uses_the_candidate_theme_without_saving_it(client, account, db_session):
    response = client.post(
        "/api/settings/receipt-layout/preview",
        headers=_auth(account["user"]),
        json={"layout": {"paper": "a4_third_band"},
              "theme": {"primary": "purple", "secondary": "ochre"}},
    )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF")

    settings = account["landlord"].landlord_settings
    db_session.refresh(settings)
    assert settings.theme_primary is None, "the preview saved the theme"
