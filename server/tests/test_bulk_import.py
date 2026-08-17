"""
Bulk import — properties, units and tenants from whatever spreadsheet arrives.

The existing tenant importer needs one sheet with OUR headers. A manager
migrating a real book has three sheets with THEIR headers, and the step that
loses them is being told to reformat the file first. So the parts worth pinning
here are the ones that decide whether a real file gets in:

  MAPPING       headers are read through a {field: column} mapping, and the
                suggestion is good enough that ordinary spreadsheets need no
                corrections.
  CLEANING      "KES 25,000" is a number and "0712 345 678" is a phone.
  UNIQUENESS    a unit's account number is what a tenant quotes when paying, so
                a duplicate means money landing on the wrong lease. Checked
                against the file AND the whole account.
  PARTIAL       bad rows are rejected individually; the good ones still land.
"""

import io
import uuid
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    Landlord, LandlordSettings, Property, Tenant, Unit, User,
)
from services import bulk_import_service as bulk


def _uniq():
    return uuid.uuid4().hex[:8]


class _Upload(io.BytesIO):
    """Minimal stand-in for a werkzeug FileStorage."""

    def __init__(self, text: str, filename: str = "import.csv"):
        super().__init__(text.encode())
        self.filename = filename


@pytest.fixture()
def estate(app, db_session):
    s = db_session
    n = _uniq()
    owner = User(email=f"bi-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()
    landlord = Landlord(user_id=owner.id, company_name=f"Import {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.flush()
    return landlord


def _rows(text, filename="f.csv"):
    parsed = bulk.parse_file(_Upload(text, filename))
    assert not parsed["errors"], parsed["errors"]
    return parsed


# ---------------------------------------------------------------------------
# Reading and mapping
# ---------------------------------------------------------------------------

def test_a_file_is_read_without_demanding_our_headers():
    """
    The importer must not reject a file for using the customer's own column
    names — that is the step people give up at.
    """
    parsed = _rows("Block,Town\nKileleshwa Court,Nairobi\n")

    assert parsed["headers"] == ["Block", "Town"]
    assert parsed["rows"][0]["Block"] == "Kileleshwa Court"
    assert parsed["rows"][0]["_line"] == 2


def test_semicolon_separated_exports_are_understood():
    """Excel in some locales exports with semicolons; reading that as one
    column looks exactly like "the importer is broken"."""
    parsed = _rows("Block;Town\nKileleshwa Court;Nairobi\n")

    assert parsed["headers"] == ["Block", "Town"]
    assert parsed["rows"][0]["Town"] == "Nairobi"


def test_blank_lines_are_ignored():
    parsed = _rows("Block,Town\n\nKileleshwa Court,Nairobi\n\n")

    assert len(parsed["rows"]) == 1


def test_the_suggested_mapping_handles_ordinary_column_names():
    """If this is weak, every import starts with fifteen manual corrections."""
    mapping = bulk.suggest_mapping(
        "units", ["Estate", "House No.", "Monthly Rent", "Acc No"])

    assert mapping["property_name"] == "Estate"
    assert mapping["name"] == "House No."
    assert mapping["rent_amount"] == "Monthly Rent"
    assert mapping["account_number"] == "Acc No"


def test_one_column_is_never_mapped_to_two_fields():
    """
    Several fields share aliases ("account" matches both a unit's account number
    and a tenant's unit reference). Letting one column fill two fields silently
    duplicates data.
    """
    mapping = bulk.suggest_mapping("tenants", ["Account", "Phone"])

    assert len(set(mapping.values())) == len(mapping.values())


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("KES 25,000", Decimal("25000")),
    ("25000.00", Decimal("25000.00")),
    ("  30,000  ", Decimal("30000")),
    ("1,234.56", Decimal("1234.56")),
])
def test_money_survives_currency_symbols_and_separators(raw, expected):
    """A rent roll says "KES 25,000" far more often than it says 25000."""
    field = {"key": "rent_amount", "label": "Rent", "required": True,
             "kind": "decimal", "help": "", "aliases": ()}

    value, error = bulk.clean_value(field, raw)

    assert error is None
    assert value == expected


def test_nonsense_in_a_money_column_is_reported_not_swallowed():
    field = {"key": "rent_amount", "label": "Rent", "required": True,
             "kind": "decimal", "help": "", "aliases": ()}

    value, error = bulk.clean_value(field, "ask landlord")

    assert value is None
    assert "must be a number" in error


@pytest.mark.parametrize("raw", ["0712345678", "+254712345678", "254712345678",
                                 "0712 345 678"])
def test_phones_are_stored_in_one_dialable_form(app, raw):
    """
    normalise_phone() is a COMPARISON key (last nine digits). Storing that would
    leave imported tenants unlike every other row and unusable for SMS.
    """
    with app.app_context():
        assert bulk.canonical_phone(raw) == "+254712345678"


