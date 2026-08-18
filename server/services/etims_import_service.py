"""
services/etims_import_service.py — putting KRA control numbers back onto the
payments they belong to, in bulk.

A landlord who invoices through eTIMS ends up with numbers issued OUTSIDE this
system — typed into the KRA portal, produced by an accountant's own tooling,
handed back as a spreadsheet at the end of the month. Re-keying four hundred of
them is a morning's work and, worse, a morning's opportunity to put the right
number on the wrong payment.

THE ONLY THING THAT MATTERS HERE IS BEING RIGHT.

A control number on the wrong payment is not a cosmetic error: it attests to
KRA that a particular sale happened, under a particular invoice, for a
particular amount. So the matching rules are deliberately conservative:

  EXACTLY ONE MATCH, OR NONE.  A row matches when it identifies exactly one
    payment. Two candidates is AMBIGUOUS and is never resolved by picking the
    likelier one — it is handed back for a human to choose.

  REFERENCE FIRST.  Our payment reference, then the M-Pesa code. Both name one
    payment. Amount-and-date is offered only as an explicit fallback, because
    two tenants paying 25,000 rent on the 1st is the normal case, not an edge
    one — on its own it identifies a payment about as well as a shoe size.

  AMOUNT IS A CHECK, NOT A KEY.  When the file carries an amount and it
    disagrees with the payment we matched, that is reported as a MISMATCH
    rather than quietly applied. A number attached to a differing amount is
    precisely the error this importer exists to avoid.

Nothing is written until the caller confirms, and every write goes through
etims_service.record_number(), so the duplicate-number rule and the audit trail
are the same ones a hand-typed number gets.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Matching strategies, in the order they are attempted.
MATCH_REFERENCE = "reference"
MATCH_MPESA = "mpesa"
MATCH_AMOUNT_DATE = "amount_date"

# Row outcomes.
STATUS_MATCHED = "matched"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNMATCHED = "unmatched"
STATUS_MISMATCH = "amount_mismatch"
STATUS_ALREADY = "already_recorded"
STATUS_INVALID = "invalid"

FIELDS = [
    {"key": "reference", "label": "Our reference", "required": False,
     "help": "The payment reference or M-Pesa code — whichever your file carries.",
     "aliases": ("reference", "ref", "payment_ref", "receipt", "receipt_no",
                 "mpesa", "mpesa_code", "mpesa_reference", "transaction",
                 "transaction_id", "trans_id")},
    {"key": "etims_invoice_number", "label": "eTIMS invoice number", "required": True,
     "help": "The control number KRA issued.",
     "aliases": ("etims", "etims_invoice_number", "control_number", "cu_invoice_number",
                 "invoice_number", "kra_invoice", "cu_number", "control_no")},
    {"key": "issued_at", "label": "Issued at", "required": False,
     "help": "When KRA issued it. Defaults to now.",
     "aliases": ("issued_at", "issued", "date_issued", "timestamp", "issue_date")},
    {"key": "qr_url", "label": "QR / verification URL", "required": False,
     "aliases": ("qr", "qr_url", "qr_code", "verification_url", "link", "url")},
    {"key": "amount", "label": "Amount", "required": False,
     "help": "Optional, and worth including — it is checked against the payment "
             "we match and a disagreement is reported rather than applied.",
     "aliases": ("amount", "total", "value", "gross", "paid")},
    {"key": "payment_date", "label": "Payment date", "required": False,
     "help": "Only used when matching by amount + date.",
     "aliases": ("date", "payment_date", "paid_on", "transaction_date")},
]


def catalogue() -> list[dict]:
    return [{k: v for k, v in f.items() if k != "aliases"} for f in FIELDS]


def suggest_mapping(headers: list[str]) -> dict:
    from services.bulk_import_service import _slug

    by_slug = {_slug(h): h for h in headers if h}
    mapping, taken = {}, set()
    for field in FIELDS:
        for candidate in (field["key"],) + field["aliases"]:
            header = by_slug.get(_slug(candidate))
            if header and header not in taken:
                mapping[field["key"]] = header
                taken.add(header)
                break
    return mapping


def _decimal(value):
    if value in (None, ""):
        return None
    text = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    try:
        return Decimal(text) if text not in ("", "-", ".") else None
    except InvalidOperation:
        return None


def _date(value):
    from services.bulk_import_service import _to_date

    parsed, _error = _to_date(value, "payment date")
    return parsed


def _candidates_for(landlord_id: int, reference: str | None, amount, when,
                    *, allow_amount_date: bool):
    """
    Payments this row could name, and how it was found.

    Returns (matches, strategy). An empty list means nothing matched; more than
    one means ambiguous — never "pick the first".
    """
    from extensions import db
    from models import NON_CASH_PAYMENT_SOURCES, Payment, PaymentStatus

    base = (
        db.session.query(Payment)
        .filter(Payment.landlord_id == landlord_id,
                Payment.is_deleted.is_(False),
                Payment.status == PaymentStatus.confirmed.value,
                db.func.coalesce(Payment.source, "").notin_(tuple(NON_CASH_PAYMENT_SOURCES)))
    )

    if reference:
        needle = str(reference).strip()
        # Our own reference names exactly one payment.
        found = base.filter(db.func.upper(Payment.payment_ref) == needle.upper()).all()
        if found:
            return found, MATCH_REFERENCE
        # An M-Pesa code also names exactly one.
        found = base.filter(db.func.upper(Payment.mpesa_reference) == needle.upper()).all()
        if found:
            return found, MATCH_MPESA

    # Amount + date identifies a payment poorly — two tenants paying the same
    # rent on the 1st is the ordinary case — so it is opt-in, and any tie is
    # reported as ambiguous rather than guessed.
    if allow_amount_date and amount is not None and when is not None:
        found = (base
                 .filter(Payment.amount == amount, Payment.payment_date == when)
                 .all())
        if found:
            return found, MATCH_AMOUNT_DATE

    return [], None


def _payment_summary(payment) -> dict:
    tenant = payment.tenant
    return {
        "payment_id":    payment.id,
        "payment_ref":   payment.payment_ref,
        "amount":        float(payment.amount or 0),
        "payment_date":  payment.payment_date.isoformat() if payment.payment_date else None,
        "tenant_name":   f"{tenant.first_name} {tenant.last_name}".strip() if tenant else None,
        "unit_name":     payment.unit.name if payment.unit else None,
        "property_name": payment.property.name if payment.property else None,
        "existing_etims_number": payment.etims_invoice_number,
    }


def validate(landlord_id: int, rows: list[dict], mapping: dict,
             options: dict | None = None) -> dict:
    """
    Work out what each row would do, writing nothing.

    Every row comes back with a status and, where relevant, the payment it
    matched — because the reviewer's job is to confirm that THIS number belongs
    to THAT payment, and they cannot do it from a count.
    """
    from services import etims_service

    options = options or {}
    allow_amount_date = bool(options.get("allow_amount_date_match"))

    results = []
    seen_numbers: dict[str, int] = {}

    for row in rows:
        def cell(key):
            header = mapping.get(key)
            return row.get(header) if header else None

        line = row.get("_line")
        number_raw = cell("etims_invoice_number")
        number = etims_service.normalise_invoice_number(number_raw)

        entry = {
            "_line": line,
            "etims_invoice_number": number,
            "reference": (str(cell("reference")).strip() if cell("reference") else None),
            "amount": None,
            "payment": None,
            "match_strategy": None,
            "status": STATUS_INVALID,
            "message": None,
        }

        if not number:
            entry["message"] = "No eTIMS invoice number on this row."
            results.append(entry)
            continue

        # A number appearing twice in one file is a file problem, and applying
        # either copy would be a guess about which payment it belongs to.
        if number in seen_numbers:
            entry["status"] = STATUS_INVALID
            entry["message"] = (f"'{number}' appears twice in this file "
                                f"(also line {seen_numbers[number]}).")
            results.append(entry)
            continue
        seen_numbers[number] = line

        amount = _decimal(cell("amount"))
        when = _date(cell("payment_date"))
        entry["amount"] = float(amount) if amount is not None else None

        matches, strategy = _candidates_for(
            landlord_id, entry["reference"], amount, when,
            allow_amount_date=allow_amount_date)
        entry["match_strategy"] = strategy

        if not matches:
            entry["status"] = STATUS_UNMATCHED
            entry["message"] = (
                "No payment matches this row."
                + ("" if entry["reference"] else
                   " There is no reference on it — add one, or enable "
                   "amount-and-date matching and include both.")
            )
            results.append(entry)
            continue

        if len(matches) > 1:
            entry["status"] = STATUS_AMBIGUOUS
            entry["candidates"] = [_payment_summary(p) for p in matches[:5]]
            entry["message"] = (
                f"{len(matches)} payments match this row. Pick the right one — "
                f"a control number on the wrong payment misstates a sale to KRA."
            )
            results.append(entry)
            continue

        payment = matches[0]
        entry["payment"] = _payment_summary(payment)

        # The amount is a CHECK. A number attached to a payment of a different
        # value is exactly the mistake this importer exists to prevent.
        if amount is not None and Decimal(str(payment.amount or 0)) != amount:
            entry["status"] = STATUS_MISMATCH
            entry["message"] = (
                f"The file says {amount} but this payment is "
                f"{payment.amount}. Not applied — check you have the right row.")
            results.append(entry)
            continue

        if payment.etims_invoice_number:
            if payment.etims_invoice_number == number:
                entry["status"] = STATUS_ALREADY
                entry["message"] = "Already recorded with this number — nothing to do."
            else:
                entry["status"] = STATUS_MISMATCH
                entry["message"] = (
                    f"This payment already carries {payment.etims_invoice_number}. "
                    f"Applying {number} would replace it — resolve by hand.")
            results.append(entry)
            continue

        entry["status"] = STATUS_MATCHED
        results.append(entry)

    counts: dict[str, int] = {}
    for entry in results:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    return {
        "rows": results,
        "summary": {
            "total": len(results),
            "matched": counts.get(STATUS_MATCHED, 0),
            "ambiguous": counts.get(STATUS_AMBIGUOUS, 0),
            "unmatched": counts.get(STATUS_UNMATCHED, 0),
            "mismatch": counts.get(STATUS_MISMATCH, 0),
            "already_recorded": counts.get(STATUS_ALREADY, 0),
            "invalid": counts.get(STATUS_INVALID, 0),
        },
    }


def commit(landlord_id: int, rows: list[dict], mapping: dict,
           options: dict | None = None, *, resolutions: dict | None = None,
           allowed_property_ids=None, actor_user_id: int | None = None) -> dict:
    """
    Apply the unambiguous matches, plus any ambiguity a human resolved.

    `resolutions` is {line_number: payment_id} — the reviewer's explicit choice
    for rows the matcher refused to decide. Nothing else about an ambiguous row
    is guessed at.

    `allowed_property_ids` is the set of properties the caller may record tax
    data against, passed IN rather than resolved here. etims_service's own
    assert_can_manage() reads the caller out of the JWT, which would tie this
    service to a live request — untestable, and wrong for anything running off
    a queue later. The route computes the set; this function just honours it.
    None means unrestricted.

    Re-validates rather than trusting the browser: the preview may be minutes
    old, and a number recorded in the meantime must not be silently overwritten.
    """
    from extensions import db
    from models import Payment
    from services import etims_service
    from services.audit_service import record_audit
    from utils import ApiError

    resolutions = {int(k): int(v) for k, v in (resolutions or {}).items()}
    checked = validate(landlord_id, rows, mapping, options)

    applied, failed = [], []

    for entry in checked["rows"]:
        line = entry["_line"]
        payment_id = None

        if entry["status"] == STATUS_MATCHED:
            payment_id = entry["payment"]["payment_id"]
        elif line in resolutions:
            # A human chose. Honour it — but only among the candidates we
            # actually offered, so a stale or hand-edited payload cannot point
            # a control number at an unrelated payment.
            offered = {c["payment_id"] for c in entry.get("candidates", [])}
            if entry.get("payment"):
                offered.add(entry["payment"]["payment_id"])
            if resolutions[line] not in offered:
                failed.append({"_line": line,
                               "message": "That payment was not one of the options for this row."})
                continue
            payment_id = resolutions[line]
        else:
            continue

        payment = db.session.get(Payment, payment_id)
        if payment is None or payment.landlord_id != landlord_id:
            failed.append({"_line": line, "message": "Payment not found on this account."})
            continue

        if allowed_property_ids is not None and payment.property_id not in allowed_property_ids:
            failed.append({"_line": line,
                           "message": "You don't have tax-compliance access to that property."})
            continue

        try:
            etims_service.record_number(
                payment, "payment",
                invoice_number=entry["etims_invoice_number"],
                issued_at=None,
                qr_url=None,
                actor_user_id=actor_user_id,
            )
            applied.append({"_line": line,
                            "payment_id": payment.id,
                            "payment_ref": payment.payment_ref,
                            "etims_invoice_number": entry["etims_invoice_number"]})
        except ApiError as exc:
            # A duplicate number, or a property this person may not touch.
            failed.append({"_line": line, "message": getattr(exc, "message", str(exc))})

    db.session.commit()

    record_audit(
        actor_user_id=actor_user_id,
        landlord_id=landlord_id,
        action="etims_bulk_import",
        entity_type="payment",
        entity_id=None,
        description=(f"eTIMS control numbers imported: {len(applied)} applied, "
                     f"{len(failed)} refused, "
                     f"{checked['summary']['ambiguous']} left ambiguous."),
        after_data={"applied": applied, "failed": failed},
    )
    db.session.commit()

    return {"applied": applied, "failed": failed,
            "rows": checked["rows"], "summary": checked["summary"]}
