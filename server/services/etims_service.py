"""
services/etims_service.py — the manual-first KRA / eTIMS compliance layer.

SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md. Read §0 before changing anything here.

WHAT THIS IS NOT
----------------
There is no integration with KRA. Nothing in this module calls eTIMS, OSCU,
VSCU or iTax; nothing generates an invoice number; nothing verifies that a
number a user typed really exists. Landlords, property managers and SahilPay
itself issue their official invoices OUTSIDE the app through KRA's free
channels (eCitizen, *222#, the eTIMS Non-VAT app) and then record the resulting
numbers here. Validation is therefore FORMAT-ONLY, deliberately.

THE GOLDEN RULE: OPTIONAL AND SILENT
------------------------------------
The whole layer is opt-in per property and defaults to OFF. When it is off, or
when a record simply has no number, the app must look EXACTLY as it did before
this feature existed: no empty column, no "pending" badge, no warning colour,
no greyed-out anything. Absence is invisible — it is never flagged, counted at
the user, or styled as a problem.

Consequently this module has no concept of "missing", "overdue" or
"non-compliant", and no user-facing string it produces may use those words. The
single place a coverage number appears at all is the neutral count line on the
KRA Monthly Report ("eTIMS invoices recorded: N of M payments"), and even that
is only reachable from an opt-in report.

MRI figures produced here are a computational aid for the taxpayer's own
filing. Nothing is withheld, deducted or remitted.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from extensions import db
from utils import ApiError

ZERO = Decimal("0.00")

# Kenya's Monthly Rental Income rate — 7.5% of GROSS rent RECEIVED, with no
# deductions permitted under the MRI regime. Display/reference only.
MRI_RATE = Decimal("0.075")

# KRA PIN: one letter (A = individual, P = non-individual), nine digits, one
# checking letter. e.g. A012345678B / P051234567X.
_KRA_PIN_RE = re.compile(r"^[AP]\d{9}[A-Z]$")

# eTIMS number formats vary by channel and keep changing, so this is a light
# sanity check rather than a grammar: printable invoice-ish characters only.
_ETIMS_NUMBER_RE = re.compile(r"^[A-Za-z0-9/\-. ]{1,64}$")

# The three tables that carry an eTIMS number, and the invoice each represents.
#   payment      landlord → tenant, under the property OWNER's PIN
#   payout       PM → landlord, for the commission, under the PM's PIN
#   subscription SahilPay → client, under SahilPay's PIN (admin-entered only)
RECORD_KINDS = ("payment", "payout", "subscription")


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def platform_settings():
    """The single global settings row, created on first read."""
    from models import PlatformSettings

    row = db.session.query(PlatformSettings).order_by(PlatformSettings.id.asc()).first()
    if row is None:
        row = PlatformSettings(etims_features_enabled=True)
        db.session.add(row)
        db.session.flush()
    return row


def features_enabled() -> bool:
    """
    Whether the eTIMS layer may render at all, platform-wide.

    The env var is the kill switch and wins over the database, so an incident
    can be contained by a redeploy without touching data.
    """
    from flask import current_app

    if not current_app.config.get("ETIMS_FEATURES_ENABLED", True):
        return False
    return bool(platform_settings().etims_features_enabled)


def account_enabled(landlord_id: int) -> bool:
    """Whether this account has switched the layer on for itself (§2.1)."""
    from models import LandlordSettings

    if not features_enabled():
        return False
    settings = (
        db.session.query(LandlordSettings)
        .filter_by(landlord_id=landlord_id)
        .first()
    )
    return bool(settings and settings.etims_enabled)


# ---------------------------------------------------------------------------
# Validation / normalisation
# ---------------------------------------------------------------------------

def normalise_kra_pin(value, field: str = "kra_pin") -> str | None:
    """
    Clean and validate a KRA PIN. Blank is always valid and returns None — a
    PIN is never required and never blocks a save.

    Accepts any case and surrounding whitespace, stores uppercase.
    """
    if value is None:
        return None
    pin = str(value).strip().upper().replace(" ", "")
    if not pin:
        return None
    if not _KRA_PIN_RE.match(pin):
        raise ApiError(
            "That doesn't look like a KRA PIN. The format is one letter, "
            "nine digits and one letter — for example A012345678B.",
            status=422,
            errors={field: "invalid_kra_pin"},
        )
    return pin


def normalise_invoice_number(value) -> str | None:
    """Clean an eTIMS invoice number. Blank returns None (i.e. 'not recorded')."""
    if value is None:
        return None
    number = " ".join(str(value).split())
    if not number:
        return None
    if len(number) > 64:
        raise ApiError(
            "That eTIMS invoice number is too long (64 characters maximum).",
            status=422, errors={"etims_invoice_number": "too_long"},
        )
    if not _ETIMS_NUMBER_RE.match(number):
        raise ApiError(
            "An eTIMS invoice number can contain letters, numbers and the "
            "characters / - . only.",
            status=422, errors={"etims_invoice_number": "invalid_characters"},
        )
    return number


def _parse_issued_at(value) -> datetime | None:
    """Accept a date or datetime, in ISO form, or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip().replace("Z", "+00:00")
    for parse in (datetime.fromisoformat,
                  lambda t: datetime.strptime(t, "%Y-%m-%d")):
        try:
            parsed = parse(text)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except (ValueError, TypeError):
            continue
    raise ApiError("Enter the issue date as YYYY-MM-DD.", status=422,
                   errors={"etims_issued_at": "invalid_date"})