def test_an_unusable_phone_becomes_none(app):
    with app.app_context():
        assert bulk.canonical_phone("not a phone") is None


# ---------------------------------------------------------------------------
# Account numbers
# ---------------------------------------------------------------------------

def test_a_prefix_is_derived_from_the_property_name():
    assert bulk.derive_prefix("Kileleshwa Court") == "KC"
    assert bulk.derive_prefix("Riverside") == "RIV"
    assert bulk.derive_prefix("") == "U"


def test_composed_account_numbers_stay_in_the_pay_code_alphabet():
    """Read aloud on the phone and typed on a keypad — no spaces or symbols."""
    assert bulk.compose_account_number("KC", "A 1") == "KC-A1"
    assert bulk.compose_account_number("KC", "b/2") == "KC-B2"


# ---------------------------------------------------------------------------
# Validation — properties
# ---------------------------------------------------------------------------

def test_a_property_repeated_in_the_file_is_rejected(app, estate):
    parsed = _rows("Block,Town\nAlpha,Nairobi\nAlpha,Nairobi\n")
    mapping = bulk.suggest_mapping("properties", parsed["headers"])

    result = bulk.validate(estate.id, "properties", parsed["rows"], mapping)

    assert result["summary"]["valid"] == 1
    assert "appears twice" in result["rows"][1]["errors"][0]


def test_an_existing_property_is_a_warning_not_an_error(app, estate, db_session):
    """Re-running an import, or adding units to a known block, is normal."""
    db_session.add(Property(landlord_id=estate.id, name="Alpha", city="Nairobi"))
    db_session.flush()

    parsed = _rows("Block,Town\nAlpha,Nairobi\n")
    result = bulk.validate(estate.id, "properties", parsed["rows"],
                           bulk.suggest_mapping("properties", parsed["headers"]))

    assert result["rows"][0]["errors"] == []
    assert "already exists" in result["rows"][0]["warnings"][0]


# ---------------------------------------------------------------------------
# Validation — units. The account-number rules are the point.
# ---------------------------------------------------------------------------

@pytest.fixture()
def two_blocks(estate, db_session):
    for name in ("Alpha", "Beta"):
        db_session.add(Property(landlord_id=estate.id, name=name, city="Nairobi"))
    db_session.flush()
    return estate


def test_units_land_in_an_existing_property(app, two_blocks):
    parsed = _rows("Estate,House No.,Monthly Rent\nAlpha,A1,25000\n")
    result = bulk.validate(two_blocks.id, "units", parsed["rows"],
                           bulk.suggest_mapping("units", parsed["headers"]))

    assert result["summary"]["valid"] == 1


def test_a_unit_for_an_unknown_property_is_rejected(app, two_blocks):
    parsed = _rows("Estate,House No.,Monthly Rent\nGamma,C1,15000\n")
    result = bulk.validate(two_blocks.id, "units", parsed["rows"],
                           bulk.suggest_mapping("units", parsed["headers"]))

    assert "No property called 'Gamma'" in result["rows"][0]["errors"][0]


def test_the_same_account_number_twice_in_one_file_is_rejected(app, two_blocks):
    """
    The rule that matters most: two units sharing an account number means a
    tenant's payment lands on somebody else's lease.
    """
    parsed = _rows(
        "Estate,House No.,Monthly Rent,Acc No\n"
        "Alpha,A1,25000,DUP-1\n"
        "Beta,B1,30000,DUP-1\n"
    )
    result = bulk.validate(two_blocks.id, "units", parsed["rows"],
                           bulk.suggest_mapping("units", parsed["headers"]))

    assert result["summary"]["valid"] == 1
    assert "used twice in this file" in result["rows"][1]["errors"][0]


def test_an_account_number_already_on_the_account_is_rejected(app, two_blocks, db_session):
    """Uniqueness is per LANDLORD ACCOUNT, across every property."""
    prop = Property.query.filter_by(landlord_id=two_blocks.id, name="Alpha").first()
    unit = Unit(landlord_id=two_blocks.id, property_id=prop.id, name="Z9",
                rent_amount=Decimal("1000"), pay_code="TAKEN-1")
    db_session.add(unit)
    db_session.flush()

    parsed = _rows("Estate,House No.,Monthly Rent,Acc No\nBeta,B1,30000,TAKEN-1\n")
    result = bulk.validate(two_blocks.id, "units", parsed["rows"],
                           bulk.suggest_mapping("units", parsed["headers"]))

    assert "already in use on this account" in result["rows"][0]["errors"][0]


