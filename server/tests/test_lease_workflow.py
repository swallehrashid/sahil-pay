"""
The lease workflow end to end, as the tenant actually experiences it.

Covers what test_leases.py does not:
  * an OTP-only tenant (no User row) is notified — the bug that made the whole
    flow invisible from the tenant's side;
  * the three documents (standard / custom / uploaded) × the two ways to sign
    (in the portal / by hand and uploaded);
  * a person with more than one tenancy sees every lease, and nobody else's;
  * both sides can download the final copy, with the dates recorded.
"""

import io
from decimal import Decimal

import pytest

from models import LeaseStatus, Notification, Tenant, DocumentTemplate
from services import lease_service as leases
from tests.test_leases import world, client, _auth, _clean_lease_files  # noqa: F401


def _png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (400, 560), (250, 250, 250)).save(buf, format="PNG")
    return buf.getvalue()


def _pdf_bytes():
    from utils import render_pdf
    return render_pdf("<html><body><h1>Landlord's own lease</h1><p>Clause 1.</p></body></html>")


def test_an_otp_only_tenant_is_notified_when_a_lease_is_sent(client, db_session, world):
    tenant = world["tenants"][0]
    tenant.user_id = None                         # how real tenants sign in
    db_session.commit()

    res = client.post(f"/api/tenants/{tenant.id}/leases", headers=_auth(world["landlord_token"]),
                      json={"send": True})
    assert res.status_code == 201, res.get_data(as_text=True)
    lease_id = res.get_json()["data"]["id"]

    note = db_session.query(Notification).filter_by(entity_type="lease", entity_id=lease_id).first()
    assert note is not None and note.recipient_tenant_id == tenant.id

    # …and it is on THEIR bell.
    bell = client.get("/api/notifications", headers=_auth(world["tenant_tokens"][0]))
    assert bell.status_code == 200
    assert str(lease_id) in bell.get_data(as_text=True) or "lease" in bell.get_data(as_text=True).lower()


def test_the_tenant_lists_signs_and_downloads_in_the_portal(client, db_session, world):
    tenant = world["tenants"][0]
    token = world["tenant_tokens"][0]
    lease_id = client.post(f"/api/tenants/{tenant.id}/leases", headers=_auth(world["landlord_token"]),
                           json={"send": True}).get_json()["data"]["id"]

    listing = client.get("/api/portal/leases", headers=_auth(token)).get_json()["data"]
    assert listing["action_needed"] == 1
    assert listing["items"][0]["id"] == lease_id and listing["items"][0]["can_sign"]

    detail = client.get(f"/api/portal/leases/{lease_id}", headers=_auth(token)).get_json()["data"]
    assert "TENANCY AGREEMENT" in detail["body_html"]
    assert detail["viewed_at"] is not None

    blank = client.get(f"/api/portal/leases/{lease_id}/blank", headers=_auth(token))
    assert blank.status_code == 200 and blank.data[:5] == b"%PDF-"

    signed = client.post(f"/api/portal/leases/{lease_id}/sign", headers=_auth(token),
                         json={"signed_name": "Ten0 Test", "agreed": True})
    assert signed.status_code == 200, signed.get_data(as_text=True)
    assert signed.get_json()["data"]["status"] == LeaseStatus.submitted.value

    # Not downloadable by the tenant until approved; reviewable by staff.
    assert client.get(f"/api/portal/leases/{lease_id}/download", headers=_auth(token)).status_code == 409
    assert client.get(f"/api/leases/{lease_id}/download",
                      headers=_auth(world["landlord_token"])).status_code == 200

    assert client.post(f"/api/leases/{lease_id}/approve",
                       headers=_auth(world["landlord_token"])).status_code == 200
    final = client.get(f"/api/portal/leases/{lease_id}/download", headers=_auth(token))
    assert final.status_code == 200 and final.data[:5] == b"%PDF-"

    row = client.get(f"/api/leases/{lease_id}", headers=_auth(world["landlord_token"])).get_json()["data"]
    assert row["signed_at"] and row["reviewed_at"] and row["sent_at"] and row["signing_method"] == "electronic"