def normalise_qr_url(value) -> str | None:
    """A KRA verification URL, if the user pasted one. http(s) only."""
    if value is None:
        return None
    url = str(value).strip()
    if not url:
        return None
    if len(url) > 512:
        raise ApiError("That verification link is too long.", status=422,
                       errors={"etims_qr_url": "too_long"})
    if not url.lower().startswith(("http://", "https://")):
        raise ApiError("The verification link should start with https://",
                       status=422, errors={"etims_qr_url": "invalid_url"})
    return url


# ---------------------------------------------------------------------------
# Scoping — enforced server-side on every read and write
# ---------------------------------------------------------------------------

def _model_for(kind: str):
    from models import BillingTransaction, OwnerPayout, Payment

    return {"payment": Payment, "payout": OwnerPayout,
            "subscription": BillingTransaction}[kind]


def tax_property_ids(landlord_id: int) -> set[int]:
    """
    The properties on which the CURRENT caller may do compliance work.

    Three filters, all applied:
      1. the property belongs to this account and has eTIMS switched on;
      2. the caller can see it at all (the existing team-member property
         scoping);
      3. for a team member, they hold `manage_tax_compliance` on it
         specifically — the module permission alone grants nothing.

    A landlord, PM, or impersonating admin passes filters 2 and 3 freely.
    Returning an empty set is the normal, silent state for anyone who has not
    opted in; callers must render nothing rather than an empty-state warning.
    """
    from models import (
        Property, TeamMemberPropertyPermission as TMPP,
    )
    from utils import accessible_property_ids, get_jwt_user

    if not account_enabled(landlord_id):
        return set()

    rows = (
        db.session.query(Property.id)
        .filter(Property.landlord_id == landlord_id,
                Property.is_deleted.is_(False),
                Property.etims_enabled.is_(True))
        .all()
    )
    ids = {r[0] for r in rows}

    visible = accessible_property_ids()
    if visible is not None:
        ids &= set(visible)

    try:
        user = get_jwt_user()
    except ApiError:
        return set()

    if user.role == "team_member":
        tm = user.team_member_profile
        if tm is None:
            return set()
        granted = {
            r[0] for r in db.session.query(TMPP.property_id).filter(
                TMPP.team_member_id == tm.id,
                TMPP.permission == TMPP.PERM_MANAGE_TAX_COMPLIANCE,
            ).all()
        }
        ids &= granted

    return ids


def assert_can_manage(landlord_id: int, property_id: int | None) -> None:
    """Raise 403 unless the caller may record eTIMS data on *property_id*."""
    if property_id is None or property_id not in tax_property_ids(landlord_id):
        raise ApiError(
            "You don't have tax-compliance access to this property.",
            status=403, code="no_tax_compliance_scope",
        )


