"""
services/lease_service.py — tenancy agreements.

TWO ROUTES, ONE DESTINATION
---------------------------
A lease is signed either in the tenant's portal or on paper at the kitchen
table. Both end as a PDF attached to the tenancy that landlord and tenant can
each download. Everything below exists to make those two routes converge.

    PORTAL    draft → sent → submitted → approved
                              ↘ rejected → submitted   (corrected, resubmitted)
    PAPER     uploaded

THE STATE MACHINE IS ENFORCED, NOT SUGGESTED
--------------------------------------------
`transition()` is the only way a lease changes status, and it refuses moves
that are not on the map. Without that, "approve" on a stale browser tab could
approve a lease the tenant had already been asked to redo, and the audit trail
would record an approval of a document nobody signed.

THE SIGNATURE IS EVIDENCE
-------------------------
Typed name + timestamp + IP + user agent, captured once at submission and never
written again. A drawn squiggle on a phone screen proves far less than a
recorded consent event with provenance, and it cannot be typed by the landlord
on the tenant's behalf afterwards — which is the failure mode that matters.

WHAT IS DELIBERATELY NOT DONE
-----------------------------
No e-signature certificate authority, no witness workflow. Kenyan tenancy
agreements are ordinarily signed on paper or by simple consent; adding a PKI
ceremony would be theatre that stops landlords using it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from html import escape

from extensions import db
from models import (
    DOWNLOADABLE_LEASE_STATUSES, DocumentTemplate, LeaseAgreement, LeaseSource,
    LeaseStatus, Tenant,
)
from utils import ApiError

logger = logging.getLogger(__name__)

# The only moves allowed. Anything absent here is refused, whatever the caller
# believes the current state to be.
# `superseded` is reachable from every un-signed state: issuing a newer
# agreement retires the old one wherever it had got to. It is never reachable
# from `submitted` or `approved` — a signature, once given, is not swept aside
# by someone pressing Prepare again.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    LeaseStatus.draft.value:     {LeaseStatus.sent.value, LeaseStatus.superseded.value},
    LeaseStatus.sent.value:      {LeaseStatus.submitted.value, LeaseStatus.draft.value,
                                  LeaseStatus.superseded.value},
    LeaseStatus.submitted.value: {LeaseStatus.approved.value, LeaseStatus.rejected.value},
    # A rejected lease goes back to the tenant, who resubmits it.
    LeaseStatus.rejected.value:  {LeaseStatus.submitted.value, LeaseStatus.superseded.value},
    # Terminal. An approved lease is re-issued by creating a new agreement, so
    # the signed one is never quietly rewritten.
    LeaseStatus.approved.value:   set(),
    LeaseStatus.uploaded.value:   set(),
    LeaseStatus.superseded.value: set(),
}

# Placeholders a template may use. Anything else is left alone rather than
# blanked, so a stray brace in legal prose does not eat the sentence after it.
TEMPLATE_FIELDS = (
    "tenant_name", "tenant_phone", "tenant_email", "tenant_id_number",
    "unit_name", "property_name", "property_address",
    "landlord_name", "rent_amount", "deposit_amount",
    "lease_start_date", "lease_end_date", "today",
)

_PLACEHOLDER = re.compile(r"\{(" + "|".join(TEMPLATE_FIELDS) + r")\}")


def transition(lease: LeaseAgreement, new_status: str, *, actor_user_id=None) -> None:
    """
    Move a lease to *new_status*, or refuse.

    Refusing loudly is the point: a stale tab pressing Approve on a lease that
    has since been sent back would otherwise record an approval of a document
    nobody signed.
    """
    allowed = ALLOWED_TRANSITIONS.get(lease.status, set())
    if new_status not in allowed:
        raise ApiError(
            f"A lease that is '{lease.status}' cannot become '{new_status}'.",
            status=409, code="invalid_lease_transition",
        )
    lease.status = new_status


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def field_context(tenant: Tenant) -> dict:
    """The values a template may interpolate, drawn from the tenancy itself."""
    unit = tenant.unit
    prop = unit.property if unit else None
    landlord = tenant.landlord

    def _money(value):
        return f"{float(value or 0):,.2f}"

    return {
        "tenant_name":      f"{tenant.first_name} {tenant.last_name}".strip(),
        "tenant_phone":     tenant.phone or "",
        "tenant_email":     tenant.email or "",
        "tenant_id_number": tenant.national_id or "",
        "unit_name":        unit.name if unit else "",
        "property_name":    prop.name if prop else "",
        "property_address": ", ".join(filter(None, [
            getattr(prop, "street_name", None), getattr(prop, "city", None),
        ])) if prop else "",
        "landlord_name":    getattr(landlord, "company_name", "") or "",
        "rent_amount":      _money(unit.rent_amount if unit else 0),
        "deposit_amount":   _money(tenant.deposit_amount),
        "lease_start_date": str(tenant.lease_start_date or ""),
        "lease_end_date":   str(tenant.lease_expiry_date or ""),
        "today":            datetime.utcnow().date().isoformat(),
    }


def render_body(template_html: str | None, context: dict) -> str:
    """
    Substitute {placeholders} in a template.

    Values are HTML-escaped: a tenant's name is user input, and this string is
    rendered into a PDF and shown back in the portal.
    """
    if not template_html:
        return ""
    return _PLACEHOLDER.sub(
        lambda match: escape(str(context.get(match.group(1), "") or "")),
        template_html,
    )


def default_template_html() -> str:
    """
    A lawful, plain-language fallback for a landlord who has not written their
    own. Deliberately complete enough to use as-is: an empty template would
    make the feature useless to exactly the people who most need it.
    """
    return """