def test_auto_numbering_composes_a_code_per_property(app, two_blocks):
    parsed = _rows(
        "Estate,House No.,Monthly Rent\n"
        "Alpha,A1,25000\n"
        "Beta,B1,30000\n"
    )
    result = bulk.validate(
        two_blocks.id, "units", parsed["rows"],
        bulk.suggest_mapping("units", parsed["headers"]),
        {"auto_account_numbers": True, "separator": "-"},
    )

    codes = [r["values"]["account_number"] for r in result["rows"]]
    # "Alpha" is one word -> first three letters; see derive_prefix().
    assert codes == ["ALP-A1", "BET-B1"]
    assert all(not r["errors"] for r in result["rows"])


def test_auto_numbering_does_not_overwrite_a_supplied_code(app, two_blocks):
    parsed = _rows("Estate,House No.,Monthly Rent,Acc No\nAlpha,A1,25000,MINE-1\n")
    result = bulk.validate(
        two_blocks.id, "units", parsed["rows"],
        bulk.suggest_mapping("units", parsed["headers"]),
        {"auto_account_numbers": True},
    )

    assert result["rows"][0]["values"]["account_number"] == "MINE-1"


def test_the_same_unit_twice_in_one_property_is_rejected(app, two_blocks):
    parsed = _rows(
        "Estate,House No.,Monthly Rent\n"
        "Alpha,A1,25000\n"
        "Alpha,A1,25000\n"
    )
    result = bulk.validate(two_blocks.id, "units", parsed["rows"],
                           bulk.suggest_mapping("units", parsed["headers"]))

    assert "appears twice for Alpha" in " ".join(result["rows"][1]["errors"])


def test_the_same_unit_name_in_a_different_block_is_fine(app, two_blocks):
    """A1 in Alpha and A1 in Beta are different rooms — only the ACCOUNT
    NUMBER has to be unique across the book."""
    parsed = _rows(
        "Estate,House No.,Monthly Rent\n"
        "Alpha,A1,25000\n"
        "Beta,A1,30000\n"
    )
    result = bulk.validate(
        two_blocks.id, "units", parsed["rows"],
        bulk.suggest_mapping("units", parsed["headers"]),
        {"auto_account_numbers": True},
    )

    assert result["summary"]["valid"] == 2
    codes = [r["values"]["account_number"] for r in result["rows"]]
    assert len(set(codes)) == 2


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

def test_committing_units_writes_them_with_their_account_numbers(app, two_blocks):
    parsed = _rows(
        "Estate,House No.,Monthly Rent\n"
        "Alpha,A1,\"KES 25,000\"\n"
        "Alpha,A2,25000\n"
    )
    result = bulk.commit(
        two_blocks, "units", parsed["rows"],
        bulk.suggest_mapping("units", parsed["headers"]),
        {"auto_account_numbers": True},
    )

    assert result["created"] == 2
    units = Unit.query.filter_by(landlord_id=two_blocks.id).all()
    assert {u.name for u in units} == {"A1", "A2"}
    assert all(u.pay_code for u in units)
    assert {u.rent_amount for u in units} == {Decimal("25000.00")}


def test_bad_rows_are_skipped_and_the_good_ones_still_land(app, two_blocks):
    """
    400 units with three bad ones should import 397 and list the three. An
    all-or-nothing import just means nobody ever completes one.
    """
    parsed = _rows(
        "Estate,House No.,Monthly Rent\n"
        "Alpha,A1,25000\n"
        "Gamma,C1,15000\n"
        "Alpha,A2,25000\n"
    )
    result = bulk.commit(
        two_blocks, "units", parsed["rows"],
        bulk.suggest_mapping("units", parsed["headers"]),
        {"auto_account_numbers": True},
    )

    assert result["created"] == 2
    assert result["rejected"] == 1


def test_re_running_an_import_does_not_duplicate_units(app, two_blocks):
    text = "Estate,House No.,Monthly Rent\nAlpha,A1,25000\n"
    mapping = bulk.suggest_mapping("units", ["Estate", "House No.", "Monthly Rent"])
    options = {"auto_account_numbers": True}

    bulk.commit(two_blocks, "units", _rows(text)["rows"], mapping, options)
    second = bulk.commit(two_blocks, "units", _rows(text)["rows"], mapping, options)

    assert second["created"] == 0
    assert second["skipped"] == 1
    assert Unit.query.filter_by(landlord_id=two_blocks.id).count() == 1


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

@pytest.fixture()
def stocked(two_blocks):
    """Two blocks with a unit each, ready for tenants."""
    parsed = _rows(
        "Estate,House No.,Monthly Rent\n"
        "Alpha,A1,25000\n"
        "Beta,B1,30000\n"
    )
    bulk.commit(two_blocks, "units", parsed["rows"],
                bulk.suggest_mapping("units", parsed["headers"]),
                {"auto_account_numbers": True})
    return two_blocks


