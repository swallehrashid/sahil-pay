"""
Every document that leaves the building carries the landlord's identity.

A statement, a receipt, a payout advice and a tenancy agreement are all shown to
somebody outside the company — an owner, a tenant, sometimes a court. An
unbranded one reads as a draft somebody typed, which is a poor showing for the
managing agent whose name should be on it.

These tests assert on the HTML handed to WeasyPrint rather than on the rendered
PDF. That is deliberate: it isolates the branding decision from the renderer, so
a failure here means "this document has no letterhead" and never "WeasyPrint
changed its font metrics".

The fallback rule matters as much as the happy path. A landlord who has not
uploaded a logo must still get a finished-looking document, so the Sahil Pay
mark fills the slot — but it must never read as if Sahil Pay were the party to
the agreement.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    ChargeCategory, Invoice, InvoiceStatus, Landlord, LandlordSettings, Payment,
    PaymentStatus, Property, Tenant, Unit, User,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def captured_html(monkeypatch):
    """Capture what each renderer would hand to WeasyPrint."""
    seen = {}

    def fake_render_pdf(html, base_url=None):
        seen["html"] = html
        return b"%PDF-1.4 stub"

    import utils
    monkeypatch.setattr(utils, "render_pdf", fake_render_pdf)
    # Modules that imported the symbol directly hold their own reference.
    for module_name in ("services.report_builder", "services.lease_service",
                        "services.receipt_service", "services.payout_pdf",
                        "services.pdf_service"):
        try:
            module = __import__(module_name, fromlist=["render_pdf"])
            if hasattr(module, "render_pdf"):
                monkeypatch.setattr(module, "render_pdf", fake_render_pdf)
        except ImportError:                                   # pragma: no cover
            pass
    return seen


@pytest.fixture()
def estate(app, db_session):
    s = db_session
    n = _uniq()

    owner = User(email=f"br-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()
    landlord = Landlord(user_id=owner.id, company_name=f"Mwangi Property Ltd {n}",
                        currency="KES", company_address="P.O. Box 123, Nairobi")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.add(ChargeCategory(landlord_id=landlord.id, name="Rent", kind="invoice",
                         is_metered=False))
    s.flush()

    prop = Property(landlord_id=landlord.id, name=f"Riverside {n}", city="Nairobi",
                    street_name="Ring Road")
    s.add(prop)
    s.flush()
    unit = Unit(landlord_id=landlord.id, property_id=prop.id, name=f"A{n[:3]}",
                rent_amount=Decimal("25000"))
    s.add(unit)
    s.flush()
    tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id,
                    first_name="Amina", last_name=n[:4],
                    phone=f"2547{n[:7]}", account_number=f"B{n}",
                    balance=Decimal("0"),
                    lease_start_date=date(2026, 1, 1),
                    lease_expiry_date=date(2026, 12, 31),
                    deposit_amount=Decimal("25000"))
    s.add(tenant)
    s.flush()

    invoice = Invoice(landlord_id=landlord.id, tenant_id=tenant.id, unit_id=unit.id,
                      property_id=prop.id, invoice_number=f"INV-{n}",
                      invoice_type="rent", title="Rent",
                      issue_date=date.today(), due_date=date.today(),
                      total_amount=Decimal("25000"), amount_paid=Decimal("25000"),
                      balance=Decimal("0"), status=InvoiceStatus.paid.value)
    s.add(invoice)
    s.flush()
    payment = Payment(landlord_id=landlord.id, tenant_id=tenant.id, unit_id=unit.id,
                      property_id=prop.id, amount=Decimal("25000"),
                      payment_date=date.today(), payment_ref=f"PAY-{n}",
                      status=PaymentStatus.confirmed.value, source="manual")
    s.add(payment)
    s.flush()

    return {"landlord": landlord, "property": prop, "unit": unit,
            "tenant": tenant, "invoice": invoice, "payment": payment, "n": n}


def _assert_branded(html: str, landlord) -> None:
    assert html, "nothing was rendered"
    assert landlord.company_name in html, "the landlord's name is not on the document"
    assert "letterhead" in html, "the document has no letterhead block"


# ---------------------------------------------------------------------------
# Each document type
# ---------------------------------------------------------------------------

def test_a_tenancy_agreement_carries_the_letterhead(app, estate, captured_html):
    """
    The one the landlord asked about specifically. A lease is the document
    produced when there is a dispute, and it had no letterhead at all.
    """
    from services import lease_service as leases

    lease = leases.create_for_tenant(estate["tenant"])
    db.session.flush()
    leases.render_pdf_bytes(lease)

    _assert_branded(captured_html.get("html", ""), estate["landlord"])


def test_a_lease_still_shows_the_agreement_itself(app, estate, captured_html):
    """Branding must not have displaced the actual terms."""
    from services import lease_service as leases

    lease = leases.create_for_tenant(estate["tenant"])
    db.session.flush()
    leases.render_pdf_bytes(lease)

    html = captured_html["html"]
    assert "TENANCY AGREEMENT" in html
    assert estate["tenant"].first_name in html


def test_a_receipt_carries_the_letterhead(app, estate, captured_html):
    from services.receipt_service import render_receipt_pdf

    render_receipt_pdf(estate["payment"])

    html = captured_html.get("html", "")
    assert html, "nothing was rendered"
    assert estate["landlord"].company_name in html


def test_a_property_statement_carries_the_letterhead(app, estate, captured_html):
    from services.report_generators import build_property_statement
    from services.report_builder import render_document

    doc = build_property_statement(estate["landlord"], estate["property"].id, None, None)
    render_document(doc, "pdf")

    _assert_branded(captured_html.get("html", ""), estate["landlord"])


def test_a_tenant_statement_carries_the_letterhead(app, estate, captured_html):
    from services.report_generators import build_tenant_statement
    from services.report_builder import render_document

    doc = build_tenant_statement(estate["landlord"], estate["tenant"].id, None, None)
    render_document(doc, "pdf")

    _assert_branded(captured_html.get("html", ""), estate["landlord"])


# ---------------------------------------------------------------------------
# The fallback
# ---------------------------------------------------------------------------

def test_a_landlord_with_no_logo_still_gets_a_finished_document(app, estate, captured_html):
    """
    Most accounts never upload a logo. Their documents must not come out with an
    empty rectangle where the identity should be.
    """
    from services import lease_service as leases

    assert not getattr(estate["landlord"], "logo_url", None)

    lease = leases.create_for_tenant(estate["tenant"])
    db.session.flush()
    leases.render_pdf_bytes(lease)

    html = captured_html["html"]
    # The Sahil Pay mark fills the slot...
    assert "<svg" in html
    # ...but the COMPANY on the document is the landlord, never Sahil Pay.
    assert estate["landlord"].company_name in html


def test_an_uploaded_logo_is_used_instead_of_the_fallback(app, estate, captured_html, db_session):
    estate["landlord"].logo_url = "/uploads/logos/1/mark.png"
    db_session.flush()

    from services import lease_service as leases

    lease = leases.create_for_tenant(estate["tenant"])
    db.session.flush()
    leases.render_pdf_bytes(lease)

    html = captured_html["html"]
    assert "/uploads/logos/1/mark.png" in html


def test_the_company_address_appears_when_set(app, estate, captured_html):
    from services import lease_service as leases

    lease = leases.create_for_tenant(estate["tenant"])
    db.session.flush()
    leases.render_pdf_bytes(lease)

    assert "P.O. Box 123, Nairobi" in captured_html["html"]
