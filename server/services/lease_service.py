"""
services/lease_service.py — tenancy agreements.

WHICH DOCUMENT × HOW IT IS SIGNED
---------------------------------
WHICH (lease.document_kind):
    standard   Sahil Pay's own Kenyan tenancy agreement
    custom     the landlord's own wording (Settings → Documents)
    uploaded   a file the landlord uploaded — e.g. a photo of their paper lease

HOW (lease.signing_method), chosen by the TENANT for any of the three:
    electronic read it in the portal, type their name, tick to agree
    scan       download the blank copy, print, sign by hand, photograph or
               scan it, upload it back

    SENT TO TENANT   draft → sent → submitted → approved      (both download)
                                     ↘ rejected → submitted   (corrected)
    OFFICE PAPER     uploaded                                 (signed in person)

Every page the system produces carries the landlord's logo, theme colours,
letterhead and contact details (services/document_brand.py).

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
    DOWNLOADABLE_LEASE_STATUSES, DocumentTemplate, LeaseAgreement, LeaseDocumentKind,
    LeaseSigningMethod, LeaseSource, LeaseStatus, Tenant,
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


_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td", "blockquote", "hr", "span", "div", "small",
}


def sanitise_html(html: str | None) -> str:
    """
    Strip everything but document formatting from agreement HTML.

    A custom template is typed by a landlord or a team member and then rendered
    inside every tenant's browser. Without this, one <script> or onerror= in a
    template would run in the portal of every tenant the lease is sent to.
    """
    if not html:
        return ""
    import nh3
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes={"td": {"colspan"}, "th": {"colspan"}},
                     url_schemes=set(), link_rel=None)


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
        sanitise_html(template_html),
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


# ---------------------------------------------------------------------------
# Branded PDF rendering
# ---------------------------------------------------------------------------

def _meta(lease: LeaseAgreement, title: str | None = None) -> dict:
    from services.report_builder import build_meta

    tenant = lease.tenant
    subject = None
    if tenant is not None:
        unit = lease.unit.name if lease.unit else None
        subject = " · ".join(p for p in (f"{tenant.first_name} {tenant.last_name}".strip(),
                                         f"Unit {unit}" if unit else None) if p)
    return build_meta(
        lease.landlord,
        report_title=title or lease.title or "Tenancy Agreement",
        subject=subject,
        property_name=lease.property.name if lease.property else None,
    )


def _document_css(meta: dict, numbered: bool = True) -> str:
    """
    Report stylesheet in the landlord's colours, plus the lease's own rules and
    a running footer — contact details and page numbers on EVERY page, so a
    single photographed page still says whose document it is.
    """
    from services import document_brand, receipt_theme
    from services.report_builder import report_style

    theme = receipt_theme.resolve(meta.get("theme"))
    primary, secondary = theme["primary"], theme["secondary"]
    muted = receipt_theme.tint(primary, 0.42)
    footer = " · ".join(p for p in (meta.get("company_name"), document_brand.contact_line(meta)) if p)
    footer = footer.replace("\\", "").replace('"', "'")
    # A composed PDF is stitched from several renders, each of which would count
    # its own pages ("Page 1 of 1" on a three-page lease) — so only a document
    # rendered in one piece is numbered.
    page_counter = (f'@bottom-right {{ content: "Page " counter(page) " of " counter(pages); '
                    f'font-size: 8pt; color: {muted}; }}') if numbered else ""
    return report_style(meta.get("theme")) + f"""
