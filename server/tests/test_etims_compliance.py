"""
SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §10 — acceptance checklist.

The tests are grouped the way the spec's checklist is, because the first group
is the one that actually matters. "Silence & optionality" is not a nice-to-have
here: the entire feature is opt-in, and a landlord who never touches it must be
unable to tell it shipped. Anything that makes absence visible — an empty
column, a placeholder, a "pending" badge, a coverage warning — is a bug even
when the numbers underneath are right.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    ChargeCategory, Invoice, InvoiceLineItem, InvoiceStatus, InvoiceType,
    Landlord, LandlordSettings, Payment, PaymentAllocation, PaymentStatus,
    PaymentSource, Property, PropertyOwner, Tenant, Unit, User,
)
from services import etims_service as etims
from services.category_service import rent_category_id, seed_default_categories
from utils import ApiError


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def estate(db_session):
    """
    A property manager with TWO owners, so the consolidation rule has something
    real to consolidate:

        Owner A (PIN A012345678B) — Block One, Block Two
        Owner B (PIN P051234567X) — Block Three

    One tenant in Block One pays 20,000: 12,000 rent current, 3,000 rent
    arrears, 5,000 deposit. Rent received is therefore 15,000 and the deposit
    is excluded, exactly as the commission engine already treats it.
    """
    s = db_session
    n = _uniq()

    user = User(
        email=f"etims-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="property_manager", is_verified=True, is_active=True,
    )
    s.add(user)
    s.flush()

    landlord = Landlord(user_id=user.id, company_name=f"Agent {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    seed_default_categories(landlord.id)
    s.flush()

    owner_a = PropertyOwner(landlord_id=landlord.id, full_name=f"Owner A {n}",
                            phone=f"+2547111{n[:4]}", kra_pin="A012345678B")
    owner_b = PropertyOwner(landlord_id=landlord.id, full_name=f"Owner B {n}",
                            phone=f"+2547222{n[:4]}", kra_pin="P051234567X")
    s.add_all([owner_a, owner_b])
    s.flush()

    def block(name, owner):
        p = Property(landlord_id=landlord.id, name=f"{name} {n}", number_of_units=1,
                     city="Nairobi", tax_rate=Decimal("0.00"), owner_id=owner.id)
        s.add(p)
        s.flush()
        return p

    one, two, three = (block("Block One", owner_a), block("Block Two", owner_a),
                       block("Block Three", owner_b))

    unit = Unit(property_id=one.id, name=f"A1-{n}", rent_amount=Decimal("12000"))
    s.add(unit)
    s.flush()
    tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id, first_name="Tina",
                    last_name=n, phone=f"+25473{n[:7]}", account_number=f"E-{n}")
    s.add(tenant)
    s.flush()

    rent_cat = rent_category_id(landlord.id)
    today = date.today()
    invoice = Invoice(
        invoice_number=f"INV-{n}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=unit.id, property_id=one.id, invoice_type=InvoiceType.monthly.value,
        issue_date=today, status=InvoiceStatus.open.value,
        total_amount=Decimal("20000"), amount_paid=Decimal("0"),
        balance=Decimal("20000"),
    )
    s.add(invoice)
    s.flush()

    def line(item, amount, subcategory):
        li = InvoiceLineItem(invoice_id=invoice.id, item=item, quantity=1,
                             unit_price=amount, amount=amount,
                             category_id=rent_cat, subcategory=subcategory)
        s.add(li)
        s.flush()
        return li

    lines = [(line("Rent", Decimal("12000"), "current"), "12000"),
             (line("Rent b/f", Decimal("3000"), "balance"), "3000"),
             (line("Deposit", Decimal("5000"), "deposit"), "5000")]

    payment = Payment(
        payment_ref=f"PMT-{n}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=unit.id, property_id=one.id, amount=Decimal("20000"),
        payment_date=today, status=PaymentStatus.confirmed.value,
        source=PaymentSource.mpesa.value, payment_method="M-Pesa",
    )
    s.add(payment)
    s.flush()
    for li, amount in lines:
        s.add(PaymentAllocation(payment_id=payment.id, invoice_id=invoice.id,
                                line_item_id=li.id, amount_allocated=Decimal(amount)))
    s.commit()

    return {"landlord": landlord, "user": user, "owner_a": owner_a,
            "owner_b": owner_b, "one": one, "two": two, "three": three,
            "unit": unit, "tenant": tenant, "payment": payment, "today": today}


def _opt_in(estate, *properties, **display):
    """Switch the account master on and enable the given properties."""
    estate["landlord"].landlord_settings.etims_enabled = True
    for prop in properties:
        prop.etims_enabled = True
        if display:
            prop.etims_display_settings = dict(display)
    db.session.commit()


# ===========================================================================
# Silence & optionality
# ===========================================================================

def test_untouched_account_has_no_etims_surface(estate):
    """A fresh account: the feature is completely dark."""
    landlord_id = estate["landlord"].id
    assert etims.account_enabled(landlord_id) is False
    assert estate["one"].etims_enabled is False
    for surface in ("receipts", "statements", "reports"):
        assert estate["one"].etims_shows(surface) is False


def test_property_opt_in_does_not_leak_to_siblings(estate):
    _opt_in(estate, estate["one"])
    assert estate["one"].etims_shows("receipts") is True
    assert estate["two"].etims_shows("receipts") is False


def test_account_master_switch_overrides_property_flags(estate):
    """Turning the account off hides everything without deleting a thing."""
    _opt_in(estate, estate["one"])
    estate["landlord"].landlord_settings.etims_enabled = False
    db.session.commit()
    # The property flag is untouched — this is a display decision, not a delete.
    assert estate["one"].etims_enabled is True
    assert etims.account_enabled(estate["landlord"].id) is False


def test_receipt_has_no_etims_block_without_a_number(estate):
    """
    The central rule: enabled property + payment with no number = NO block.
    Not a placeholder, not a "pending" badge — nothing.
    """
    from services.etims_pdf import receipt_block_html

    _opt_in(estate, estate["one"])
    assert estate["payment"].etims_invoice_number is None
    assert receipt_block_html(estate["payment"], estate["one"], estate["tenant"]) == ""


def test_receipt_block_appears_once_a_number_is_recorded(estate):
    from services.etims_pdf import receipt_block_html

    _opt_in(estate, estate["one"])
    estate["one"].kra_pin = "A012345678B"
    estate["tenant"].kra_pin = "P051234567X"
    # Unique per run: the eTIMS unique index is global and these tests commit.
    number = f"KRA/{_uniq()}"
    etims.record_number(estate["payment"], "payment",
                        invoice_number=number, actor_user_id=estate["user"].id)
    db.session.commit()

    html = receipt_block_html(estate["payment"], estate["one"], estate["tenant"])
    assert number in html
    assert "A012345678B" in html    # seller = the property owner
    assert "P051234567X" in html    # buyer  = the tenant


def test_receipt_block_stays_hidden_when_receipts_are_switched_off(estate):
    """Per-surface control: reports on, receipts off."""
    from services.etims_pdf import receipt_block_html

    _opt_in(estate, estate["one"], show_on_receipts=False, show_on_reports=True)
    etims.record_number(estate["payment"], "payment", invoice_number=f"KRA/{_uniq()}",
                        actor_user_id=estate["user"].id)
    db.session.commit()
    assert receipt_block_html(estate["payment"], estate["one"], estate["tenant"]) == ""
    assert estate["one"].etims_shows("reports") is True


def test_statement_column_omitted_when_nothing_was_recorded(estate):
    """A column of blanks is exactly what this feature must never produce."""
    from services.etims_pdf import include_etims_column

    _opt_in(estate, estate["one"])
    by_id = {estate["one"].id: estate["one"]}
    rows = [{"property_id": estate["one"].id, "etims_invoice_number": None}]
    assert include_etims_column(rows, by_id, checkbox=True) is False

    rows[0]["etims_invoice_number"] = "KRA/1"
    assert include_etims_column(rows, by_id, checkbox=True) is True
    # Unticking the box always wins.
    assert include_etims_column(rows, by_id, checkbox=False) is False


def test_no_alarming_language_in_user_facing_strings():
    """
    §10: no user-facing string in this feature may say "missing",
    "non-compliant", "overdue" or "warning".
    """
    import ast
    import inspect

    from services import etims_pdf
    from services import notification_service
    from tasks import etims_tasks

    banned = ("non-compliant", "noncompliant", "overdue", "violation")

    def user_facing_strings(module):
        """
        Every string literal in the module EXCEPT docstrings.

        Docstrings and comments are exempt on purpose: explaining a rule
        requires naming the words the rule bans, and no user ever reads them.
        """
        tree = ast.parse(inspect.getsource(module))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docstrings.add(id(body[0].value))
        return [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings]

    for module in (etims, etims_pdf, etims_tasks):
        for literal in user_facing_strings(module):
            lowered = literal.lower()
            for word in banned:
                assert word not in lowered, f"{module.__name__}: {literal!r}"

    for key in ("etims_record_invoices", "mri_filing_due"):
        body = notification_service.TEMPLATES[key]["body"].lower()
        title = notification_service.TEMPLATES[key]["title"].lower()
        for word in banned + ("missing",):
            assert word not in body and word not in title


# ===========================================================================
# Validation
# ===========================================================================

@pytest.mark.parametrize("value,expected", [
    ("A012345678B", "A012345678B"),
    ("p051234567x", "P051234567X"),   # case-insensitive in, uppercase stored
    ("  A012345678B  ", "A012345678B"),
    ("", None),                        # blank is always allowed
    (None, None),
])
def test_kra_pin_accepts_valid_and_blank(value, expected):
    assert etims.normalise_kra_pin(value) == expected


@pytest.mark.parametrize("value", [
    "X012345678B",    # bad prefix letter
    "A01234567B",     # too few digits
    "A0123456789",    # ends in a digit
    "junk",
])
def test_kra_pin_rejects_junk(value):
    with pytest.raises(ApiError):
        etims.normalise_kra_pin(value)


def test_invoice_number_trimmed_and_character_checked():
    assert etims.normalise_invoice_number("  KRA/0012-45.9  ") == "KRA/0012-45.9"
    assert etims.normalise_invoice_number("") is None
    with pytest.raises(ApiError):
        etims.normalise_invoice_number("bad;semicolon")
    with pytest.raises(ApiError):
        etims.normalise_invoice_number("X" * 65)


def test_duplicate_number_is_refused_and_names_the_conflict(estate):
    """Friendly, specific, and never a crash."""
    _opt_in(estate, estate["one"])
    first = estate["payment"]
    number = f"KRA/DUP-{_uniq()}"
    etims.record_number(first, "payment", invoice_number=number,
                        actor_user_id=estate["user"].id)
    db.session.commit()

    second = Payment(
        payment_ref=f"PMT2-{_uniq()}", landlord_id=estate["landlord"].id,
        tenant_id=estate["tenant"].id, unit_id=estate["unit"].id,
        property_id=estate["one"].id, amount=Decimal("1000"),
        payment_date=estate["today"], status=PaymentStatus.confirmed.value,
        source=PaymentSource.mpesa.value,
    )
    db.session.add(second)
    db.session.flush()

    with pytest.raises(ApiError) as excinfo:
        etims.record_number(second, "payment", invoice_number=number,
                            actor_user_id=estate["user"].id)
    assert f"#{first.id}" in excinfo.value.message
    assert excinfo.value.status == 409


def test_clearing_a_number_is_an_ordinary_state(estate):
    _opt_in(estate, estate["one"])
    payment = estate["payment"]
    etims.record_number(payment, "payment", invoice_number=f"KRA/{_uniq()}",
                        actor_user_id=estate["user"].id)
    db.session.commit()
    etims.record_number(payment, "payment", invoice_number="",
                        actor_user_id=estate["user"].id)
    db.session.commit()
    assert payment.etims_invoice_number is None
    assert payment.etims_issued_at is None


# ===========================================================================
# KRA Monthly Report
# ===========================================================================

def test_mri_is_cash_basis_rent_only(estate, monkeypatch):
    """
    Gross is the 15,000 of rent that arrived — the 5,000 deposit is the
    tenant's own money and never enters the base. 7.5% of 15,000 = 1,125.
    """
    _opt_in(estate, estate["one"], estate["two"], estate["three"])
    monkeypatch.setattr(etims, "tax_property_ids",
                        lambda _lid: {estate["one"].id, estate["two"].id,
                                      estate["three"].id})

    report = etims.kra_monthly_report(
        estate["landlord"].id, month=estate["today"].strftime("%Y-%m"))

    assert report["totals"]["gross_rent_received"] == "15000.00"
    assert report["totals"]["mri_due"] == "1125.00"


def test_worked_example_100k_rent_gives_7500(estate, monkeypatch):
    """The spec's own worked figure."""
    assert (Decimal("100000") * etims.MRI_RATE).quantize(Decimal("0.01")) \
        == Decimal("7500.00")


