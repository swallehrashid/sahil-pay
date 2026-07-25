"""
services/copilot_service.py — Co-Pilot SMS-forwarder pipeline
================================================================
See COPILOT_PLATFORM_SPEC.md §3. Two responsibilities:

  1. The parser template engine — admin-managed placeholder patterns
     ({amount}/{ref}/{name}/{account}/{phone}/{date}/{time}/{*}) compiled to
     regex, so onboarding a new bank/sender never touches this file.
  2. process_copilot_message() — the ingest pipeline a forwarded SMS runs
     through: idempotency → gate → parse → ref-dedupe → tenant match →
     MpesaTransaction/Payment creation (through allocation_service, the ONLY
     ledger writer) → notify → audit.

Every function here FLUSHES but never commits — the route/caller owns the
transaction, exactly like services/allocation_service.py and
services/audit_service.py.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from extensions import db
from services.audit_service import record_audit
from services.notification_service import notify

logger = logging.getLogger(__name__)


# ===========================================================================
# Placeholder → regex compiler
# ===========================================================================

# Groups the admin can drop into a template. "date"/"time"/"*" are discarded
# (non-capturing) — their value is never used, they just let the admin mark
# where variable, uninteresting text sits so the surrounding literal text
# can still line up exactly with the real SMS.
_PLACEHOLDER_GROUPS = {
    "amount":  r"(?P<amount>[\d,]+(?:\.\d{1,2})?)",
    "ref":     r"(?P<ref>[A-Z0-9]{6,20})",
    "name":    r"(?P<name>.+?)",
    "account": r"(?P<account>[A-Za-z0-9\-/#.]{1,50})",
    "phone":   r"(?P<phone>(?:\+?254|0)[17]\d{8})",
    "date":    r"(?:.*?)",
    "time":    r"(?:.*?)",
    "*":       r"(?:.*?)",
}

# Placeholders whose match is open-ended/lazy free text. Two of these placed
# directly adjacent (no literal separator) are genuinely ambiguous — regex
# backtracking will starve the first one down to almost nothing. Placeholders
# with a hard character-class boundary (amount/ref/account/phone) terminate
# themselves and are safe next to anything.
_LOOSE_PLACEHOLDERS = {"name", "date", "time", "*"}

PLACEHOLDERS = list(_PLACEHOLDER_GROUPS.keys())

_TOKEN_RE = re.compile(r"\{([A-Za-z*]+)\}")

# In-process cache of compiled patterns, keyed by (template_id, updated_at) so
# an edit invalidates the old entry without needing a signal/pubsub.
_COMPILED_CACHE: dict[tuple[int, str], re.Pattern] = {}

# Regex search runs off-thread with a hard timeout — belt-and-braces even
# though the compiler's structure (below) makes catastrophic backtracking
# structurally implausible. Best-effort: a timed-out worker thread keeps
# running in the background (Python can't kill it), it just stops blocking
# the caller.
_REGEX_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="copilot-regex")
_REGEX_TIMEOUT_SECONDS = 0.1


# Interchangeable connector words. Kenyan bank/M-Pesa SMS say the same thing
# many ways for the SAME transaction; a template author shouldn't have to
# author one template per bank's phrasing. Each key (lowercased literal word an
# admin types in the template) expands to a regex alternation that also matches
# its synonyms, so "received" in a template still matches an SMS that says
# "credited", and "Ref" still matches "Reference"/"Ref."/"Ref:". This is the
# core of "if a template exists for that sender, it should parse" — the literal
# glue between placeholders becomes tolerant instead of exact.
_CONNECTOR_SYNONYMS = {
    "received":  r"(?:received|credited|deposited|paid)",
    "credited":  r"(?:credited|received|deposited|paid)",
    "deposited": r"(?:deposited|credited|received|paid)",
    "ref":       r"(?:ref|reference|txn|transaction)",
    "reference": r"(?:reference|ref|txn|transaction)",
    "account":   r"(?:account|acc|a/c|acct)",
    "from":      r"from",
    "to":        r"to",
    "for":       r"for",
    "ksh":       r"(?:ksh|kes|kshs)",
    "kes":       r"(?:kes|ksh|kshs)",
}

# Trailing punctuation on a connector word varies ("Ref", "Ref:", "Ref."). We
# strip it off the literal, match the word tolerantly, then allow optional
# punctuation after. Leading/standalone punctuation runs (":", ",", "-") in a
# template are made optional too, so a missing colon in the real SMS doesn't
# break the whole match.
_TRAILING_PUNCT_RE = re.compile(r"([:.,;#\-]+)$")


def _escape_literal(text: str) -> str:
    """Turn an admin's literal template text into a TOLERANT regex.

    - Whitespace runs collapse to \\s+ (banks vary spacing/line-breaks).
    - Recognised connector words (received/credited, Ref/Reference, account/acc,
      Ksh/KES, …) match any of their synonyms — so one template covers a bank's
      many phrasings instead of failing on a single word swap.
    - Trailing punctuation on any word (Ref: / Ref. / Ref) is made optional.
    - Standalone punctuation tokens (":", ",", "-") are made optional so a
      missing separator in the real SMS doesn't sink the match.

    The placeholder anchors ({amount}, {ref}, {account}, {phone}) are untouched
    and still terminate themselves, so tolerant glue can never make the pattern
    ambiguous or greedy across them."""
    parts = re.split(r"(\s+)", text)
    out = []
    for part in parts:
        if not part:
            continue
        if part.isspace():
            out.append(r"\s+")
            continue

        # A run that's purely punctuation ("," ":" "-" "#") — make it optional.
        if re.fullmatch(r"[:.,;#\-]+", part):
            out.append("(?:" + re.escape(part) + r")?")
            continue

        # Peel trailing punctuation off the word so "Ref:" -> word "Ref" + ":".
        trailing = ""
        m = _TRAILING_PUNCT_RE.search(part)
        if m:
            trailing = m.group(1)
            core = part[: m.start()]
        else:
            core = part

        low = core.lower()
        if low in _CONNECTOR_SYNONYMS:
            out.append(_CONNECTOR_SYNONYMS[low])
            # A connector word in the real SMS often carries trailing punctuation
            # the template author didn't type ("Ref" -> "Ref.", "account" ->
            # "account:"). Allow an optional punctuation run right after any
            # recognised connector so that never breaks the match.
            out.append(r"[:.,;]?")
        else:
            out.append(re.escape(core))

        if trailing:
            out.append("(?:" + re.escape(trailing) + r")?")
    return "".join(out)


def compile_template(template_text: str) -> re.Pattern:
    """
    Compile an admin-authored placeholder template into a regex.
    Raises ValueError with a human-readable message on any validation failure
    — callers (the admin template CRUD routes) turn that straight into a 400.
    """
    if not template_text or not template_text.strip():
        raise ValueError("Template text cannot be empty.")
    if "{amount}" not in template_text:
        raise ValueError("Template must include an {amount} placeholder.")

    tokens: list[tuple[str, str]] = []
    pos = 0
    for m in _TOKEN_RE.finditer(template_text):
        if m.start() > pos:
            tokens.append(("literal", template_text[pos:m.start()]))
        name = m.group(1)
        if name not in _PLACEHOLDER_GROUPS:
            raise ValueError(
                f"Unknown placeholder '{{{name}}}'. Valid placeholders: "
                + ", ".join(f"{{{k}}}" for k in PLACEHOLDERS)
            )
        tokens.append(("placeholder", name))
        pos = m.end()
    if pos < len(template_text):
        tokens.append(("literal", template_text[pos:]))

    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        if a[0] == "placeholder" and b[0] == "placeholder" \
                and a[1] in _LOOSE_PLACEHOLDERS and b[1] in _LOOSE_PLACEHOLDERS:
            raise ValueError(
                f"{{{a[1]}}} and {{{b[1]}}} are both free-text placeholders with no "
                "literal text between them — add a word or punctuation mark to "
                "separate them so the pattern isn't ambiguous."
            )

    parts = []
    for kind, value in tokens:
        if kind == "literal":
            if value:
                parts.append(_escape_literal(value))
        else:
            parts.append(_PLACEHOLDER_GROUPS[value])

    pattern_str = "".join(parts)
    try:
        return re.compile(pattern_str, re.IGNORECASE | re.DOTALL)
    except re.error as exc:
        raise ValueError(f"Could not compile this template: {exc}") from exc


def _get_compiled(template) -> re.Pattern | None:
    key = (template.id, str(template.updated_at or template.created_at))
    cached = _COMPILED_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        pattern = compile_template(template.template_text)
    except ValueError:
        logger.error("copilot_service: stored template #%s no longer compiles.", template.id)
        return None
    for k in list(_COMPILED_CACHE):
        if k[0] == template.id and k != key:
            del _COMPILED_CACHE[k]
    _COMPILED_CACHE[key] = pattern
    return pattern


def _safe_search(pattern: re.Pattern, text: str) -> re.Match | None:
    future = _REGEX_EXECUTOR.submit(pattern.search, text)
    try:
        return future.result(timeout=_REGEX_TIMEOUT_SECONDS)
    except _FutureTimeoutError:
        logger.error("copilot_service: regex search exceeded the %.0fms safety guard.",
                     _REGEX_TIMEOUT_SECONDS * 1000)
        return None


def _clean_amount(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    p = raw.strip().replace(" ", "").replace("-", "")
    if p.startswith("+"):
        p = p[1:]
    if p.startswith("0") and len(p) == 10:
        p = "254" + p[1:]
    return p


def _clean_account(raw: str | None) -> str | None:
    """Trim an account number and shave trailing sentence punctuation the
    tolerant literal matcher may have let the greedy account group swallow
    (e.g. "ACME-T001." -> "ACME-T001"), so tenant matching by account number
    compares clean value to clean value."""
    if not raw:
        return None
    return raw.strip().rstrip(".,;:") or None


_POST_PROCESS = {
    "amount":  _clean_amount,
    "ref":     lambda s: s.strip().upper().rstrip(".,;:") if s else None,
    "name":    lambda s: s.strip() if s else None,
    "account": _clean_account,
    "phone":   _normalize_phone,
}


def parse_sms(sender_id: str, raw_text: str):
    """
    Try every active template for `sender_id` (case-insensitive), lowest
    `priority` first. Returns (template, fields_dict) on the first match,
    or (None, None) if nothing matches — the caller routes that to the
    admin's unparsed queue.
    """
    from models import SmsParserTemplate

    sender_id = (sender_id or "").strip()
    if not sender_id:
        return None, None

    templates = (
        SmsParserTemplate.query
        .filter(db.func.upper(SmsParserTemplate.sender_id) == sender_id.upper())
        .filter_by(is_active=True)
        .order_by(SmsParserTemplate.priority.asc(), SmsParserTemplate.id.asc())
        .all()
    )
    for template in templates:
        pattern = _get_compiled(template)
        if pattern is None:
            continue
        match = _safe_search(pattern, raw_text or "")
        if not match:
            continue
        groups = match.groupdict()
        fields = {key: proc(groups.get(key)) for key, proc in _POST_PROCESS.items()}
        return template, fields

    return None, None


def test_template(template_text: str, sample_text: str) -> dict:
    """Powers the admin template editor's live test console + the
    auto-run-on-save check. Never raises — errors come back in the dict."""
    try:
        pattern = compile_template(template_text)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    match = _safe_search(pattern, sample_text or "")
    if not match:
        return {"ok": False, "error": "This template does not match the sample message."}

    groups = match.groupdict()
    fields = {}
    for key, proc in _POST_PROCESS.items():
        try:
            value = proc(groups.get(key))
        except Exception:
            value = None
        fields[key] = str(value) if isinstance(value, Decimal) else value
    return {"ok": True, "fields": fields}


# ===========================================================================
# Device tokens
# ===========================================================================

def generate_device_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). Only the hash is ever persisted —
    the raw value is returned to the caller exactly once, at pairing."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_device_token(raw)


def hash_device_token(raw_token: str) -> str:
    return hashlib.sha256((raw_token or "").encode()).hexdigest()


# ===========================================================================
# Ingest pipeline
# ===========================================================================

def _dedupe_hash(landlord_id: int, sender_id: str, raw_text: str) -> str:
    basis = f"{landlord_id}|{sender_id.strip().upper()}|{raw_text.strip().lower()}"
    return hashlib.sha256(basis.encode()).hexdigest()


def _redact_unmatched(raw: str | None) -> str:
    """No template claimed this message. Retain only a redacted shape stub —
    enough for an admin to recognise a message family worth writing a template
    for, never enough to expose the landlord's private SMS content."""
    if not raw:
        return "[redacted: no matching template]"
    head = raw.strip()[:40]
    head = re.sub(r"\d", "#", head)
    return f"[redacted: no matching template] {head}..."


