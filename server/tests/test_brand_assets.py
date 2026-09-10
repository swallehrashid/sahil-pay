"""
The logo and signature pipeline, end to end: upload → stored → on the document.

WHY THIS FILE EXISTS
--------------------
A landlord uploaded a company logo, the settings page said "Settings saved",
and the logo appeared on nothing. Every individual piece was working:
storage_service optimised and stored brand images correctly, report_builder and
receipt_layout both drew `landlord.logo_url` when it was set, and
test_document_branding.py proved the rendering by setting the column directly.

The break was in the one seam nothing covered — the client sent the file inside
a JSON body. `JSON.stringify({logo: File})` produces `{"logo":{}}`, so the
request succeeded with an empty object where the file should have been, the
server's multipart branch never ran, and no layer had any reason to complain.

So these tests exercise the seam: a real multipart POST at the route, then the
rendered document. Setting logo_url directly would pass while the feature is
broken, which is exactly what happened.
"""

import io
import uuid

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import Landlord, LandlordSettings, User

def _uniq():
    """
    A fresh identity per RUN, not per test.

    These fixtures commit, and the db_session fixture's rollback cannot undo a
    commit — so rows outlive the test that made them and are still in
    sahilpay_test the next time the suite runs. A counter therefore produces
    `brand0@test.sahilpay` on every run and collides with itself the second
    time, which shows up as an unrelated-looking UniqueViolation at setup.
    Random suffixes are what the rest of the suite uses for exactly this reason.
    """
    return uuid.uuid4().hex[:10]


@pytest.fixture()
def client(app):
    return app.test_client()