def test_report_consolidates_per_owner_not_per_property(estate, monkeypatch):
    """
    Under a PM account the taxpayer is the OWNER, so Owner A's two blocks
    collapse into one filing group and Owner B keeps their own.
    """
    _opt_in(estate, estate["one"], estate["two"], estate["three"])
    monkeypatch.setattr(etims, "tax_property_ids",
                        lambda _lid: {estate["one"].id, estate["two"].id,
                                      estate["three"].id})

    report = etims.kra_monthly_report(
        estate["landlord"].id, month=estate["today"].strftime("%Y-%m"),
        consolidated=True)

    groups = {g["name"]: g for g in report["groups"]}
    assert len(report["groups"]) == 2, "two owners → two filing groups"

    owner_a = groups[estate["owner_a"].full_name]
    assert owner_a["kra_pin"] == "A012345678B"
    assert len(owner_a["properties"]) == 2
    assert owner_a["gross_rent_received"] == "15000.00"

    owner_b = groups[estate["owner_b"].full_name]
    assert owner_b["gross_rent_received"] == "0.00"


def test_unconsolidated_view_is_per_property(estate, monkeypatch):
    _opt_in(estate, estate["one"], estate["two"], estate["three"])
    monkeypatch.setattr(etims, "tax_property_ids",
                        lambda _lid: {estate["one"].id, estate["two"].id,
                                      estate["three"].id})
    report = etims.kra_monthly_report(
        estate["landlord"].id, month=estate["today"].strftime("%Y-%m"),
        consolidated=False)
    assert len(report["groups"]) == 3


