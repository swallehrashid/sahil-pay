"""
SahilPay — services/email_service.py
=======================================
Transactional email. _send_email() is a real implementation — it posts to
SendGrid's v3 API with stdlib urllib + json (no SDK dependency) whenever
SENDGRID_API_KEY is configured, and falls back to logging the message when
it isn't, so registration/OTP/receipt flows still complete while testing
without real email credentials.

Every public function here is a Celery task (routes call them via
.delay(...)), matching how routes/*.py already imports them.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request

from flask import current_app

from celery_app import celery
from services import email_templates as T

logger = logging.getLogger(__name__)

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def _frontend_url() -> str:
    return current_app.config.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")


def _absolute_url(url: str) -> str:
    """
    A link that works from inside an email client.

    Storage hands back relative paths for locally-held files and absolute ones
    for anything on a CDN, and only the caller knows which it has — so normalise
    here rather than at every call site.
    """
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{_frontend_url()}/{url.lstrip('/')}"


def _send_email(
    to_email: str,
    subject: str,
    html_body: str,
    pdf_bytes: bytes | None = None,
    pdf_filename: str | None = None,
) -> bool:
    """
    Send one HTML email, optionally with a single PDF attachment. Returns
    True if a real send was attempted and accepted, False if SendGrid isn't
    configured (the email is logged instead) or the send failed. Never
    raises — a failed email should never fail the request/task that
    triggered it.
    """
    if not to_email:
        logger.warning("_send_email: no recipient address given for subject '%s' — skipping.", subject)
        return False

    # Honour COMMS_SIMULATION_MODE like the SMS path: when simulation is on (the
    # default until go-live) log the email instead of dispatching, so a non-prod
    # environment that happens to carry a real SendGrid key never emails a real
    # person. In production (COMMS_SIMULATION_MODE=false) real emails are sent.
    if current_app.config.get("COMMS_SIMULATION_MODE", True):
        logger.info("EMAIL [simulated — not sent] to %s: %s", to_email, subject)
        return False

    api_key = current_app.config.get("SENDGRID_API_KEY")
    sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@sahilpay.co.ke")
    sender_name = current_app.config.get("MAIL_DEFAULT_SENDER_NAME", "Sahil Pay")

    if not api_key:
        logger.info("EMAIL [stub — SendGrid not configured] to %s | subject: %s\n%s", to_email, subject, html_body)
        return False

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": sender, "name": sender_name},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
        # Send these EXPLICITLY rather than inheriting the SendGrid account
        # default, which has click tracking on.
        #
        # Click tracking rewrites every href into a ct.sendgrid.net redirect.
        # For marketing mail that is a fair trade; for this mail it is not.
        # Everything sent from here is a one-shot credential: a verification
        # link, a password reset, a team invitation, a receipt. If the tracking
        # domain is not authenticated — or the redirect is stripped, flagged as
        # a phishing pattern, or mangled by a mail client — the recipient is
        # locked out of their account, and the analytics gained were worth
        # nothing. The real destination is also what makes the link trustworthy:
        # people check that a login link points at sahilpay.co.ke before
        # clicking, and an opaque redirect defeats that.
        #
        # Open tracking is off for the same reason it is not needed: it injects
        # a remote pixel into every receipt, which triggers "images blocked"
        # banners on financial mail that should look plain and legitimate.
        "tracking_settings": {
            "click_tracking": {"enable": False, "enable_text": False},
            "open_tracking": {"enable": False},
            "subscription_tracking": {"enable": False},
        },
    }
    if pdf_bytes:
        payload["attachments"] = [
            {
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
                "filename": pdf_filename or "document.pdf",
                "type": "application/pdf",
                "disposition": "attachment",
            }
        ]

    req = urllib.request.Request(
        SENDGRID_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            logger.info("Email sent to %s via SendGrid: %s", to_email, subject)
            return True
    except urllib.error.URLError as exc:
        logger.error("_send_email failed for %s: %s", to_email, exc)
        return False


@celery.task(name="services.email_service.send_otp_email")
def send_otp_email(identifier: str, code: str, first_name: str) -> None:
    """Celery task — sends a tenant's OTP login code via email."""
    subject = "Your Sahil Pay login code"
    html = T.render_email(
        heading="Your login code",
        intro=f"Hi {T.escape(first_name or 'there')}, use the one-time code below to sign in to your Sahil Pay tenant portal.",
        blocks=[
            T.code_box(code, caption="One-time code"),
            T.note("This code expires in 10 minutes and can only be used once. "
                   "If you didn't try to log in, you can ignore this email — no one can access your account without it."),
        ],
        preheader=f"Your Sahil Pay login code is {code}",
        footer_note="You're receiving this because someone requested a login code for your Sahil Pay tenant account.",
    )
    _send_email(identifier, subject, html)