def is_system_admin() -> bool:
    from utils import get_jwt_user

    try:
        return get_jwt_user().role == "system_admin"
    except ApiError:
        return False


# ---------------------------------------------------------------------------
# Recording a number
# ---------------------------------------------------------------------------

def _duplicate_holder(kind: str, number: str, exclude_id: int | None):
    """The record that already carries *number*, if any."""
    model = _model_for(kind)
    query = db.session.query(model).filter(model.etims_invoice_number == number)
    if exclude_id is not None:
        query = query.filter(model.id != exclude_id)
    return query.first()


def record_number(record, kind: str, *, invoice_number, issued_at=None,
                  qr_url=None, actor_user_id: int | None = None):
    """
    Attach (or update) an eTIMS invoice number on one record.

    Passing a blank invoice_number CLEARS the entry — the record simply goes
    back to having no number, which is an ordinary state, not an error.

    Latest write wins. The previous value is written to the application log for
    traceability, and `etims_entered_by_user_id` always names whoever typed the
    value that is currently stored.
    """
    from flask import current_app

    number = normalise_invoice_number(invoice_number)

    if number is None:
        previous = record.etims_invoice_number
        record.etims_invoice_number = None
        record.etims_issued_at = None
        record.etims_qr_url = None
        record.etims_entered_by_user_id = actor_user_id
        if previous:
            current_app.logger.info(
                "[etims] cleared %s #%s (was %s) by user %s",
                kind, record.id, previous, actor_user_id,
            )
        return record

    clash = _duplicate_holder(kind, number, exclude_id=record.id)
    if clash is not None:
        label = {"payment": "payment", "payout": "payout",
                 "subscription": "subscription payment"}[kind]
        raise ApiError(
            f"This eTIMS invoice number is already recorded on {label} #{clash.id}.",
            status=409,
            errors={"etims_invoice_number": "duplicate"},
            code="etims_duplicate",
        )

    previous = record.etims_invoice_number
    record.etims_invoice_number = number
    record.etims_issued_at = _parse_issued_at(issued_at) or datetime.utcnow()
    record.etims_qr_url = normalise_qr_url(qr_url)
    record.etims_entered_by_user_id = actor_user_id
    if previous and previous != number:
        current_app.logger.info(
            "[etims] %s #%s number changed %s -> %s by user %s",
            kind, record.id, previous, number, actor_user_id,
        )
    return record


# ---------------------------------------------------------------------------
# The eTIMS Register (§4.2)
# ---------------------------------------------------------------------------

def month_bounds(month: str | None) -> tuple[date, date]:
    """'YYYY-MM' → (first day, last day). Defaults to the current month."""
    today = date.today()
    if not month:
        year, mon = today.year, today.month
    else:
        try:
            year, mon = (int(p) for p in str(month).split("-", 1))
            if not 1 <= mon <= 12:
                raise ValueError
        except (ValueError, TypeError):
            raise ApiError("Use YYYY-MM for the month.", status=422,
                           errors={"month": "invalid_month"})
    return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])