def test_a_tenant_is_matched_to_a_unit_by_account_number(app, stocked):
    parsed = _rows("Account,First,Surname,Mobile\nALP-A1,Amina,Otieno,0712345678\n")
    result = bulk.commit(stocked, "tenants", parsed["rows"],
                         bulk.suggest_mapping("tenants", parsed["headers"]))

    assert result["created"] == 1
    tenant = Tenant.query.filter_by(landlord_id=stocked.id).first()
    assert tenant.phone == "+254712345678"
    assert tenant.unit.name == "A1"


def test_a_tenant_can_be_matched_by_property_and_unit(app, stocked):
    parsed = _rows("Unit,First,Surname,Mobile\nAlpha / A1,Amina,Otieno,0712345678\n")
    result = bulk.validate(stocked.id, "tenants", parsed["rows"],
                           bulk.suggest_mapping("tenants", parsed["headers"]))

    assert result["rows"][0]["errors"] == []


def test_an_unknown_unit_reference_is_rejected(app, stocked):
    parsed = _rows("Account,First,Surname,Mobile\nZZ-NOPE,Erick,Kip,0755777888\n")
    result = bulk.validate(stocked.id, "tenants", parsed["rows"],
                           bulk.suggest_mapping("tenants", parsed["headers"]))

    assert "No unit matches" in result["rows"][0]["errors"][0]


def test_two_tenants_into_one_unit_is_rejected(app, stocked):
    parsed = _rows(
        "Account,First,Surname,Mobile\n"
        "ALP-A1,Amina,Otieno,0712345678\n"
        "ALP-A1,David,Mwangi,0744555666\n"
    )
    result = bulk.validate(stocked.id, "tenants", parsed["rows"],
                           bulk.suggest_mapping("tenants", parsed["headers"]))

    assert "Two tenants in this file" in " ".join(result["rows"][1]["errors"])


def test_one_person_in_several_units_is_flagged_but_allowed(app, stocked):
    """
    Exactly why account numbers must be unique — and also what a copy-paste
    error looks like, so it is surfaced as a warning rather than blocked.
    """
    parsed = _rows(
        "Account,First,Surname,Mobile\n"
        "ALP-A1,Amina,Otieno,0712345678\n"
        "BET-B1,Amina,Otieno,0712345678\n"
    )
    result = bulk.validate(stocked.id, "tenants", parsed["rows"],
                           bulk.suggest_mapping("tenants", parsed["headers"]))

    assert result["summary"]["valid"] == 2
    assert all("Same person as line" in " ".join(r["warnings"]) for r in result["rows"])


def test_an_occupied_unit_is_rejected(app, stocked):
    text = "Account,First,Surname,Mobile\nALP-A1,Amina,Otieno,0712345678\n"
    mapping = bulk.suggest_mapping("tenants", ["Account", "First", "Surname", "Mobile"])
    bulk.commit(stocked, "tenants", _rows(text)["rows"], mapping)

    result = bulk.validate(stocked.id, "tenants", _rows(
        "Account,First,Surname,Mobile\nALP-A1,David,Mwangi,0744555666\n")["rows"], mapping)

    assert "already has a tenant" in result["rows"][0]["errors"][0]


def test_an_opening_balance_becomes_a_traceable_invoice(app, stocked):
    """
    Not a magic number on the tenant row: the balance needs provenance so it
    appears on a statement and can be paid off through the normal allocation.
    """
    from models import Invoice

    parsed = _rows(
        "Account,First,Surname,Mobile,Arrears\n"
        "ALP-A1,Amina,Otieno,0712345678,\"12,500\"\n"
    )
    bulk.commit(stocked, "tenants", parsed["rows"],
                bulk.suggest_mapping("tenants", parsed["headers"]))

    tenant = Tenant.query.filter_by(landlord_id=stocked.id).first()
    assert tenant.balance == Decimal("12500")

    invoice = Invoice.query.filter_by(landlord_id=stocked.id, tenant_id=tenant.id).first()
    assert invoice is not None
    assert invoice.total_amount == Decimal("12500")
    # invoices.property_id is NOT NULL — every property report depends on it.
    assert invoice.property_id is not None


def test_importing_a_tenant_marks_the_unit_occupied(app, stocked):
    parsed = _rows("Account,First,Surname,Mobile\nALP-A1,Amina,Otieno,0712345678\n")
    bulk.commit(stocked, "tenants", parsed["rows"],
                bulk.suggest_mapping("tenants", parsed["headers"]))

    unit = Unit.query.filter_by(landlord_id=stocked.id, name="A1").first()
    assert unit.is_occupied is True