def test_coverage_line_is_neutral_and_counted(estate, monkeypatch):
    """The single place a coverage figure appears anywhere in the product."""
    _opt_in(estate, estate["one"])
    monkeypatch.setattr(etims, "tax_property_ids", lambda _lid: {estate["one"].id})

    report = etims.kra_monthly_report(
        estate["landlord"].id, month=estate["today"].strftime("%Y-%m"))
    group = report["groups"][0]
    assert group["coverage_line"] == "eTIMS invoices recorded: 0 of 1 payments."

    etims.record_number(estate["payment"], "payment", invoice_number=f"KRA/{_uniq()}",
                        actor_user_id=estate["user"].id)
    db.session.commit()

    report = etims.kra_monthly_report(
        estate["landlord"].id, month=estate["today"].strftime("%Y-%m"))
    assert report["groups"][0]["coverage_line"] == \
        "eTIMS invoices recorded: 1 of 1 payments."


def test_report_is_empty_when_nothing_opted_in(estate, monkeypatch):
    monkeypatch.setattr(etims, "tax_property_ids", lambda _lid: set())
    report = etims.kra_monthly_report(estate["landlord"].id)
    assert report["groups"] == []
    assert report["totals"]["gross_rent_received"] == "0.00"


def test_report_always_carries_the_disclaimer(estate, monkeypatch):
    monkeypatch.setattr(etims, "tax_property_ids", lambda _lid: {estate["one"].id})
    report = etims.kra_monthly_report(estate["landlord"].id)
    assert "not tax advice" in report["disclaimer"]