@celery.task(name="services.email_service.send_verification_email")
def send_verification_email(email: str, verification_token: str) -> None:
    """Celery task — sends the email-verification link after registration."""
    link = f"{_frontend_url()}/verify-email/{verification_token}"
    subject = "Verify your Sahil Pay account"
    html = T.render_email(
        heading="Confirm your email to activate your account",
        intro="Welcome to Sahil Pay! You're one step away. Confirm this email address to "
              "verify and activate your landlord account so you can start managing your "
              "properties, tenants and rent collection.",
        blocks=[
            T.button("Verify my email", link),
            T.note(f'If the button doesn\'t work, copy and paste this link into your browser:<br>'
                   f'<a href="{T.escape(link, quote=True)}" style="color:{T.ACCENT};">{T.escape(link)}</a>'),
            T.note("This link is unique to you. If you didn't create a Sahil Pay account, you can ignore this email."),
        ],
        preheader="Confirm your email to activate your Sahil Pay account.",
        footer_note="You're receiving this because a Sahil Pay account was created with this email address.",
    )
    _send_email(email, subject, html)


@celery.task(name="services.email_service.send_password_reset_email")
def send_password_reset_email(email: str, reset_token: str) -> None:
    """Celery task — sends a password-reset link (landlord, team member or any user)."""
    link = f"{_frontend_url()}/reset-password?token={reset_token}"
    subject = "Reset your Sahil Pay password"
    html = T.render_email(
        heading="Reset your password",
        intro="We received a request to reset the password for your Sahil Pay account. "
              "Click the button below to choose a new one.",
        blocks=[
            T.button("Reset my password", link),
            T.note(f'Or paste this link into your browser:<br>'
                   f'<a href="{T.escape(link, quote=True)}" style="color:{T.ACCENT};">{T.escape(link)}</a>'),
            T.note("This link expires after a single use. If you didn't request a password reset, "
                   "you can safely ignore this email — your password won't change."),
        ],
        preheader="Reset your Sahil Pay password.",
        footer_note="You're receiving this because a password reset was requested for your Sahil Pay account.",
    )
    _send_email(email, subject, html)


@celery.task(name="services.email_service.send_team_activation_email")
def send_team_activation_email(email: str, activation_token: str, username: str) -> None:
    """
    Legacy activation-link flow (kept for backwards compatibility). New team
    members now receive their credentials directly — see send_team_credentials_email.
    """
    link = f"{_frontend_url()}/team-activate/{activation_token}"
    subject = "Activate your Sahil Pay team account"
    html = T.render_email(
        heading="Activate your team account",
        intro=f"Hi {T.escape(username)}, you've been added as a team member on Sahil Pay. "
              f"Activate your account and set a password to get started.",
        blocks=[T.button("Activate my account", link)],
        preheader="Activate your Sahil Pay team account.",
    )
    _send_email(email, subject, html)


@celery.task(name="services.email_service.send_team_credentials_email")
def send_team_credentials_email(
    email: str,
    username: str,
    temp_password: str,
    first_name: str | None = None,
    company_name: str | None = None,
    verification_token: str | None = None,
) -> None:
    """
    Celery task — emails a newly-created team member their login credentials
    (email, username, temporary password) plus how to log in and change it.

    When *verification_token* is present the primary button VERIFIES the address
    and then lands on sign-in, because the account cannot log in until it does.
    Keeping it to a single button matters: two competing calls to action ("verify"
    and "log in") is how people click the wrong one, hit a refusal on a brand
    new account, and conclude the invitation is broken.
    """
    login_url = f"{_frontend_url()}/login"
    who = first_name or username
    by = f" by {T.escape(company_name)}" if company_name else ""
    subject = "Your Sahil Pay team account is ready"

    if verification_token:
        action_url = f"{_frontend_url()}/verify-email/{verification_token}?next=login"
        action_label = "Verify my email & log in"
        first_step = (
            "Click <strong>Verify my email &amp; log in</strong> above. That confirms "
            "this address and takes you to the sign-in page."
        )
    else:
        action_url = login_url
        action_label = "Log in to Sahil Pay"
        first_step = (
            "Click <strong>Log in to Sahil Pay</strong> above and sign in with the "
            "email and temporary password."
        )

    html = T.render_email(
        heading="Your team account is ready",
        intro=f"Hi {T.escape(who)}, a Sahil Pay team member account has been created for you{by}. "
              f"Use the credentials below to log in to your team portal.",
        blocks=[
            T.credentials([
                ("Email", email),
                ("Username", username),
                ("Temp password", temp_password),
            ]),
            T.button(action_label, action_url),
            T.paragraph("<strong style='color:#fff;'>Please change your password right after your first login.</strong>"),
            T.steps([
                first_step,
                "Sign in with the email and temporary password above.",
                "You'll be taken straight to <strong>Change password</strong> — enter the temporary password, then set a new private one (at least 8 characters).",
                "From then on, log in with your email and your new password. Your username never changes.",
            ]),
            T.note("Keep these details private. If you didn't expect this account, contact the person who manages your Sahil Pay team."),
        ],
        preheader="Your Sahil Pay team login details are inside.",
        footer_note="You're receiving this because a Sahil Pay team account was created for this email address.",
    )
    _send_email(email, subject, html)