def test_a_hand_signed_scan_goes_through_review_to_a_final_copy(client, db_session, world):
    tenant = world["tenants"][0]
    token = world["tenant_tokens"][0]
    lease_id = client.post(f"/api/tenants/{tenant.id}/leases", headers=_auth(world["landlord_token"]),
                           json={"send": True}).get_json()["data"]["id"]

    res = client.post(
        f"/api/portal/leases/{lease_id}/upload", headers=_auth(token),
        data={"signed_name": "Ten0 Test", "agreed": "true",
              "files": [(io.BytesIO(_png_bytes()), "page1.png"), (io.BytesIO(_png_bytes()), "page2.png")]},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()["data"]
    assert data["status"] == "submitted" and data["signing_method"] == "scan" and data["scan_page_count"] == 2

    # The office can look at each page it is reviewing.
    page = client.get(f"/api/leases/{lease_id}/scans/0", headers=_auth(world["landlord_token"]))
    assert page.status_code == 200 and page.data[:4] == b"\x89PNG"

    assert client.post(f"/api/leases/{lease_id}/approve",
                       headers=_auth(world["landlord_token"])).status_code == 200
    final = client.get(f"/api/portal/leases/{lease_id}/download", headers=_auth(token))
    assert final.status_code == 200
    from pypdf import PdfReader
    assert len(PdfReader(io.BytesIO(final.data)).pages) >= 3   # certificate + two pages


def test_an_uploaded_lease_document_is_sent_and_printed_with_a_cover(client, db_session, world):
    tenant = world["tenants"][0]
    res = client.post(
        f"/api/tenants/{tenant.id}/leases", headers=_auth(world["landlord_token"]),
        data={"send": "true", "title": "Riverside lease 2026",
              "file": (io.BytesIO(_pdf_bytes()), "our-lease.pdf")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 201, res.get_data(as_text=True)
    data = res.get_json()["data"]
    assert data["document_kind"] == "uploaded" and data["title"] == "Riverside lease 2026"

    blank = client.get(f"/api/portal/leases/{data['id']}/blank", headers=_auth(world["tenant_tokens"][0]))
    assert blank.status_code == 200
    from pypdf import PdfReader
    pages = PdfReader(io.BytesIO(blank.data)).pages
    assert len(pages) >= 3                        # cover + their page + signature page


def test_a_stored_file_template_is_sent_as_the_landlords_document(db_session, world):
    """A template holding only a FILE used to quietly send the standard lease."""
    from services.storage_service import upload_to_s3
    tenant = world["tenants"][0]
    url = upload_to_s3(io.BytesIO(_pdf_bytes()), folder="documents/test", filename="lease.pdf",
                       profile="document", force_local=True)
    tmpl = DocumentTemplate(landlord_id=tenant.landlord_id, name="Our paper lease", file_url=url,
                            document_type="lease")
    db_session.add(tmpl)
    db_session.flush()

    lease = leases.create_for_tenant(tenant, template_id=tmpl.id)
    assert lease.document_kind == "uploaded" and lease.source_document_url == url
    assert lease.body_html is None


def test_a_custom_template_requires_choosing_one(db_session, world):
    from utils import ApiError
    with pytest.raises(ApiError):
        leases.create_for_tenant(world["tenants"][0], document_kind="custom")


def test_one_person_sees_leases_for_all_their_units_and_no_one_elses(client, db_session, world):
    first, other = world["tenants"]
    landlord_token = world["landlord_token"]
    # The same person rents a second unit (same phone) — a sibling tenancy.
    second = Tenant(landlord_id=first.landlord_id, unit_id=other.unit_id, first_name=first.first_name,
                    last_name=first.last_name, phone=first.phone, email=first.email,
                    account_number=f"{first.account_number}B", balance=Decimal("0"))
    db_session.add(second)
    db_session.commit()

    a = client.post(f"/api/tenants/{first.id}/leases", headers=_auth(landlord_token), json={"send": True})
    b = client.post(f"/api/tenants/{second.id}/leases", headers=_auth(landlord_token), json={"send": True})
    c = client.post(f"/api/tenants/{other.id}/leases", headers=_auth(landlord_token), json={"send": True})
    ids = {a.get_json()["data"]["id"], b.get_json()["data"]["id"]}
    stranger = c.get_json()["data"]["id"]

    listing = client.get("/api/portal/leases", headers=_auth(world["tenant_tokens"][0])).get_json()["data"]
    assert {i["id"] for i in listing["items"]} == ids
    assert client.get(f"/api/portal/leases/{stranger}",
                      headers=_auth(world["tenant_tokens"][0])).status_code == 404


def test_send_many_gives_each_tenant_their_own_lease(client, db_session, world):
    ids = [t.id for t in world["tenants"]]
    res = client.post("/api/leases/send-many", headers=_auth(world["landlord_token"]),
                      json={"tenant_ids": ids})
    assert res.status_code == 201, res.get_data(as_text=True)
    items = res.get_json()["data"]["items"]
    assert sorted(i["tenant_id"] for i in items) == sorted(ids)
    assert all(i["status"] == "sent" for i in items)


def test_the_lease_pdf_carries_the_landlords_contact_details(db_session, world):
    landlord = world["landlord"]
    landlord.contact_phone = "0799 111 222"
    landlord.contact_email = "rent@leaseco.test"
    db_session.flush()
    lease = leases.create_for_tenant(world["tenants"][0])
    leases.send_to_tenant(lease)
    pdf = leases.render_blank_pdf(lease)
    from pypdf import PdfReader
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "0799 111 222" in text and "rent@leaseco.test" in text
    assert landlord.company_name in text


def test_script_in_a_custom_template_never_reaches_the_tenant(client, db_session, world):
    tenant = world["tenants"][0]
    tmpl = DocumentTemplate(landlord_id=tenant.landlord_id, name="Evil",
                            content='<h1>Lease</h1><img src=x onerror="alert(1)"><script>steal()</script><p>{tenant_name}</p>')
    db_session.add(tmpl)
    db_session.commit()
    lease_id = client.post(f"/api/tenants/{tenant.id}/leases", headers=_auth(world["landlord_token"]),
                           json={"template_id": tmpl.id, "send": True}).get_json()["data"]["id"]
    body = client.get(f"/api/portal/leases/{lease_id}",
                      headers=_auth(world["tenant_tokens"][0])).get_json()["data"]["body_html"]
    assert "<script" not in body and "onerror" not in body and "<img" not in body
    assert "<h1>Lease</h1>" in body and tenant.first_name in body