def register_rows(landlord_id: int, *, scope: str = "payments",
                  property_ids: list[int] | None = None,
                  month: str | None = None,
                  status: str = "all") -> list[dict]:
    """
    The Register's table body — one row per record the caller may record a
    number against, in the chosen month.

    `status` filters with NEUTRAL labels only: "all" | "recorded" |
    "not_recorded". "not_recorded" is a working filter for someone doing data
    entry, NOT a compliance judgement, and nothing else in the app may present
    the absence of a number as a state worth flagging.
    """
    from models import NON_CASH_PAYMENT_SOURCES, OwnerPayout, Payment, PaymentStatus

    allowed = tax_property_ids(landlord_id)
    if property_ids:
        allowed &= set(property_ids)
    if not allowed:
        return []

    start, end = month_bounds(month)

    if scope == "payouts":
        query = (
            db.session.query(OwnerPayout)
            .filter(OwnerPayout.landlord_id == landlord_id,
                    OwnerPayout.property_id.in_(allowed),
                    OwnerPayout.payout_date >= start,
                    OwnerPayout.payout_date <= end)
            .order_by(OwnerPayout.payout_date.asc(), OwnerPayout.id.asc())
        )
        records = query.all()
        rows = [{
            "kind":        "payout",
            "id":          payout.id,
            "date":        payout.payout_date.isoformat() if payout.payout_date else None,
            "property_id": payout.property_id,
            "property":    payout.property.name if payout.property else None,
            "counterparty": (payout.property.owner.full_name
                             if payout.property and payout.property.owner else None),
            "unit":        None,
            "reference":   payout.reference,
            "amount":      str(payout.amount or ZERO),
            **payout.etims_dict(),
        } for payout in records]
    else:
        query = (
            db.session.query(Payment)
            .filter(Payment.landlord_id == landlord_id,
                    Payment.property_id.in_(allowed),
                    Payment.is_deleted.is_(False),
                    Payment.status == PaymentStatus.confirmed.value,
                    # Credit re-applications move money that was already
                    # received and invoiced; they are not a new sale.
                    db.func.coalesce(Payment.source, "").notin_(tuple(NON_CASH_PAYMENT_SOURCES)),
                    Payment.payment_date >= start,
                    Payment.payment_date <= end)
            .order_by(Payment.payment_date.asc(), Payment.id.asc())
        )
        records = query.all()
        rows = [{
            "kind":        "payment",
            "id":          payment.id,
            "date":        payment.payment_date.isoformat() if payment.payment_date else None,
            "property_id": payment.property_id,
            "property":    payment.property.name if payment.property else None,
            "counterparty": (f"{payment.tenant.first_name} {payment.tenant.last_name}".strip()
                             if payment.tenant else None),
            "unit":        payment.unit.name if payment.unit else None,
            "reference":   payment.payment_ref,
            "amount":      str(payment.amount or ZERO),
            **payment.etims_dict(),
        } for payment in records]

    if status == "recorded":
        rows = [r for r in rows if r["etims_invoice_number"]]
    elif status == "not_recorded":
        rows = [r for r in rows if not r["etims_invoice_number"]]
    return rows


def bulk_record(landlord_id: int, records: list[dict], *,
                actor_user_id: int | None = None) -> dict:
    """
    Save many rows in one request (§4.2).

    Every row is attempted independently: a bad row reports its own error and
    the valid rows around it still save. That matters because the Register is a
    bulk data-entry screen — losing nine good rows to one typo would make it
    unusable.
    """
    saved, errors = [], []

    for index, row in enumerate(records or []):
        kind = (row.get("type") or row.get("kind") or "payment").strip()
        record_id = row.get("id")
        # A SAVEPOINT per row: a database-level failure (a unique violation
        # racing another user) aborts only this row's work, leaving the session
        # usable so the rest of the batch still commits.
        savepoint = db.session.begin_nested()
        try:
            if kind not in RECORD_KINDS:
                raise ApiError(f"Unknown record type '{kind}'.", status=422)

            model = _model_for(kind)
            record = db.session.get(model, record_id)
            if record is None:
                raise ApiError("That record no longer exists.", status=404)

            if kind == "subscription":
                # SahilPay is the seller on a subscription invoice, so only
                # SahilPay's own staff may record its numbers.
                if not is_system_admin():
                    raise ApiError("Only a system administrator can record "
                                   "subscription eTIMS numbers.", status=403)
            else:
                if record.landlord_id != landlord_id and not is_system_admin():
                    raise ApiError("That record belongs to another account.", status=403)
                if not is_system_admin():
                    assert_can_manage(landlord_id, record.property_id)

            record_number(
                record, kind,
                invoice_number=row.get("etims_invoice_number"),
                issued_at=row.get("etims_issued_at"),
                qr_url=row.get("etims_qr_url"),
                actor_user_id=actor_user_id,
            )
            db.session.flush()
            savepoint.commit()
            saved.append({"index": index, "kind": kind, "id": record_id,
                          **record.etims_dict()})
        except ApiError as exc:
            savepoint.rollback()
            errors.append({"index": index, "kind": kind, "id": record_id,
                           "message": exc.message, "errors": exc.errors})
        except IntegrityError:
            savepoint.rollback()
            errors.append({"index": index, "kind": kind, "id": record_id,
                           "message": "That eTIMS invoice number is already "
                                      "recorded on another record.",
                           "errors": {"etims_invoice_number": "duplicate"}})

    return {"saved": saved, "errors": errors,
            "saved_count": len(saved), "error_count": len(errors)}