def _copilot_payment_ref(landlord_id: int) -> str:
    from models import Payment
    count = Payment.query.filter_by(landlord_id=landlord_id).count()
    return f"PAY-{landlord_id}-{count + 1:06d}"


def process_copilot_message(device, *, client_uuid: str, sender_id: str,
                             raw_text: str, received_at: datetime | None = None):
    """
    Entry point for a freshly-forwarded SMS (COPILOT_PLATFORM_SPEC.md §3.3
    steps 1-2, then delegates parsing/matching/creation to _finalize_message).
    Returns the CopilotMessage row (flushed). Caller commits — and per the
    spec's error-containment rule, should wrap each call in its own
    try/except + rollback when processing a batch, so one bad SMS can't sink
    the rest.
    """
    from models import Landlord, CopilotMessage, CopilotParseStatus, CopilotMatchStatus

    landlord_id = device.landlord_id
    sender_id = (sender_id or "").strip().upper()[:30]
    raw_text = (raw_text or "").strip()[:1000]
    client_uuid = (client_uuid or "").strip()[:40]

    if not client_uuid or not sender_id or not raw_text:
        raise ValueError("client_uuid, sender_id and text are all required.")

    # Step 1a — per-device idempotency key. A retried/queued-then-flushed
    # message with the same client_uuid is a no-op, not a new row.
    existing = CopilotMessage.query.filter_by(device_id=device.id, client_uuid=client_uuid).first()
    if existing is not None:
        return existing

    dedupe_hash = _dedupe_hash(landlord_id, sender_id, raw_text)

    # NOTE: we deliberately do NOT flag a message as a "duplicate" on matching
    # message TEXT. Two genuinely different payments can share an amount, a payer
    # name, even the full wording — only the REFERENCE NUMBER is unique per
    # transaction. A true retry of the exact same SMS is already caught by the
    # client_uuid idempotency check above. The real duplicate test — parsed
    # reference number matching an already-confirmed transaction — happens after
    # parsing in _finalize_message (Step 4). dedupe_hash is still stored for
    # diagnostics, but never on its own marks a message duplicate.

    landlord = db.session.get(Landlord, landlord_id)
    ls = landlord.landlord_settings if landlord else None

    # Step 2 — gate. Nothing is lost: the app keeps this in its own local
    # log even when the server rejects it, and the landlord can see it once
    # they re-enable Co-pilot (the row is already here, just 'rejected').
    if not landlord or not ls or not ls.copilot_enabled or ls.copilot_admin_locked:
        msg = CopilotMessage(
            landlord_id=landlord_id, device_id=device.id, client_uuid=client_uuid,
            sender_id=sender_id, raw_text=raw_text, sms_received_at=received_at,
            dedupe_hash=dedupe_hash,
            parse_status=CopilotParseStatus.rejected.value,
            match_status=CopilotMatchStatus.n_a.value,
            error_reason="Co-pilot is disabled for this account.",
        )
        db.session.add(msg)
        db.session.flush()
        return msg

    msg = CopilotMessage(
        landlord_id=landlord_id, device_id=device.id, client_uuid=client_uuid,
        sender_id=sender_id, raw_text=raw_text, sms_received_at=received_at,
        dedupe_hash=dedupe_hash,
        parse_status=CopilotParseStatus.unparsed.value,   # _finalize_message sets the real outcome
        match_status=CopilotMatchStatus.n_a.value,
    )
    db.session.add(msg)
    db.session.flush()

    _finalize_message(msg, landlord, ls, device)

    device.last_seen_at = datetime.utcnow()
    db.session.flush()
    return msg