<h1>TENANCY AGREEMENT</h1>
<p>This agreement is made on {today} between <strong>{landlord_name}</strong>
("the Landlord") and <strong>{tenant_name}</strong> ("the Tenant").</p>

<h2>1. The premises</h2>
<p>The Landlord lets to the Tenant the residential premises known as
<strong>{unit_name}</strong> at <strong>{property_name}</strong>,
{property_address} ("the Premises").</p>

<h2>2. Term</h2>
<p>The tenancy begins on {lease_start_date} and continues until
{lease_end_date}, unless ended earlier in accordance with this agreement or
with Kenyan law.</p>

<h2>3. Rent</h2>
<p>The Tenant shall pay rent of <strong>KES {rent_amount}</strong> per month,
in advance, on or before the fifth day of each month, by the payment method
notified by the Landlord.</p>

<h2>4. Deposit</h2>
<p>The Tenant has paid a deposit of <strong>KES {deposit_amount}</strong>. The
deposit is held by the Landlord and is refundable at the end of the tenancy,
less any sums properly due for unpaid rent, unpaid utilities, or damage beyond
fair wear and tear. The deposit is not rent and may not be used by the Tenant
as the final month's rent.</p>

<h2>5. Utilities</h2>
<p>The Tenant is responsible for water, electricity and any other metered
charges for the Premises, billed as read.</p>

<h2>6. Use of the premises</h2>
<p>The Tenant shall use the Premises as a private residence, keep them in good
condition, and not sublet or assign without the Landlord's written consent.</p>

<h2>7. Repairs</h2>
<p>The Landlord shall keep the structure, roof, plumbing and electrical
installations in repair. The Tenant shall report faults promptly and shall meet
the cost of damage they or their visitors cause.</p>

<h2>8. Access</h2>
<p>The Landlord may enter the Premises at reasonable times, having given the
Tenant at least twenty-four hours' notice, except in an emergency.</p>

<h2>9. Ending the tenancy</h2>
<p>Either party may end this tenancy by giving one month's written notice. The
Tenant shall return the Premises and any keys in the condition received, fair
wear and tear excepted.</p>

<h2>10. Tenant's details</h2>
<p>Telephone: {tenant_phone}<br>Email: {tenant_email}<br>
Identification number: {tenant_id_number}</p>