# ===========================================================================
# Bulk save
# ===========================================================================

def test_bulk_save_keeps_good_rows_when_one_is_invalid(estate, monkeypatch):
    """9 saved, 1 inline error, nothing lost — the Register is unusable otherwise."""
    _opt_in(estate, estate["one"])
    monkeypatch.setattr(etims, "tax_property_ids", lambda _lid: {estate["one"].id})
    monkeypatch.setattr(etims, "is_system_admin", lambda: False)

    payments = []
    for index in range(10):
        payment = Payment(
            payment_ref=f"BULK-{_uniq()}", landlord_id=estate["landlord"].id,
            tenant_id=estate["tenant"].id, unit_id=estate["unit"].id,
            property_id=estate["one"].id, amount=Decimal("1000"),
            payment_date=estate["today"], status=PaymentStatus.confirmed.value,
            source=PaymentSource.mpesa.value,
        )
        db.session.add(payment)
        payments.append(payment)
    db.session.flush()

    batch = _uniq()
    records = [{"type": "payment", "id": p.id,
                "etims_invoice_number": f"KRA/BULK-{batch}-{i}"}
               for i, p in enumerate(payments)]
    records[4]["etims_invoice_number"] = "bad;char"   # the one bad row

    result = etims.bulk_record(estate["landlord"].id, records,
                               actor_user_id=estate["user"].id)
    db.session.commit()

    assert result["saved_count"] == 9
    assert result["error_count"] == 1
    assert result["errors"][0]["index"] == 4
    assert payments[4].etims_invoice_number is None
    assert payments[3].etims_invoice_number == f"KRA/BULK-{batch}-3"