def retry_unparsed_message(message):
    """
    Re-run the parse → match → create pipeline on an already-stored message
    (used after the admin adds/fixes a parser template). Refuses if Co-pilot
    is currently disabled for the landlord — the message stays as it was.
    """
    from models import Landlord

    landlord = db.session.get(Landlord, message.landlord_id)
    ls = landlord.landlord_settings if landlord else None
    if not landlord or not ls or not ls.copilot_enabled or ls.copilot_admin_locked:
        message.error_reason = "Co-pilot is currently disabled for this landlord — enable it before retrying."
        db.session.flush()
        return message

    _finalize_message(message, landlord, ls, message.device)
    db.session.flush()
    return message


def _finalize_message(msg, landlord, ls, device) -> None:
    """
    Steps 3-9 of COPILOT_PLATFORM_SPEC.md §3.3 — parse, ref-dedupe, tenant
    match, MpesaTransaction + (through allocation_service) Payment creation,
    notify, audit. Mutates `msg` in place; flushes but does not commit.
    """
    from models import (
        Tenant, Payment, PaymentStatus, PaymentSource,
        MpesaTransaction, MpesaTransactionStatus,
        CopilotParseStatus, CopilotMatchStatus,
    )

    device_label = device.device_name if device else "retry"

    # Step 3 — parse.
    template, fields = parse_sms(msg.sender_id, msg.raw_text)
    if not template:
        msg.parse_status = CopilotParseStatus.unparsed.value
        msg.match_status = CopilotMatchStatus.n_a.value
        msg.template_id = None
        msg.error_reason = None
        # §2 — no active template claimed this message, so it is not a payment
        # notification: it is the landlord's private SMS traffic (airtime,
        # personal transfers, utility bills, ...) picked up because
        # SENDER_PRESETS is deliberately broad-carrier. Do not retain the body
        # unless this landlord has opted in (admin-authoring exemption).
        if not getattr(ls, "copilot_retain_unmatched", False):
            msg.raw_text = _redact_unmatched(msg.raw_text)
        db.session.flush()
        return

    amount = fields.get("amount")
    if amount is None or amount <= 0:
        msg.parse_status = CopilotParseStatus.rejected.value
        msg.match_status = CopilotMatchStatus.n_a.value
        msg.template_id = template.id
        msg.error_reason = "Parsed amount was missing or not a positive number."
        db.session.flush()
        return

    parsed_ref     = fields.get("ref")
    parsed_name    = fields.get("name")
    parsed_account = fields.get("account")
    parsed_phone   = fields.get("phone")

    # Step 4 — the REAL duplicate test: this reference number already belongs to
    # a CONFIRMED transaction (one that was recorded/applied, or is linked to a
    # confirmed Payment). The reference number is the only truly unique field per
    # transaction, so it — and only it — decides a duplicate. A ref that appears
    # only on an unmatched/pending row that never became a real payment does NOT
    # block this one (it may be the same money finally being allocated).
    if parsed_ref:
        dupe_q = MpesaTransaction.query.filter_by(
            landlord_id=landlord.id, reference_number=parsed_ref
        )
        if msg.mpesa_transaction_id:
            dupe_q = dupe_q.filter(MpesaTransaction.id != msg.mpesa_transaction_id)

        confirmed_dupe = None
        for txn in dupe_q.all():
            is_recorded = txn.status == MpesaTransactionStatus.recorded.value
            payment_confirmed = (
                txn.payment_id is not None
                and txn.payment is not None
                and txn.payment.status == PaymentStatus.confirmed.value
            )
            if is_recorded or payment_confirmed:
                confirmed_dupe = txn
                break

        if confirmed_dupe is not None:
            msg.parse_status = CopilotParseStatus.duplicate.value
            msg.match_status = CopilotMatchStatus.n_a.value
            msg.template_id = template.id
            msg.parsed_ref, msg.parsed_amount = parsed_ref, amount
            msg.parsed_name, msg.parsed_account, msg.parsed_phone = parsed_name, parsed_account, parsed_phone
            msg.error_reason = "A confirmed transaction with this reference has already been recorded."
            db.session.flush()
            return

    # Step 5 — match tenant: account number first, then phone. Never fuzzy.
    tenant = None
    if parsed_account:
        tenant = Tenant.query.filter_by(
            landlord_id=landlord.id, account_number=parsed_account, is_deleted=False
        ).first()
    if tenant is None and parsed_phone:
        # Tenant.phone is stored inconsistently across the app (some rows keep
        # a leading '+', some don't — see mpesa_routes.py's own phone
        # normalisation) so match against every plausible form rather than
        # assuming one.
        phone_candidates = {parsed_phone, "+" + parsed_phone}
        if parsed_phone.startswith("254") and len(parsed_phone) == 12:
            phone_candidates.add("0" + parsed_phone[3:])
        tenant = Tenant.query.filter_by(
            landlord_id=landlord.id, is_deleted=False
        ).filter(Tenant.phone.in_(phone_candidates)).first()

    tenant_name = f"{tenant.first_name} {tenant.last_name}" if tenant else None

    msg.parse_status   = CopilotParseStatus.parsed.value
    msg.match_status   = CopilotMatchStatus.matched.value if tenant else CopilotMatchStatus.unmatched.value
    msg.template_id    = template.id
    msg.parsed_ref     = parsed_ref
    msg.parsed_amount  = amount
    msg.parsed_name    = parsed_name
    msg.parsed_account = parsed_account
    msg.parsed_phone   = parsed_phone
    msg.error_reason   = None
    db.session.flush()

    # Step 6 — MpesaTransaction record, matched or not (it's the shared
    # transaction-status table every other M-Pesa flow already uses).
    mpesa_txn = MpesaTransaction(
        landlord_id=landlord.id,
        reference_number=parsed_ref or f"COP-{msg.id}",
        status=(MpesaTransactionStatus.recorded.value if tenant else MpesaTransactionStatus.unmatched.value),
        amount=amount,
        tenant_id=tenant.id if tenant else None,
        description=f"Co-pilot | {msg.sender_id} | {parsed_name or ''} | {msg.raw_text[:120]}",
    )
    db.session.add(mpesa_txn)
    db.session.flush()
    msg.mpesa_transaction_id = mpesa_txn.id

    if tenant is None:
        # Step 8 — unmatched: notify, audit, stop. No Payment yet.
        if landlord.user_id:
            notify(
                recipient_user_id=landlord.user_id,
                category="copilot_payment_unmatched",
                template_key="copilot_payment_unmatched",
                template_kwargs={"amount": f"{amount:,.2f}", "sender_id": msg.sender_id},
                landlord_id=landlord.id,
                # Deep-link into the Co-pilot inbox and auto-open THIS message so
                # the landlord can review it and pick a tenant to allocate to —
                # even though it stayed unmatched (no payment yet). Clicking the
                # notification opens the same review flow as clicking the message.
                link=f"/landlord/payments?tab=copilot&message={msg.id}",
                entity_type="copilot", entity_id=msg.id,
            )
        record_audit(
            actor_user_id=None, landlord_id=landlord.id, action="copilot_ingest",
            entity_type="copilot", entity_id=msg.id,
            description=f"Co-pilot [{device_label}] {msg.sender_id}: KES {amount} — unmatched.",
        )
        db.session.flush()
        return

    # Step 7 — matched: create the Payment. copilot_auto_allocate decides
    # confirmed+allocated (through allocation_service — never a direct
    # balance write) vs pending (touches nothing until the landlord confirms).
    payment = Payment(
        payment_ref     = _copilot_payment_ref(landlord.id),
        landlord_id     = landlord.id,
        tenant_id       = tenant.id,
        unit_id         = tenant.unit_id,
        property_id     = tenant.unit.property_id if tenant.unit else None,
        amount          = amount,
        payment_date    = msg.sms_received_at.date() if msg.sms_received_at else date.today(),
        status          = PaymentStatus.confirmed.value if ls.copilot_auto_allocate else PaymentStatus.pending.value,
        source          = PaymentSource.co_pilot.value,
        mpesa_reference = parsed_ref,
        notes           = f"Co-pilot via {msg.sender_id}. Payer: {parsed_name or 'unknown'}.",
    )
    db.session.add(payment)
    db.session.flush()

    mpesa_txn.payment_id = payment.id
    msg.payment_id = payment.id
    msg.tenant_id  = tenant.id

    if ls.copilot_auto_allocate:
        from services.allocation_service import auto_allocate, apply_allocations
        alloc_rows = auto_allocate(tenant, amount, landlord, ref_date=payment.payment_date)
        apply_allocations(payment, tenant, alloc_rows, landlord.id)

        from services.alert_service import dispatch_alert
        from services.automation_service import on_payment_recorded
        dispatch_alert(
            landlord.id, "payment", title="Payment received",
            body=f"{tenant_name} paid KES {amount} via Co-pilot ({payment.payment_ref}).",
            link="/landlord/payments", entity_type="payment", entity_id=payment.id,
        )
        on_payment_recorded(landlord, payment, tenant)
    elif landlord.user_id:
        notify(
            recipient_user_id=landlord.user_id,
            category="copilot_payment_pending",
            template_key="copilot_payment_pending",
            template_kwargs={
                "amount": f"{amount:,.2f}",
                "sender_name": parsed_name or msg.sender_id,
                "tenant_name": tenant_name,
            },
            landlord_id=landlord.id,
            # Deep-link straight into the review-and-allocate modal for this
            # payment (PaymentsPage reads ?review=<id>), so clicking the
            # notification opens the same flow as clicking the parsed message.
            link=f"/landlord/payments?review={payment.id}",
            entity_type="payment", entity_id=payment.id,
        )

    record_audit(
        actor_user_id=None, landlord_id=landlord.id, action="copilot_ingest",
        entity_type="copilot", entity_id=msg.id,
        description=(
            f"Co-pilot [{device_label}] {msg.sender_id}: KES {amount} — "
            f"matched to {tenant_name} ({payment.payment_ref})."
        ),
    )
    db.session.flush()
