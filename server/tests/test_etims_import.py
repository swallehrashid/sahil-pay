"""
Importing KRA control numbers back onto payments.

The only thing that matters here is being right. A control number attests to KRA
that a particular sale happened, for a particular amount — so putting one on the
wrong payment is a false statement to a tax authority, not a cosmetic slip.

Every test below is therefore about the matcher REFUSING to guess:

  one match or none        two candidates is ambiguous, and ambiguity is handed
                           back to a human, never resolved by picking the first
  reference beats amount   amount+date is opt-in, because two tenants paying
                           25,000 rent on the 1st is the ordinary case
  amount is a check        a number whose amount disagrees with the payment is
                           reported, not applied
  resolutions are bounded  a human may choose, but only among the candidates the
                           matcher actually offered
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    Landlord, LandlordSettings, Payment, PaymentStatus, Property, Tenant, Unit, User,
)
from services import etims_import_service as importer


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def books(app, db_session):
    """One landlord, one block, and three confirmed payments."""
    s = db_session
    n = _uniq()

    owner = User(email=f"ei-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()
    # kra_pin lives on the User row, not the Landlord — and none of these tests
    # need it, since the matcher never looks at it.
    landlord = Landlord(user_id=owner.id, company_name=f"Etims {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    prop = Property(landlord_id=landlord.id, name=f"Block {n}", city="Nairobi",
                    etims_enabled=True)
    s.add(prop)
    s.flush()

    payments = {}
    # Two DELIBERATELY identical amounts on the same day — the ambiguity case.
    spec = [
        ("A", Decimal("25000"), date(2026, 4, 1), "MPESA-AAA"),
        ("B", Decimal("25000"), date(2026, 4, 1), "MPESA-BBB"),
        ("C", Decimal("31000"), date(2026, 4, 2), "MPESA-CCC"),
    ]
    for label, amount, when, mpesa in spec:
        unit = Unit(landlord_id=landlord.id, property_id=prop.id,
                    name=f"{label}{n[:3]}", rent_amount=amount)
        s.add(unit)
        s.flush()
        tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id,
                        first_name=f"Ten{label}", last_name=n[:4],
                        phone=f"2547{abs(hash(label)) % 10000000:07d}",
                        account_number=f"{label}{n}", balance=Decimal("0"))
        s.add(tenant)
        s.flush()
        payment = Payment(
            landlord_id=landlord.id, tenant_id=tenant.id, unit_id=unit.id,
            property_id=prop.id, amount=amount, payment_date=when,
            payment_ref=f"PAY-{label}-{n}", mpesa_reference=mpesa,
            status=PaymentStatus.confirmed.value, source="manual",
        )
        s.add(payment)
        s.flush()
        payments[label] = payment

    return {"landlord": landlord, "payments": payments, "n": n}


def _rows(*dicts):
    return [{**d, "_line": i + 2} for i, d in enumerate(dicts)]


def _number(books, suffix):
    """
    A control number unique to this run.

    commit() commits — that is its job — so numbers written by these tests
    survive db_session's rollback and would collide with the next run. The
    payments table has a UNIQUE constraint on the column, which is exactly
    right in production and exactly why the tests must not reuse literals.
    """
    return f"KRA-{books['n']}-{suffix}"


MAPPING = {
    "reference": "Ref",
    "etims_invoice_number": "Control",
    "amount": "Amount",
    "payment_date": "Date",
}


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

def test_ordinary_kra_column_names_are_recognised():
    mapping = importer.suggest_mapping(
        ["Receipt No", "CU Invoice Number", "Date Issued", "QR Code", "Total"])

    assert mapping["reference"] == "Receipt No"
    assert mapping["etims_invoice_number"] == "CU Invoice Number"
    assert mapping["qr_url"] == "QR Code"
    assert mapping["amount"] == "Total"


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_our_own_reference_matches_exactly_one_payment(app, books):
    payment = books["payments"]["C"]
    rows = _rows({"Ref": payment.payment_ref, "Control": _number(books, "0001")})

    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["summary"]["matched"] == 1
    assert result["rows"][0]["payment"]["payment_id"] == payment.id
    assert result["rows"][0]["match_strategy"] == importer.MATCH_REFERENCE


def test_an_mpesa_code_also_matches(app, books):
    rows = _rows({"Ref": "MPESA-CCC", "Control": _number(books, "0002")})

    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["summary"]["matched"] == 1
    assert result["rows"][0]["match_strategy"] == importer.MATCH_MPESA


def test_amount_and_date_alone_does_not_match_by_default(app, books):
    """
    Two tenants paying the same rent on the same day is the ordinary case, so
    this is opt-in — on its own it identifies a payment about as well as a shoe
    size.
    """
    rows = _rows({"Control": _number(books, "0003"), "Amount": "31000", "Date": "2026-04-02"})

    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["summary"]["unmatched"] == 1


def test_amount_and_date_can_be_enabled_deliberately(app, books):
    rows = _rows({"Control": _number(books, "0004"), "Amount": "31000", "Date": "2026-04-02"})

    result = importer.validate(books["landlord"].id, rows, MAPPING,
                               {"allow_amount_date_match": True})

    assert result["summary"]["matched"] == 1
    assert result["rows"][0]["match_strategy"] == importer.MATCH_AMOUNT_DATE


def test_two_identical_payments_are_ambiguous_never_guessed(app, books):
    """The case the whole design exists for."""
    rows = _rows({"Control": _number(books, "0005"), "Amount": "25000", "Date": "2026-04-01"})

    result = importer.validate(books["landlord"].id, rows, MAPPING,
                               {"allow_amount_date_match": True})

    entry = result["rows"][0]
    assert entry["status"] == importer.STATUS_AMBIGUOUS
    assert len(entry["candidates"]) == 2
    assert entry["payment"] is None


def test_an_unknown_reference_is_unmatched_not_forced(app, books):
    rows = _rows({"Ref": "NOT-A-REF", "Control": _number(books, "0006")})

    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["rows"][0]["status"] == importer.STATUS_UNMATCHED


# ---------------------------------------------------------------------------
# The amount is a check, not a key
# ---------------------------------------------------------------------------

def test_a_disagreeing_amount_blocks_the_row(app, books):
    """
    A number attached to a payment of a different value is precisely the error
    this importer exists to prevent.
    """
    payment = books["payments"]["C"]           # 31,000
    rows = _rows({"Ref": payment.payment_ref, "Control": _number(books, "0007"), "Amount": "9999"})

    result = importer.validate(books["landlord"].id, rows, MAPPING)

    entry = result["rows"][0]
    assert entry["status"] == importer.STATUS_MISMATCH
    assert "9999" in entry["message"]


def test_a_matching_amount_passes(app, books):
    payment = books["payments"]["C"]
    rows = _rows({"Ref": payment.payment_ref, "Control": _number(books, "0008"), "Amount": "31,000"})

    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["rows"][0]["status"] == importer.STATUS_MATCHED


# ---------------------------------------------------------------------------
# File-level problems
# ---------------------------------------------------------------------------

def test_a_control_number_twice_in_one_file_is_refused(app, books):
    rows = _rows(
        {"Ref": books["payments"]["A"].payment_ref, "Control": _number(books, "DUP")},
        {"Ref": books["payments"]["C"].payment_ref, "Control": _number(books, "DUP")},
    )

    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["rows"][1]["status"] == importer.STATUS_INVALID
    assert "appears twice" in result["rows"][1]["message"]


def test_a_row_with_no_control_number_is_invalid(app, books):
    rows = _rows({"Ref": books["payments"]["A"].payment_ref, "Control": ""})

    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["rows"][0]["status"] == importer.STATUS_INVALID


def test_a_payment_that_already_has_that_number_is_a_no_op(app, books, db_session):
    payment = books["payments"]["C"]
    payment.etims_invoice_number = _number(books, "EXISTING")
    db_session.flush()

    rows = _rows({"Ref": payment.payment_ref, "Control": _number(books, "EXISTING")})
    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["rows"][0]["status"] == importer.STATUS_ALREADY


def test_overwriting_a_different_number_is_refused(app, books, db_session):
    """Replacing one control number with another is not a bulk decision."""
    payment = books["payments"]["C"]
    payment.etims_invoice_number = _number(books, "OLD")
    db_session.flush()

    rows = _rows({"Ref": payment.payment_ref, "Control": _number(books, "NEW")})
    result = importer.validate(books["landlord"].id, rows, MAPPING)

    assert result["rows"][0]["status"] == importer.STATUS_MISMATCH
    assert "already carries" in result["rows"][0]["message"]


# ---------------------------------------------------------------------------
# Committing
# ---------------------------------------------------------------------------

def test_committing_records_the_number_on_the_payment(app, books):
    payment = books["payments"]["C"]
    rows = _rows({"Ref": payment.payment_ref, "Control": _number(books, "1000")})

    result = importer.commit(books["landlord"].id, rows, MAPPING)

    assert len(result["applied"]) == 1
    db.session.refresh(payment)
    assert payment.etims_invoice_number == _number(books, "1000")


def test_ambiguous_rows_are_left_alone_by_a_plain_commit(app, books):
    rows = _rows({"Control": _number(books, "1001"), "Amount": "25000", "Date": "2026-04-01"})

    result = importer.commit(books["landlord"].id, rows, MAPPING,
                             {"allow_amount_date_match": True})

    assert result["applied"] == []
    for payment in books["payments"].values():
        db.session.refresh(payment)
        assert payment.etims_invoice_number is None


def test_a_human_can_resolve_an_ambiguous_row(app, books):
    chosen = books["payments"]["B"]
    rows = _rows({"Control": _number(books, "1002"), "Amount": "25000", "Date": "2026-04-01"})

    result = importer.commit(
        books["landlord"].id, rows, MAPPING, {"allow_amount_date_match": True},
        resolutions={2: chosen.id})

    assert len(result["applied"]) == 1
    db.session.refresh(chosen)
    assert chosen.etims_invoice_number == _number(books, "1002")


def test_a_resolution_outside_the_offered_candidates_is_refused(app, books):
    """
    A stale or hand-edited payload must not be able to point a control number at
    an unrelated payment.
    """
    unrelated = books["payments"]["C"]         # not a candidate for 25,000
    rows = _rows({"Control": _number(books, "1003"), "Amount": "25000", "Date": "2026-04-01"})

    result = importer.commit(
        books["landlord"].id, rows, MAPPING, {"allow_amount_date_match": True},
        resolutions={2: unrelated.id})

    assert result["applied"] == []
    assert "not one of the options" in result["failed"][0]["message"]
    db.session.refresh(unrelated)
    assert unrelated.etims_invoice_number is None


def test_a_duplicate_number_across_payments_is_refused_at_commit(app, books, db_session):
    """
    etims_service.record_number() owns the duplicate rule; the importer must go
    through it rather than writing the column itself.
    """
    books["payments"]["A"].etims_invoice_number = _number(books, "TAKEN")
    db_session.flush()

    rows = _rows({"Ref": books["payments"]["C"].payment_ref, "Control": _number(books, "TAKEN")})
    result = importer.commit(books["landlord"].id, rows, MAPPING)

    assert result["applied"] == []
    assert result["failed"]
    db.session.refresh(books["payments"]["C"])
    assert books["payments"]["C"].etims_invoice_number is None