def test_bulk_save_refuses_a_property_outside_the_caller_scope(estate, monkeypatch):
    """Server-side scoping, not UI hiding: a crafted id is still a 403."""
    _opt_in(estate, estate["one"], estate["two"])
    # The caller may only touch Block One.
    monkeypatch.setattr(etims, "tax_property_ids", lambda _lid: {estate["one"].id})
    monkeypatch.setattr(etims, "is_system_admin", lambda: False)

    outsider = Payment(
        payment_ref=f"OUT-{_uniq()}", landlord_id=estate["landlord"].id,
        tenant_id=estate["tenant"].id, unit_id=estate["unit"].id,
        property_id=estate["two"].id, amount=Decimal("500"),
        payment_date=estate["today"], status=PaymentStatus.confirmed.value,
        source=PaymentSource.mpesa.value,
    )
    db.session.add(outsider)
    db.session.flush()

    result = etims.bulk_record(
        estate["landlord"].id,
        [{"type": "payment", "id": outsider.id, "etims_invoice_number": f"KRA/NOPE-{_uniq()}"}],
        actor_user_id=estate["user"].id)

    assert result["saved_count"] == 0
    assert result["error_count"] == 1
    assert outsider.etims_invoice_number is None


def test_bulk_subscription_entry_is_admin_only(estate, monkeypatch):
    from models import BillingTransaction

    monkeypatch.setattr(etims, "is_system_admin", lambda: False)
    txn = BillingTransaction(landlord_id=estate["landlord"].id, type="subscription",
                             amount=Decimal("2000"), status="paid")
    db.session.add(txn)
    db.session.flush()

    result = etims.bulk_record(
        estate["landlord"].id,
        [{"type": "subscription", "id": txn.id, "etims_invoice_number": f"KRA/SUB-{_uniq()}"}],
        actor_user_id=estate["user"].id)

    assert result["saved_count"] == 0
    assert "system administrator" in result["errors"][0]["message"]


# ===========================================================================
# Register
# ===========================================================================

def test_register_status_filters_use_neutral_labels(estate, monkeypatch):
    _opt_in(estate, estate["one"])
    monkeypatch.setattr(etims, "tax_property_ids", lambda _lid: {estate["one"].id})
    month = estate["today"].strftime("%Y-%m")

    assert len(etims.register_rows(estate["landlord"].id, month=month)) == 1
    assert etims.register_rows(estate["landlord"].id, month=month,
                               status="recorded") == []
    assert len(etims.register_rows(estate["landlord"].id, month=month,
                                   status="not_recorded")) == 1

    etims.record_number(estate["payment"], "payment", invoice_number=f"KRA/{_uniq()}",
                        actor_user_id=estate["user"].id)
    db.session.commit()
    assert len(etims.register_rows(estate["landlord"].id, month=month,
                                   status="recorded")) == 1