# ---------------------------------------------------------------------------
# KRA Monthly Report (§4.3)
# ---------------------------------------------------------------------------

def _rent_received(landlord_id: int, property_ids: set[int],
                   start: date, end: date) -> tuple[Decimal, list[dict], int]:
    """
    Gross rent RECEIVED in the window, on a CASH basis, with its appendix.

    Cash basis is the whole point: MRI is charged on what actually landed in
    the month, whichever month's rent it settles. A tenant clearing three
    months of arrears in March is taxed in March. Conversely rent invoiced in
    March but unpaid is not taxed at all until it arrives.

    Only allocations to the Rent category count (current + balance); deposits
    are the tenant's own refundable money and every other charge is a
    reimbursement, so both are excluded — the same base the commission engine
    already uses, so the two can never disagree.
    """
    from models import (
        InvoiceLineItem, NON_CASH_PAYMENT_SOURCES, Payment, PaymentAllocation,
        PaymentStatus,
    )
    from services.category_service import RENT_INCOME_SUBCATEGORIES, rent_category_id

    if not property_ids:
        return ZERO, [], 0

    rent_cat_id = rent_category_id(landlord_id)

    payments = (
        db.session.query(Payment)
        .filter(Payment.landlord_id == landlord_id,
                Payment.property_id.in_(property_ids),
                Payment.is_deleted.is_(False),
                Payment.status == PaymentStatus.confirmed.value,
                db.func.coalesce(Payment.source, "").notin_(tuple(NON_CASH_PAYMENT_SOURCES)),
                Payment.payment_date >= start,
                Payment.payment_date <= end)
        .order_by(Payment.payment_date.asc(), Payment.id.asc())
        .all()
    )
    if not payments:
        return ZERO, [], 0

    payment_ids = [p.id for p in payments]
    rent_rows = (
        db.session.query(
            PaymentAllocation.payment_id,
            db.func.coalesce(db.func.sum(PaymentAllocation.amount_allocated), 0),
        )
        .join(InvoiceLineItem, InvoiceLineItem.id == PaymentAllocation.line_item_id)
        .filter(PaymentAllocation.payment_id.in_(payment_ids),
                InvoiceLineItem.category_id == rent_cat_id,
                InvoiceLineItem.subcategory.in_(tuple(RENT_INCOME_SUBCATEGORIES)))
        .group_by(PaymentAllocation.payment_id)
        .all()
    ) if rent_cat_id is not None else []
    rent_by_payment = {pid: Decimal(str(amount or 0)) for pid, amount in rent_rows}

    total = ZERO
    appendix: list[dict] = []
    recorded = 0
    for payment in payments:
        rent = rent_by_payment.get(payment.id, ZERO)
        if rent <= ZERO:
            # Nothing in this payment cleared rent (a pure deposit or utility
            # settlement), so it is outside the MRI base entirely.
            continue
        total += rent
        if payment.etims_invoice_number:
            recorded += 1
        appendix.append({
            "payment_id":  payment.id,
            "date":        payment.payment_date.isoformat() if payment.payment_date else None,
            "tenant":      (f"{payment.tenant.first_name} {payment.tenant.last_name}".strip()
                            if payment.tenant else None),
            "unit":        payment.unit.name if payment.unit else None,
            "property":    payment.property.name if payment.property else None,
            "property_id": payment.property_id,
            "amount":      str(rent.quantize(Decimal("0.01"))),
            "etims_invoice_number": payment.etims_invoice_number,
        })

    return total.quantize(Decimal("0.01")), appendix, recorded