@celery.task(name="services.email_service.send_receipt_email")
def send_receipt_email(email: str, first_name: str, pdf_bytes: bytes, payment_ref: str) -> None:
    """Celery task — emails a payment receipt PDF."""
    subject = f"Your Sahil Pay receipt — {payment_ref}"
    html = T.render_email(
        heading="Payment received — thank you",
        intro=f"Hi {T.escape(first_name or 'there')}, we've recorded your payment. "
              f"Your receipt <strong>{T.escape(payment_ref)}</strong> is attached to this email as a PDF.",
        preheader=f"Your Sahil Pay receipt {payment_ref} is attached.",
    )
    _send_email(email, subject, html, pdf_bytes=pdf_bytes, pdf_filename=f"{payment_ref}.pdf")


@celery.task(name="services.email_service.send_invoice_email")
def send_invoice_email(email: str, first_name: str, pdf_bytes: bytes, invoice_number: str) -> None:
    """Celery task — emails an invoice PDF."""
    subject = f"New invoice from your landlord — {invoice_number}"
    html = T.render_email(
        heading="You have a new invoice",
        intro=f"Hi {T.escape(first_name or 'there')}, a new invoice "
              f"<strong>{T.escape(invoice_number)}</strong> has been issued to you. "
              f"It's attached as a PDF — log in to your tenant portal to view the breakdown or pay.",
        preheader=f"New invoice {invoice_number} from your landlord.",
    )
    _send_email(email, subject, html, pdf_bytes=pdf_bytes, pdf_filename=f"{invoice_number}.pdf")


@celery.task(name="services.email_service.send_statement_email")
def send_statement_email(email: str, first_name: str, pdf_bytes: bytes) -> None:
    """Celery task — emails a tenant statement PDF."""
    subject = "Your Sahil Pay account statement"
    html = T.render_email(
        heading="Your account statement",
        intro=f"Hi {T.escape(first_name or 'there')}, your latest Sahil Pay account statement is attached as a PDF.",
        preheader="Your Sahil Pay account statement is attached.",
    )
    _send_email(email, subject, html, pdf_bytes=pdf_bytes, pdf_filename="statement.pdf")


@celery.task(name="services.email_service.send_owner_statement_email")
def send_owner_statement_email(
    email: str,
    first_name: str,
    property_name: str,
    period_label: str,
    company_name: str,
    pdf_bytes: bytes,
) -> None:
    """
    Celery task — emails a property owner their monthly property statement.

    Sent by a property manager to the landlord who actually owns the block, so
    the copy speaks as the management company, not as the platform.
    """
    subject = f"{property_name} — statement for {period_label}"
    manager = T.escape(company_name or "Your property manager")
    html = T.render_email(
        heading=f"{property_name} — {period_label}",
        intro=(
            f"Hi {T.escape(first_name or 'there')}, here is the statement for "
            f"<strong>{T.escape(property_name)}</strong> covering {T.escape(period_label)}. "
            "The full breakdown — collections, expenses and net income — is attached as a PDF."
        ),
        blocks=[
            T.note(
                "You can also sign in to Sahil Pay at any time to see live figures for your property."
            ),
        ],
        preheader=f"{property_name} statement for {period_label} is attached.",
        footer_note=f"Sent by {manager} via Sahil Pay.",
    )
    _send_email(
        email, subject, html,
        pdf_bytes=pdf_bytes,
        pdf_filename=f"{property_name} — {period_label}.pdf".replace("/", "-"),
    )


@celery.task(name="services.email_service.send_document_email")
def send_document_email(
    email: str,
    first_name: str,
    template_name: str,
    pdf_bytes: bytes | None,
    file_url: str | None,
) -> None:
    """Celery task — emails a dispatched document template (lease, tenancy agreement, deposit, etc.)."""
    subject = f"Document from your landlord — {template_name}"
    blocks = []
    if file_url and not pdf_bytes:
        # Absolute, always. Uploaded files are stored with RELATIVE urls
        # ("/uploads/leases/1/a.pdf") because that is what the app needs, but an
        # email has no base URL to resolve them against — a relative href in a
        # mail client either does nothing or resolves against the WEBMAIL
        # provider's own domain. Either way the recipient cannot open the
        # document, which is indistinguishable from the app being broken.
        blocks.append(T.button("View document", _absolute_url(file_url)))
    html = T.render_email(
        heading="A document from your landlord",
        intro=f"Hi {T.escape(first_name or 'there')}, your landlord has sent you a document: "
              f"<strong>{T.escape(template_name)}</strong>." +
              ("" if file_url and not pdf_bytes else " It's attached to this email as a PDF."),
        blocks=blocks,
        preheader=f"{template_name} from your landlord.",
    )
    _send_email(email, subject, html, pdf_bytes=pdf_bytes, pdf_filename=f"{template_name}.pdf" if pdf_bytes else None)