def _png_bytes(width=800, height=200, color=(20, 30, 90)):
    """A real image, because storage_service runs it through Pillow."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def account(db_session):
    n = _uniq()
    user = User(email=f"brand-{n}@test.sahilpay", phone=f"2547{n[:9]}",
                password_hash=generate_password_hash("Testpass1"),
                role="landlord", is_verified=True, is_active=True)
    db_session.add(user)
    db_session.flush()
    landlord = Landlord(user_id=user.id, company_name=f"Brand Test Ltd {n}",
                        currency="KES", company_address="P.O. Box 9, Nairobi")
    db_session.add(landlord)
    db_session.flush()
    db_session.add(LandlordSettings(landlord_id=landlord.id,
                                    sms_enabled=True, email_enabled=True))
    db_session.commit()
    return {"user": user, "landlord": landlord}


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(identity=str(user.id), additional_claims={'role': user.role})}"}


# ---------------------------------------------------------------------------
# The seam that was broken
# ---------------------------------------------------------------------------

def test_a_multipart_logo_upload_is_actually_stored(client, account, db_session):
    """The whole bug in one assertion: after a save, the column is set."""
    response = client.put(
        "/api/settings/general",
        headers=_auth(account["user"]),
        data={
            "company_name": account["landlord"].company_name,
            "logo": (io.BytesIO(_png_bytes()), "company-logo.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    db_session.refresh(account["landlord"])
    assert account["landlord"].logo_url, "the logo was accepted and stored nowhere"


def test_a_json_body_cannot_smuggle_a_logo(client, account, db_session):
    """
    Documents the original failure so it cannot quietly come back. A JSON body
    has no file in it — whatever `logo` holds, the save must not invent one.
    The client is responsible for sending multipart; this proves the server
    does not paper over it by accepting something that is not a file.
    """
    response = client.put(
        "/api/settings/general",
        headers=_auth(account["user"]),
        json={"company_name": account["landlord"].company_name, "logo": {}},
    )

    assert response.status_code == 200
    db_session.refresh(account["landlord"])
    assert not account["landlord"].logo_url


def test_a_multipart_signature_upload_is_stored(client, account, db_session):
    response = client.put(
        "/api/settings/account",
        headers=_auth(account["user"]),
        data={"signature": (io.BytesIO(_png_bytes(900, 220)), "signature.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    db_session.refresh(account["landlord"])
    assert account["landlord"].signature_url


def test_an_empty_file_part_does_not_wipe_a_saved_logo(client, account, db_session):
    """
    A browser submits an empty file part for an untouched <input type=file>.
    Treating that as "the user cleared their logo" would delete the logo of
    anyone who edits their address and saves.
    """
    account["landlord"].logo_url = "/uploads/logos/9/existing.jpg"
    db_session.commit()

    response = client.put(
        "/api/settings/general",
        headers=_auth(account["user"]),
        data={"company_address": "New address", "logo": (io.BytesIO(b""), "")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    db_session.refresh(account["landlord"])
    assert account["landlord"].logo_url == "/uploads/logos/9/existing.jpg"


# ---------------------------------------------------------------------------
# The regression the fix could have introduced
# ---------------------------------------------------------------------------

def test_multipart_booleans_are_coerced_not_assigned_raw(client, account, db_session):
    """
    Multipart makes every value a STRING. `sms_enabled=false` arrives as the
    string "false", which is truthy in Python — so a landlord who unticked
    "send SMS" while uploading a logo would have had SMS silently left on, and
    then been billed for messages they told us not to send.
    """
    settings = account["landlord"].landlord_settings
    assert settings.sms_enabled is True

    response = client.put(
        "/api/settings/general",
        headers=_auth(account["user"]),
        data={
            "sms_enabled": "false",
            "email_enabled": "true",
            "logo": (io.BytesIO(_png_bytes()), "logo.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    db_session.refresh(settings)
    assert settings.sms_enabled is False, "\"false\" was assigned raw and is truthy"
    assert settings.email_enabled is True


def test_a_multipart_number_is_coerced(client, account, db_session):
    response = client.put(
        "/api/settings/general",
        headers=_auth(account["user"]),
        data={"low_sms_balance_threshold": "25",
              "logo": (io.BytesIO(_png_bytes()), "logo.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    db_session.refresh(account["landlord"].landlord_settings)
    assert account["landlord"].landlord_settings.low_sms_balance_threshold == 25


def test_a_json_save_still_works(client, account, db_session):
    """The ordinary no-file save must keep the plain JSON path."""
    response = client.put(
        "/api/settings/general",
        headers=_auth(account["user"]),
        json={"company_address": "Plot 5, Westlands", "sms_enabled": False},
    )

    assert response.status_code == 200
    db_session.refresh(account["landlord"])
    assert account["landlord"].company_address == "Plot 5, Westlands"
    assert account["landlord"].landlord_settings.sms_enabled is False


# ---------------------------------------------------------------------------
# ...and that it reaches the documents
# ---------------------------------------------------------------------------

@pytest.fixture()
def captured_html(monkeypatch):
    seen = {}

    def fake_render_pdf(html, base_url=None):
        seen["html"] = html
        return b"%PDF-1.4 stub"

    import utils
    monkeypatch.setattr(utils, "render_pdf", fake_render_pdf)
    for module_name in ("services.report_builder", "services.receipt_service",
                        "services.pdf_service", "services.lease_service"):
        module = __import__(module_name, fromlist=["render_pdf"])
        if hasattr(module, "render_pdf"):
            monkeypatch.setattr(module, "render_pdf", fake_render_pdf)
    return seen


def test_an_uploaded_logo_reaches_a_receipt(client, account, db_session, captured_html):
    """Upload through the ROUTE, then render — the two halves joined up."""
    client.put(
        "/api/settings/general",
        headers=_auth(account["user"]),
        data={"logo": (io.BytesIO(_png_bytes()), "logo.png")},
        content_type="multipart/form-data",
    )
    db_session.refresh(account["landlord"])
    stored = account["landlord"].logo_url
    assert stored

    from services import receipt_layout as rl
    from services import receipt_service as rs

    rs.render_sample_receipt_pdf(account["landlord"], rl.DEFAULT_LAYOUT)

    assert stored in captured_html["html"], "the receipt does not carry the uploaded logo"


def test_an_uploaded_logo_and_signature_reach_a_report(client, account, db_session, captured_html):
    client.put(
        "/api/settings/general",
        headers=_auth(account["user"]),
        data={"logo": (io.BytesIO(_png_bytes()), "logo.png")},
        content_type="multipart/form-data",
    )
    client.put(
        "/api/settings/account",
        headers=_auth(account["user"]),
        data={"signature": (io.BytesIO(_png_bytes(900, 220)), "sig.png")},
        content_type="multipart/form-data",
    )
    db_session.refresh(account["landlord"])
    logo_url = account["landlord"].logo_url
    signature_url = account["landlord"].signature_url
    assert logo_url and signature_url

    from services import report_builder as rb

    meta = rb.build_meta(account["landlord"], report_title="Rent Roll", period="Sept 2026")
    assert meta["logo_url"] == logo_url
    assert meta["signature_url"] == signature_url

    letterhead = rb._letterhead_html(meta)
    assert logo_url in letterhead
    assert signature_url in rb._signature_html(meta)


# ---------------------------------------------------------------------------
# The account profile fields that never persisted
# ---------------------------------------------------------------------------

def test_the_account_page_says_which_fields_it_can_save(client, account):
    """
    `users` has no name columns — a landlord's identity is their company name.
    The page used to render Username / First name / Last name inputs anyway,
    which came up blank and discarded anything typed into them. The server now
    states what it will actually write so the client can stop offering the rest.
    """
    response = client.get("/api/settings/account", headers=_auth(account["user"]))

    assert response.status_code == 200
    body = response.get_json()
    assert "editable_fields" in body
    assert "email" in body["editable_fields"]
    # A landlord has no TeamMember/SystemAdmin profile row to hold a name.
    assert "first_name" not in body["editable_fields"]
    assert body["company_name"] == account["landlord"].company_name


def test_email_and_phone_still_persist(client, account, db_session):
    response = client.put(
        "/api/settings/account",
        headers=_auth(account["user"]),
        json={"email": f"changed-{_uniq()}@test.sahilpay", "phone": "254799123456"},
    )

    assert response.status_code == 200
    db_session.refresh(account["user"])
    assert account["user"].email.startswith("changed-")
    assert account["user"].phone == "254799123456"