<p><em>This agreement is governed by the laws of Kenya.</em></p>
""".strip()


def render_pdf_bytes(lease: LeaseAgreement) -> bytes:
    """
    The finished agreement as a PDF, signature block included.

    Rendered from `body_html` — the snapshot taken when the lease was sent — so
    a later edit to the landlord's template can never change the wording of an
    agreement somebody has already signed.
    """
    from utils import render_pdf

    # A lease is the document produced in a dispute, and an unbranded one looks
    # like a draft somebody typed. It carries the SAME letterhead as every
    # report — the landlord's logo, company name and address, falling back to a
    # muted Sahil Pay mark when they have not uploaded one — by calling the
    # report builder's own helper rather than growing a second copy that drifts.
    from services.report_builder import _letterhead_html, build_meta

    landlord = lease.landlord
    letterhead = _letterhead_html(build_meta(
        landlord,
        report_title="Tenancy Agreement",
        subject=f"{lease.tenant.first_name} {lease.tenant.last_name}".strip()
                if lease.tenant else None,
        property_name=lease.property.name if lease.property else None,
    ))

    signature = ""
    if lease.signed_name:
        signature = f"""
        <div class="signature">
          <h2>Signed by the Tenant</h2>
          <p class="name">{escape(lease.signed_name)}</p>
          <p class="meta">
            Accepted electronically on {escape(str(lease.signed_at or ""))} UTC.<br>
            Recorded from IP {escape(lease.signed_ip or "unknown")}.
          </p>
          <p class="meta">
            The Tenant confirmed they had read this agreement and agreed to be
            bound by it. This record, with its timestamp and origin, is the
            evidence of that consent.
          </p>
        </div>"""

    approval = ""
    if lease.status == LeaseStatus.approved.value and lease.reviewed_at:
        approval = (f'<div class="signature"><h2>Accepted by the Landlord</h2>'
                    f'<p class="meta">Approved on {escape(str(lease.reviewed_at))} UTC.</p></div>')

    style = """
      @page { size: A4; margin: 20mm; }
      body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
             font-size: 11pt; line-height: 1.6; color: #1a1a2e; }
      h1 { font-size: 16pt; text-align: center; letter-spacing: .06em; margin-bottom: 1.5em; }
      h2 { font-size: 12pt; margin-top: 1.4em; margin-bottom: .4em; }
      p { margin: .5em 0; }
      .signature { margin-top: 2.5em; padding-top: 1em; border-top: 1px solid #999;
                   page-break-inside: avoid; }
      .signature .name { font-size: 14pt; font-style: italic; margin: .3em 0; }
      .signature .meta { font-size: 9pt; color: #555; }
    """
    # The report stylesheet carries the .letterhead rules; the lease-specific
    # rules above are appended so both apply.
    from services.report_builder import _REPORT_STYLE

    html = (f"<!doctype html><html><head><meta charset='utf-8'>{_REPORT_STYLE}"
            f"<style>{style}</style></head><body>{letterhead}"
            f"{lease.body_html or ''}{signature}{approval}</body></html>")
    return render_pdf(html)


def store_pdf(lease: LeaseAgreement) -> str:
    """Render and store the agreement, returning its URL."""
    from io import BytesIO

    from services.storage_service import upload_to_s3

    pdf = render_pdf_bytes(lease)
    # profile="lease" keeps it off the image CDN — a lease is a private legal
    # document, not something to put on a public delivery network.
    return upload_to_s3(
        BytesIO(pdf), folder=f"leases/{lease.landlord_id}/{lease.tenant_id}",
        filename=f"lease-{lease.id}.pdf", content_type="application/pdf",
        profile="lease", force_local=True,
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def create_for_tenant(tenant: Tenant, *, template_id=None,
                      actor_user_id=None) -> LeaseAgreement:
    """Prepare an agreement for a tenancy, from a template or the default."""
    template = None
    if template_id:
        template = (
            db.session.query(DocumentTemplate)
            .filter_by(id=template_id, landlord_id=tenant.landlord_id)
            .first()
        )
        if template is None:
            raise ApiError("That template does not exist on this account.", status=404)

    unit = tenant.unit
    lease = LeaseAgreement(
        landlord_id = tenant.landlord_id,
        tenant_id   = tenant.id,
        unit_id     = unit.id if unit else None,
        property_id = unit.property_id if unit else None,
        template_id = template.id if template else None,
        status      = LeaseStatus.draft.value,
        source      = LeaseSource.portal.value,
        body_html   = render_body(
            (template.content if template else None) or default_template_html(),
            field_context(tenant),
        ),
        created_by  = actor_user_id,
    )
    db.session.add(lease)
    db.session.flush()
    return lease


def supersede_outstanding(tenant_id: int, *, keep_id: int | None = None) -> int:
    """
    Retire every OTHER un-signed agreement on this tenancy. Returns how many.

    Without this a tenancy accumulates agreements. "Prepare" looks like it did
    nothing — the landlord is waiting on the tenant, not on the system — so it
    gets pressed again, and each press leaves another lease sitting in `sent`
    forever. current_for_tenant() then answers "what must I sign?" with
    whichever of those is newest, which after an approval is a stale one: the
    tenant signs an agreement, the landlord approves it, and the portal
    immediately shows them a different unsigned lease and hides the download
    for the one they just completed. That is the "the lease never reaches the
    tenant" report, from both ends.

    A signed lease is never touched. `submitted` and `approved` are outside
    is_outstanding precisely so a second Prepare cannot discard a signature.
    """
    rows = (
        db.session.query(LeaseAgreement)
        .filter(LeaseAgreement.tenant_id == tenant_id)
        .all()
    )
    retired = 0
    for row in rows:
        if row.id == keep_id or not row.is_outstanding:
            continue
        transition(row, LeaseStatus.superseded.value)
        retired += 1
    if retired:
        db.session.flush()
        logger.info("Superseded %s outstanding lease(s) for tenant %s.", retired, tenant_id)
    return retired


def send_to_tenant(lease: LeaseAgreement, *, actor_user_id=None) -> LeaseAgreement:
    transition(lease, LeaseStatus.sent.value, actor_user_id=actor_user_id)
    lease.sent_at = datetime.utcnow()
    # This is now THE agreement for the tenancy; anything else still waiting on
    # the tenant is a superseded draft and must stop competing with it.
    supersede_outstanding(lease.tenant_id, keep_id=lease.id)
    db.session.flush()
    return lease


def submit(lease: LeaseAgreement, *, signed_name: str, field_values: dict,
           ip: str | None, user_agent: str | None) -> LeaseAgreement:
    """
    The tenant's signature. The one write that has to be right.

    Captures the consent event and its provenance together, then renders the
    PDF immediately so what the landlord reviews is exactly what was signed.
    """
    signed_name = (signed_name or "").strip()
    if len(signed_name) < 3:
        raise ApiError("Type your full name to sign.", status=422,
                       errors={"signed_name": "required"})

    transition(lease, LeaseStatus.submitted.value)
    lease.field_values      = field_values or {}
    lease.signed_name       = signed_name[:200]
    lease.signed_at         = datetime.utcnow()
    lease.signed_ip         = (ip or "")[:45] or None
    lease.signed_user_agent = (user_agent or "")[:400] or None
    lease.submitted_at      = lease.signed_at
    lease.rejection_reason  = None      # a fresh submission clears the last note
    db.session.flush()

    lease.document_url = store_pdf(lease)
    db.session.flush()
    return lease


def approve(lease: LeaseAgreement, *, actor_user_id=None) -> LeaseAgreement:
    transition(lease, LeaseStatus.approved.value, actor_user_id=actor_user_id)
    lease.reviewed_by = actor_user_id
    lease.reviewed_at = datetime.utcnow()
    db.session.flush()
    # Re-render so the landlord's acceptance appears on the copy both sides keep.
    lease.document_url = store_pdf(lease)
    db.session.flush()
    return lease


def reject(lease: LeaseAgreement, *, reason: str, actor_user_id=None) -> LeaseAgreement:
    reason = (reason or "").strip()
    if not reason:
        raise ApiError(
            "Say what needs correcting — the tenant cannot fix an unexplained rejection.",
            status=422, errors={"reason": "required"},
        )
    transition(lease, LeaseStatus.rejected.value, actor_user_id=actor_user_id)
    lease.reviewed_by      = actor_user_id
    lease.reviewed_at      = datetime.utcnow()
    lease.rejection_reason = reason[:500]
    # The signature does not survive a rejection: the tenant signs again after
    # correcting, and a stale signature on an edited document is worthless.
    lease.signed_name = lease.signed_at = lease.signed_ip = None
    lease.signed_user_agent = None
    lease.document_url = None
    db.session.flush()
    return lease


def attach_scan(tenant: Tenant, file, *, actor_user_id=None,
                filename: str | None = None) -> LeaseAgreement:
    """
    Record a lease that was signed on paper.

    Arrives complete — there is nothing to review, because a person already
    witnessed the signing — so it goes straight to `uploaded`, downloadable by
    both sides at once.
    """
    from services.storage_service import upload_to_s3

    unit = tenant.unit
    url = upload_to_s3(
        file, folder=f"leases/{tenant.landlord_id}/{tenant.id}",
        filename=filename, profile="lease", force_local=True,
    )

    lease = LeaseAgreement(
        landlord_id  = tenant.landlord_id,
        tenant_id    = tenant.id,
        unit_id      = unit.id if unit else None,
        property_id  = unit.property_id if unit else None,
        status       = LeaseStatus.uploaded.value,
        source       = LeaseSource.uploaded.value,
        document_url = url,
        reviewed_by  = actor_user_id,
        reviewed_at  = datetime.utcnow(),
        created_by   = actor_user_id,
    )
    db.session.add(lease)
    db.session.flush()
    # A lease signed on paper settles the tenancy, so an unsigned portal lease
    # still sitting with the tenant is now asking them to sign it twice.
    supersede_outstanding(tenant.id, keep_id=lease.id)
    return lease


def current_for_tenant(tenant_id: int) -> LeaseAgreement | None:
    """
    The agreement that matters to the TENANT right now, in priority order:

      1. one waiting on them (sent, or rejected and needing correction);
      2. else the newest settled one (approved / uploaded);
      3. else the newest of anything.

    Rule 1 is the fix for a renewal going unnoticed. This used to return the
    newest SETTLED lease first, which meant that once a tenant had any approved
    agreement, a newly sent one was invisible to them forever — the old one
    always won. The portal showed last year's signed lease, the renewal sat in
    `sent` indefinitely, and because the submit endpoint resolves the lease the
    same way, the tenant could not have signed it even if they had known it
    existed.

    A DRAFT still never displaces a signed agreement: it is neither awaiting the
    tenant nor settled, so it can only ever be reached by rule 3. That is
    deliberate — a lease the landlord has not sent yet is not the tenant's
    business, and showing it invites arguments about which version is binding.

    NOTE: this is the tenant's "what do I do next" question, which is not the
    same as "which lease may I download" — during a renewal those are two
    different documents. Downloads use latest_downloadable_for_tenant().
    """
    leases = (
        db.session.query(LeaseAgreement)
        .filter_by(tenant_id=tenant_id)
        .order_by(LeaseAgreement.created_at.desc())
        .all()
    )
    for lease in leases:
        if lease.awaiting_tenant:
            return lease
    for lease in leases:
        if lease.status in DOWNLOADABLE_LEASE_STATUSES:
            return lease
    return leases[0] if leases else None


def latest_downloadable_for_tenant(tenant_id: int) -> LeaseAgreement | None:
    """
    The newest lease the tenant may actually download — approved or uploaded.

    Separate from current_for_tenant() because during a renewal the two diverge:
    the lease that matters is the unsigned one they must act on, but the lease
    they can still download is last year's signed agreement. Resolving downloads
    through current_for_tenant() would take that copy away the moment a renewal
    was sent, which is exactly when someone is most likely to want it.
    """
    return (
        db.session.query(LeaseAgreement)
        .filter(LeaseAgreement.tenant_id == tenant_id,
                LeaseAgreement.status.in_(DOWNLOADABLE_LEASE_STATUSES))
        .order_by(LeaseAgreement.created_at.desc())
        .first()
    )