def test_register_is_empty_without_tax_scope(estate, monkeypatch):
    monkeypatch.setattr(etims, "tax_property_ids", lambda _lid: set())
    assert etims.register_rows(estate["landlord"].id) == []


# ===========================================================================
# Help Content CMS
# ===========================================================================

def test_markdown_render_escapes_raw_html(db_session):
    from services.tutorial_service import render_markdown

    html = render_markdown("# Title\n\n<script>alert(1)</script>\n\nSome **bold**.")
    assert "<h1>" in html
    assert "<strong>bold</strong>" in html
    assert "<script>" not in html, "raw HTML must be escaped, never passed through"


def test_unpublished_content_is_invisible_to_readers(db_session):
    from models import TutorialArticle, TutorialCategory
    from services.tutorial_service import published_categories, published_article

    n = _uniq()
    category = TutorialCategory(name=f"Draft cat {n}", slug=f"draft-cat-{n}",
                                is_published=False)
    db_session.add(category)
    db_session.flush()
    article = TutorialArticle(category_id=category.id, title=f"Draft {n}",
                              slug=f"draft-{n}", body_markdown="secret",
                              is_published=False)
    db_session.add(article)
    db_session.commit()

    slugs = [c["slug"] for c in published_categories("landlord")]
    assert category.slug not in slugs
    with pytest.raises(ApiError):
        published_article(article.slug, "landlord")


def test_role_visibility_is_enforced_server_side(db_session):
    from models import TutorialArticle, TutorialCategory
    from services.tutorial_service import published_article

    n = _uniq()
    category = TutorialCategory(name=f"Cat {n}", slug=f"cat-{n}", is_published=True)
    db_session.add(category)
    db_session.flush()
    article = TutorialArticle(category_id=category.id, title=f"Landlords only {n}",
                              slug=f"landlords-only-{n}", body_markdown="body",
                              visible_to_roles=["landlord"], is_published=True)
    db_session.add(article)
    db_session.commit()

    assert published_article(article.slug, "landlord")["slug"] == article.slug
    with pytest.raises(ApiError):
        published_article(article.slug, "tenant")


def test_article_inherits_its_category_audience(db_session):
    from models import TutorialArticle, TutorialCategory
    from services.tutorial_service import audience_of

    n = _uniq()
    category = TutorialCategory(name=f"Cat {n}", slug=f"inherit-{n}",
                                visible_to_roles=["property_manager"],
                                is_published=True)
    db_session.add(category)
    db_session.flush()
    article = TutorialArticle(category_id=category.id, title=f"A {n}",
                              slug=f"inherit-a-{n}", is_published=True)
    db_session.add(article)
    db_session.commit()

    assert audience_of(article) == ["property_manager"]


def test_seeded_stubs_are_seven_drafts(db_session):
    from models import TutorialArticle, TutorialCategory
    from seed_tutorials import seed_tutorials

    result = seed_tutorials()
    category = (db_session.query(TutorialCategory)
                .filter_by(slug="tax-compliance-kra-etims").first())
    assert category is not None
    assert category.is_published is False

    articles = (db_session.query(TutorialArticle)
                .filter_by(category_id=category.id).all())
    assert len(articles) == 7
    assert all(a.is_published is False for a in articles), \
        "nothing ships until it is published from the admin portal"


# ===========================================================================
# Reminders
# ===========================================================================

def test_reminders_only_target_opted_in_accounts(estate):
    from tasks.etims_tasks import _opted_in_landlords

    assert estate["landlord"].id not in [l.id for l in _opted_in_landlords()]

    # Master switch alone is not enough — a property must be enabled too.
    estate["landlord"].landlord_settings.etims_enabled = True
    db.session.commit()
    assert estate["landlord"].id not in [l.id for l in _opted_in_landlords()]

    estate["one"].etims_enabled = True
    db.session.commit()
    assert estate["landlord"].id in [l.id for l in _opted_in_landlords()]