def kra_monthly_report(landlord_id: int, *, month: str | None = None,
                       property_id: int | None = None,
                       owner_id: int | None = None,
                       consolidated: bool = True) -> dict:
    """
    The filing aid (§4.3).

    Grouping follows who actually files the return. Under a PM account each
    block belongs to a different owner, and each of THOSE people files their
    own MRI — so the consolidated figure is computed per PropertyOwner, across
    all of that owner's properties. A landlord managing their own blocks has no
    owner rows and consolidates into a single group under their own name.

    The 7.5% figure is indicative and is never withheld or remitted by SahilPay.
    """
    from models import Landlord, Property

    start, end = month_bounds(month)
    allowed = tax_property_ids(landlord_id)
    if property_id:
        allowed &= {property_id}
    if not allowed:
        return {
            "month": start.strftime("%Y-%m"), "period_start": start.isoformat(),
            "period_end": end.isoformat(), "groups": [],
            "totals": {"gross_rent_received": "0.00", "mri_due": "0.00",
                       "etims_recorded": 0, "payments_counted": 0},
            "mri_rate": str(MRI_RATE), "consolidated": consolidated,
            "disclaimer": DISCLAIMER,
        }

    properties = (
        db.session.query(Property)
        .filter(Property.id.in_(allowed))
        .order_by(Property.name.asc())
        .all()
    )
    if owner_id:
        properties = [p for p in properties if p.owner_id == owner_id]

    landlord = db.session.get(Landlord, landlord_id)
    account_name = landlord.company_name if landlord else "This account"

    # Group by the taxpayer: the property's owner when there is one, otherwise
    # the account holder (a landlord managing their own blocks).
    buckets: dict[tuple, list] = {}
    for prop in properties:
        if consolidated:
            key = (("owner", prop.owner_id) if prop.owner_id
                   else ("account", landlord_id))
        else:
            key = ("property", prop.id)
        buckets.setdefault(key, []).append(prop)

    groups = []
    grand_gross, grand_recorded, grand_counted = ZERO, 0, 0

    for key, props in buckets.items():
        kind = key[0]
        ids = {p.id for p in props}
        gross, appendix, recorded = _rent_received(landlord_id, ids, start, end)

        if kind == "owner":
            owner = props[0].owner
            name = owner.full_name if owner else account_name
            pin = owner.kra_pin if owner else None
        elif kind == "property":
            name = props[0].name
            pin = props[0].effective_kra_pin
        else:
            name = account_name
            pin = (landlord.user.kra_pin if landlord and landlord.user else None)

        mri = (gross * MRI_RATE).quantize(Decimal("0.01"))
        grand_gross += gross
        grand_recorded += recorded
        grand_counted += len(appendix)

        groups.append({
            "key":                 f"{kind}:{key[1]}",
            "group_type":          kind,
            "name":                name,
            "kra_pin":             pin,
            "properties":          [{"id": p.id, "name": p.name} for p in props],
            "gross_rent_received": str(gross),
            "mri_due":             str(mri),
            # The ONLY coverage figure anywhere in the product, phrased
            # neutrally. Never styled as a warning.
            "etims_recorded":      recorded,
            "payments_counted":    len(appendix),
            "coverage_line":       f"eTIMS invoices recorded: {recorded} of {len(appendix)} payments.",
            "appendix":            appendix,
        })

    groups.sort(key=lambda g: g["name"] or "")

    return {
        "month":         start.strftime("%Y-%m"),
        "period_start":  start.isoformat(),
        "period_end":    end.isoformat(),
        "consolidated":  consolidated,
        "mri_rate":      str(MRI_RATE),
        "groups":        groups,
        "totals": {
            "gross_rent_received": str(grand_gross.quantize(Decimal("0.01"))),
            "mri_due":             str((grand_gross * MRI_RATE).quantize(Decimal("0.01"))),
            "etims_recorded":      grand_recorded,
            "payments_counted":    grand_counted,
        },
        "filing_note": (
            "Indicative Monthly Rental Income tax (7.5% of gross rent received). "
            "File and pay via iTax/eRITS by the 20th of the following month."
        ),
        "disclaimer": DISCLAIMER,
    }


DISCLAIMER = (
    "This report is a computational aid, not tax advice. Confirm your filing "
    "obligations with KRA or a tax professional."
)