<style>
  @page {{ size: A4; margin: 18mm 16mm 20mm;
          @bottom-left {{ content: "{footer}"; font-size: 8pt; color: {muted}; }}
          {page_counter} }}
  body {{ font-size: 11pt; line-height: 1.55; color: #1f2430; }}
  .agreement h1 {{ font-size: 15pt; text-align: center; letter-spacing: .06em; color: {primary}; margin: 14px 0 16px; }}
  .agreement h2 {{ font-size: 11.5pt; color: {secondary}; margin: 16px 0 4px; }}
  .agreement p {{ margin: 5px 0; }}
  .parties {{ margin: 10px 0 4px; }}
  .sign-grid {{ width: 100%; border-collapse: collapse; margin-top: 18px; page-break-inside: avoid; }}
  .sign-grid td {{ width: 50%; vertical-align: top; padding: 10px 12px; border: 1px solid {receipt_theme.tint(primary, 0.8)}; }}
  .sign-grid h3 {{ margin: 0 0 8px; font-size: 10.5pt; color: {primary}; text-transform: uppercase; letter-spacing: .05em; }}
  .fill {{ border-bottom: 1px solid {primary}; height: 22px; margin: 2px 0 8px; }}
  .fill-label {{ font-size: 8.5pt; color: {muted}; }}
  .e-sign {{ font-size: 15pt; font-style: italic; color: {primary}; margin: 4px 0; }}
  .small {{ font-size: 8.5pt; color: {muted}; }}
  .instructions {{ margin-top: 14px; padding: 10px 12px; border-left: 3px solid {secondary};
                   background: {receipt_theme.tint(secondary, 0.95)}; font-size: 9.5pt; page-break-inside: avoid; }}
  .cover-box {{ margin-top: 18px; }}
  .stamp {{ display: inline-block; padding: 4px 12px; border: 2px solid {secondary}; color: {secondary};
            font-weight: 700; letter-spacing: .08em; border-radius: 6px; }}
  .scan-page {{ page-break-before: always; text-align: center; }}
  .scan-page img {{ max-width: 100%; max-height: 235mm; object-fit: contain; }}
</style>"""


def _signature_blocks(lease: LeaseAgreement, *, blank: bool) -> str:
    """
    Tenant and landlord signature panels.

    Blank: ruled lines to fill in by hand — this is the page a tenant prints.
    Otherwise: the recorded e-signature (name, time, origin) and the landlord's
    acceptance, or ruled lines where a party has not signed yet.
    """
    def lines(*labels):
        return "".join(f"<div class='fill'></div><div class='fill-label'>{escape(l)}</div>" for l in labels)

    tenant_name = ""
    if lease.tenant is not None:
        tenant_name = f"{lease.tenant.first_name} {lease.tenant.last_name}".strip()

    if not blank and lease.signing_method == LeaseSigningMethod.electronic.value and lease.signed_name:
        tenant_cell = (
            f"<h3>Tenant</h3><div class='e-sign'>{escape(lease.signed_name)}</div>"
            f"<div class='small'>Signed electronically on {escape(_when(lease.signed_at))} (EAT)<br>"
            f"Recorded from IP {escape(lease.signed_ip or 'unknown')}. The tenant confirmed they had read "
            f"this agreement and agreed to be bound by it.</div>"
        )
    elif not blank and lease.signing_method == LeaseSigningMethod.scan.value and lease.signed_name:
        tenant_cell = (
            f"<h3>Tenant</h3><div class='e-sign'>{escape(lease.signed_name)}</div>"
            f"<div class='small'>Signed by hand on paper; the signed pages follow this page. "
            f"Returned through the tenant portal on {escape(_when(lease.signed_at))} (EAT).</div>"
        )
    else:
        tenant_cell = (f"<h3>Tenant</h3><div class='small'>{escape(tenant_name)}</div>"
                       + lines("Full name", "ID / passport number", "Signature", "Date"))

    company = escape(getattr(lease.landlord, "company_name", "") or "Landlord")
    if not blank and lease.status == LeaseStatus.approved.value and lease.reviewed_at:
        sig_url = getattr(lease.landlord, "signature_url", None)
        img = (f"<img src='{escape(sig_url)}' style='max-height:48px;margin:4px 0;'/>" if sig_url else "")
        landlord_cell = (
            f"<h3>Landlord / Agent</h3><div class='small'>{company}</div>{img}"
            f"<div class='small'>Accepted and approved on {escape(_when(lease.reviewed_at))} (EAT).</div>"
        )
    else:
        landlord_cell = (f"<h3>Landlord / Agent</h3><div class='small'>{company}</div>"
                         + lines("Name of signatory", "Signature", "Date"))

    return f"<table class='sign-grid'><tr><td>{tenant_cell}</td><td>{landlord_cell}</td></tr></table>"


def _when(value) -> str:
    """A timestamp as people in Nairobi read it (stored UTC → EAT)."""
    if not value:
        return ""
    from datetime import timedelta
    return (value + timedelta(hours=3)).strftime("%d %b %Y, %H:%M")


def _html_page(meta: dict, inner: str, numbered: bool = True) -> str:
    from services.report_builder import _letterhead_html
    return (f"<!doctype html><html><head><meta charset='utf-8'>{_document_css(meta, numbered)}</head>"
            f"<body>{_letterhead_html(meta)}{inner}</body></html>")


def _details_table(lease: LeaseAgreement) -> str:
    """The tenancy at a glance — the first thing on every lease page set."""
    tenant = lease.tenant
    ctx = field_context(tenant) if tenant is not None else {}
    rows = [
        ("Tenant", ctx.get("tenant_name")),
        ("Phone", ctx.get("tenant_phone")),
        ("Unit", ctx.get("unit_name")),
        ("Property", " — ".join(p for p in (ctx.get("property_name"), ctx.get("property_address")) if p)),
        ("Monthly rent", f"KES {ctx.get('rent_amount')}" if ctx.get("rent_amount") else ""),
        ("Deposit", f"KES {ctx.get('deposit_amount')}" if ctx.get("deposit_amount") else ""),
        ("Term", " to ".join(p for p in (ctx.get("lease_start_date"), ctx.get("lease_end_date")) if p)),
        ("Sent to tenant", _when(lease.sent_at)),
    ]
    if lease.signed_at:
        rows.append(("Signed by tenant", _when(lease.signed_at)))
    if lease.status == LeaseStatus.approved.value and lease.reviewed_at:
        rows.append(("Approved", _when(lease.reviewed_at)))
    body = "".join(f"<tr><td>{escape(k)}</td><td>{escape(str(v))}</td></tr>" for k, v in rows if v)
    return f"<table class='grid kv'><tbody>{body}</tbody></table>"


_PAPER_INSTRUCTIONS = (
    "<div class='instructions'><strong>Signing on paper?</strong> Print this document, fill in "
    "and sign every signature panel in pen, then photograph each page flat in good light (or scan "
    "it) and upload the pages in your Sahil Pay tenant portal under <strong>Leases</strong>. Your "
    "landlord reviews it there — no need to visit the office.</div>"
)


def render_blank_pdf(lease: LeaseAgreement) -> bytes:
    """
    The copy a tenant downloads to read, print and sign by hand.

    Standard / custom: the full agreement with empty signature panels.
    Uploaded: a branded cover sheet (tenancy details + how to return it), the
    landlord's own document exactly as they uploaded it, then a branded
    signature page.
    """
    from utils import render_pdf

    meta = _meta(lease)
    if lease.document_kind == LeaseDocumentKind.uploaded.value and lease.source_document_url:
        cover = render_pdf(_html_page(meta, (
            f"<h2>Tenancy details</h2>{_details_table(lease)}"
            "<div class='instructions'>The pages that follow are your landlord's tenancy agreement. "
            "Read them, sign where indicated and complete the signature page at the end.</div>"
        ), numbered=False))
        signature_page = render_pdf(_html_page(meta, (
            "<h2>Signature page</h2><p>By signing below, both parties agree to the terms of the "
            "attached tenancy agreement.</p>"
            f"{_signature_blocks(lease, blank=True)}{_PAPER_INSTRUCTIONS}"
        ), numbered=False))
        return merge_pdfs([cover, *_source_as_pdfs(meta, lease.source_document_url), signature_page])

    return render_pdf(_html_page(meta, (
        f"{_details_table(lease)}<div class='agreement'>{lease.body_html or ''}</div>"
        f"{_signature_blocks(lease, blank=True)}{_PAPER_INSTRUCTIONS}"
    )))


def render_pdf_bytes(lease: LeaseAgreement) -> bytes:
    """
    The agreement as it stands — the copy under review, then the final copy.

    Rendered from the snapshot taken when the lease was sent (`body_html`), so a
    later edit to the landlord's template can never change the wording of an
    agreement somebody has already signed.

    A hand-signed return is the tenant's own pages, so it is framed rather than
    re-typed: a branded certificate page (who, when, how, approval) followed by
    every page they uploaded.
    """
    from utils import render_pdf

    meta = _meta(lease)
    if lease.signing_method == LeaseSigningMethod.scan.value and lease.tenant_scan_urls:
        status_line = ("<span class='stamp'>APPROVED</span>"
                       if lease.status == LeaseStatus.approved.value
                       else "<span class='stamp'>SUBMITTED FOR REVIEW</span>")
        certificate = render_pdf(_html_page(meta, (
            f"<p>{status_line}</p><h2>Tenancy details</h2>{_details_table(lease)}"
            "<h2>How this agreement was signed</h2>"
            f"<p>Signed by hand by <strong>{escape(lease.signed_name or '')}</strong> and returned "
            f"through the tenant portal on {escape(_when(lease.signed_at))} (EAT) — "
            f"{len(lease.tenant_scan_urls)} page(s) follow.</p>"
            f"{_signature_blocks(lease, blank=False) if lease.status == LeaseStatus.approved.value else ''}"
        ), numbered=False))
        parts = [certificate]
        for url in lease.tenant_scan_urls:
            parts.extend(_source_as_pdfs(meta, url))
        return merge_pdfs(parts)

    inner = (f"{_details_table(lease)}<div class='agreement'>{lease.body_html or ''}</div>"
             f"{_signature_blocks(lease, blank=False)}")
    if lease.document_kind == LeaseDocumentKind.uploaded.value and lease.source_document_url:
        cover = render_pdf(_html_page(meta, (
            f"<h2>Tenancy details</h2>{_details_table(lease)}"
            f"<h2>Signatures</h2>{_signature_blocks(lease, blank=False)}"
        ), numbered=False))
        return merge_pdfs([cover, *_source_as_pdfs(meta, lease.source_document_url)])
    return render_pdf(_html_page(meta, inner))


def _read_stored_file(url: str) -> bytes | None:
    """Bytes of a stored upload — local disk first, then a remote URL."""
    import os

    from flask import current_app

    if not url:
        return None
    marker = "/uploads/"
    if marker in url:
        rel = url.split(marker, 1)[1]
        path = os.path.join(current_app.root_path, "uploads", rel)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                return fh.read()
    if url.startswith(("http://", "https://")):
        try:
            import requests
            resp = requests.get(url, timeout=20)
            if resp.ok and len(resp.content) <= 25 * 1024 * 1024:
                return resp.content
        except Exception:                             # noqa: BLE001
            logger.warning("Could not fetch stored lease file %s", url, exc_info=True)
    return None


def _source_as_pdfs(meta: dict, url: str) -> list[bytes]:
    """
    An uploaded document as PDF bytes: a PDF passes through untouched, a photo
    becomes a page with a slim branded strip above it. Unreadable → a page that
    says so, rather than a lease that silently loses a page.
    """
    from utils import render_pdf

    data = _read_stored_file(url)
    if data and data[:5] == b"%PDF-":
        return [data]
    if data:
        import base64
        kind = "png" if data[:8].startswith(b"\x89PNG") else ("webp" if data[8:12] == b"WEBP" else "jpeg")
        uri = f"data:image/{kind};base64,{base64.b64encode(data).decode('ascii')}"
        company = escape(meta.get("company_name") or "")
        return [render_pdf(
            f"<!doctype html><html><head><meta charset='utf-8'>{_document_css(meta)}</head><body>"
            f"<div class='small' style='border-bottom:1px solid #ccc;padding-bottom:4px;margin-bottom:6px;'>"
            f"{company} — {escape(meta.get('report_title') or 'Tenancy Agreement')}</div>"
            f"<div style='text-align:center'><img src='{uri}' style='max-width:100%;max-height:240mm;'/></div>"
            f"</body></html>"
        )]
    return [render_pdf(_html_page(meta, "<p><strong>A page of this document could not be read from "
                                        "storage.</strong> Please contact the landlord for a copy.</p>"))]


def merge_pdfs(parts: list[bytes]) -> bytes:
    """Concatenate PDFs. A part that is not a readable PDF is skipped, loudly."""
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for part in parts:
        try:
            for page in PdfReader(BytesIO(part)).pages:
                writer.add_page(page)
        except Exception:                             # noqa: BLE001
            logger.warning("Skipping an unreadable PDF part while composing a lease.", exc_info=True)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


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

def create_for_tenant(tenant: Tenant, *, template_id=None, actor_user_id=None,
                      document_kind: str | None = None, upload=None,
                      title: str | None = None) -> LeaseAgreement:
    """
    Prepare an agreement for a tenancy.

      upload=<file>                      uploaded — this file, just for this lease
      template_id=<written template>     custom   — the landlord's own wording
      template_id=<uploaded template>    uploaded — their stored lease document
      nothing                            standard — Sahil Pay's agreement

    A template holding only a FILE used to be read as "no wording" and quietly
    sent the standard agreement instead of the landlord's own lease.
    """
    template = None
    if template_id:
        template = (
            db.session.query(DocumentTemplate)
            .filter_by(id=template_id, landlord_id=tenant.landlord_id)
            .first()
        )
        if template is None:
            raise ApiError("That template does not exist on this account.", status=404)

    source_url = None
    body_template = None
    if upload is not None:
        from services.storage_service import upload_to_s3
        kind = LeaseDocumentKind.uploaded.value
        source_url = upload_to_s3(upload, folder=f"leases/{tenant.landlord_id}/source",
                                  filename=getattr(upload, "filename", None),
                                  profile="lease", force_local=True)
    elif template is not None and template.content:
        kind = LeaseDocumentKind.custom.value
        body_template = template.content
    elif template is not None and template.file_url:
        kind = LeaseDocumentKind.uploaded.value
        source_url = template.file_url
    else:
        if document_kind in (LeaseDocumentKind.custom.value, LeaseDocumentKind.uploaded.value):
            raise ApiError("Choose which of your lease documents to send.", status=422,
                           errors={"template_id": "required"})
        kind = LeaseDocumentKind.standard.value
        body_template = default_template_html()

    unit = tenant.unit
    lease = LeaseAgreement(
        landlord_id   = tenant.landlord_id,
        tenant_id     = tenant.id,
        unit_id       = unit.id if unit else None,
        property_id   = unit.property_id if unit else None,
        template_id   = template.id if template else None,
        status        = LeaseStatus.draft.value,
        source        = LeaseSource.portal.value,
        document_kind = kind,
        source_document_url = source_url,
        title         = (title or (template.name if template else None) or "Tenancy Agreement")[:150],
        body_html     = render_body(body_template, field_context(tenant)) if body_template else None,
        created_by    = actor_user_id,
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
    lease.signing_method    = LeaseSigningMethod.electronic.value
    lease.tenant_scan_urls  = None
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


MAX_SCAN_PAGES = 15


def submit_scan(lease: LeaseAgreement, files: list, *, signed_name: str,
                ip: str | None, user_agent: str | None) -> LeaseAgreement:
    """
    The tenant printed the agreement, signed it by hand and sent the pages back.

    Stored as the tenant's own pages, in order, and framed in a branded PDF for
    the landlord to review. Any of the three document kinds can come back this
    way — a tenant who prefers pen and paper is never forced to type a name.
    """
    from services.storage_service import upload_to_s3

    signed_name = (signed_name or "").strip()
    if len(signed_name) < 3:
        raise ApiError("Type your full name as you signed it.", status=422,
                       errors={"signed_name": "required"})
    files = [f for f in (files or []) if f is not None and getattr(f, "filename", "")]
    if not files:
        raise ApiError("Add a photo or scan of every signed page.", status=422,
                       errors={"files": "required"})
    if len(files) > MAX_SCAN_PAGES:
        raise ApiError(f"Upload at most {MAX_SCAN_PAGES} pages — combine them into one PDF if needed.",
                       status=422, errors={"files": "too_many"})

    transition(lease, LeaseStatus.submitted.value)
    urls = [
        upload_to_s3(f, folder=f"leases/{lease.landlord_id}/{lease.tenant_id}/signed",
                     filename=f.filename, profile="lease", force_local=True)
        for f in files
    ]
    lease.signing_method    = LeaseSigningMethod.scan.value
    lease.tenant_scan_urls  = urls
    lease.signed_name       = signed_name[:200]
    lease.signed_at         = datetime.utcnow()
    lease.signed_ip         = (ip or "")[:45] or None
    lease.signed_user_agent = (user_agent or "")[:400] or None
    lease.submitted_at      = lease.signed_at
    lease.rejection_reason  = None
    db.session.flush()

    lease.document_url = store_pdf(lease)
    db.session.flush()
    return lease


def mark_viewed(lease: LeaseAgreement) -> bool:
    """Record the first time the tenant opened it. True if this was that time."""
    if lease.viewed_at is None and lease.awaiting_tenant:
        lease.viewed_at = datetime.utcnow()
        db.session.flush()
        return True
    return False


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
    lease.signing_method = None
    lease.tenant_scan_urls = None
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
        document_kind = LeaseDocumentKind.uploaded.value,
        title        = "Tenancy Agreement (signed in person)",
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


def leases_for_person(tenant: Tenant) -> list[LeaseAgreement]:
    """
    Every agreement this PERSON may see — across all their tenancies (two units
    in a block, or houses under different landlords). Drafts and superseded
    copies are never shown; newest first, with anything waiting on them on top.
    """
    from models import TENANT_VISIBLE_LEASE_STATUSES
    from services.tenant_identity_service import sibling_tenant_ids

    ids = sibling_tenant_ids(tenant) | {tenant.id}
    rows = (
        db.session.query(LeaseAgreement)
        .filter(LeaseAgreement.tenant_id.in_(ids),
                LeaseAgreement.status.in_(TENANT_VISIBLE_LEASE_STATUSES))
        .order_by(LeaseAgreement.created_at.desc())
        .all()
    )
    return sorted(rows, key=lambda r: 0 if r.awaiting_tenant else 1)
