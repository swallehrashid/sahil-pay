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

    api_key = current_app.config.get("SENDGRID_API_KEY")
    sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@sahilpay.com")
    sender_name = current_app.config.get("MAIL_DEFAULT_SENDER_NAME", "SahilPay")

    if not api_key:
        logger.info("EMAIL [stub — SendGrid not configured] to %s | subject: %s\n%s", to_email, subject, html_body)
        return False

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": sender, "name": sender_name},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
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
    subject = "Your SahilPay login code"
    html = T.render_email(
        heading="Your login code",
        intro=f"Hi {T.escape(first_name or 'there')}, use the one-time code below to sign in to your SahilPay tenant portal.",
        blocks=[
            T.code_box(code, caption="One-time code"),
            T.note("This code expires in 10 minutes and can only be used once. "
                   "If you didn't try to log in, you can ignore this email — no one can access your account without it."),
        ],
        preheader=f"Your SahilPay login code is {code}",
        footer_note="You're receiving this because someone requested a login code for your SahilPay tenant account.",
    )
    _send_email(identifier, subject, html)


@celery.task(name="services.email_service.send_verification_email")
def send_verification_email(email: str, verification_token: str) -> None:
    """Celery task — sends the email-verification link after registration."""
    link = f"{_frontend_url()}/verify-email/{verification_token}"
    subject = "Verify your SahilPay account"
    html = T.render_email(
        heading="Confirm your email to activate your account",
        intro="Welcome to SahilPay! You're one step away. Confirm this email address to "
              "verify and activate your landlord account so you can start managing your "
              "properties, tenants and rent collection.",
        blocks=[
            T.button("Verify my email", link),
            T.note(f'If the button doesn\'t work, copy and paste this link into your browser:<br>'
                   f'<a href="{T.escape(link, quote=True)}" style="color:{T.ACCENT};">{T.escape(link)}</a>'),
            T.note("This link is unique to you. If you didn't create a SahilPay account, you can ignore this email."),
        ],
        preheader="Confirm your email to activate your SahilPay account.",
        footer_note="You're receiving this because a SahilPay account was created with this email address.",
    )
    _send_email(email, subject, html)


@celery.task(name="services.email_service.send_password_reset_email")
def send_password_reset_email(email: str, reset_token: str) -> None:
    """Celery task — sends a password-reset link (landlord, team member or any user)."""
    link = f"{_frontend_url()}/reset-password?token={reset_token}"
    subject = "Reset your SahilPay password"
    html = T.render_email(
        heading="Reset your password",
        intro="We received a request to reset the password for your SahilPay account. "
              "Click the button below to choose a new one.",
        blocks=[
            T.button("Reset my password", link),
            T.note(f'Or paste this link into your browser:<br>'
                   f'<a href="{T.escape(link, quote=True)}" style="color:{T.ACCENT};">{T.escape(link)}</a>'),
            T.note("This link expires after a single use. If you didn't request a password reset, "
                   "you can safely ignore this email — your password won't change."),
        ],
        preheader="Reset your SahilPay password.",
        footer_note="You're receiving this because a password reset was requested for your SahilPay account.",
    )
    _send_email(email, subject, html)


@celery.task(name="services.email_service.send_team_activation_email")
def send_team_activation_email(email: str, activation_token: str, username: str) -> None:
    """
    Legacy activation-link flow (kept for backwards compatibility). New team
    members now receive their credentials directly — see send_team_credentials_email.
    """
    link = f"{_frontend_url()}/team-activate/{activation_token}"
    subject = "Activate your SahilPay team account"
    html = T.render_email(
        heading="Activate your team account",
        intro=f"Hi {T.escape(username)}, you've been added as a team member on SahilPay. "
              f"Activate your account and set a password to get started.",
        blocks=[T.button("Activate my account", link)],
        preheader="Activate your SahilPay team account.",
    )
    _send_email(email, subject, html)


@celery.task(name="services.email_service.send_team_credentials_email")
def send_team_credentials_email(
    email: str,
    username: str,
    temp_password: str,
    first_name: str | None = None,
    company_name: str | None = None,
) -> None:
    """
    Celery task — emails a newly-created team member their login credentials
    (email, username, temporary password) plus how to log in and change it.
    """
    login_url = f"{_frontend_url()}/login"
    who = first_name or username
    by = f" by {T.escape(company_name)}" if company_name else ""
    subject = "Your SahilPay team account is ready"
    html = T.render_email(
        heading="Your team account is ready",
        intro=f"Hi {T.escape(who)}, a SahilPay team member account has been created for you{by}. "
              f"Use the credentials below to log in to your team portal.",
        blocks=[
            T.credentials([
                ("Email", email),
                ("Username", username),
                ("Temp password", temp_password),
            ]),
            T.button("Log in to SahilPay", login_url),
            T.paragraph("<strong style='color:#fff;'>Please change your password right after your first login.</strong>"),
            T.steps([
                "Click <strong>Log in to SahilPay</strong> above and sign in with the email and temporary password.",
                "You'll be taken straight to <strong>Change password</strong> — enter the temporary password, then set a new private one (at least 8 characters).",
                "From then on, log in with your email and your new password. Your username never changes.",
            ]),
            T.note("Keep these details private. If you didn't expect this account, contact the person who manages your SahilPay team."),
        ],
        preheader="Your SahilPay team login details are inside.",
        footer_note="You're receiving this because a SahilPay team account was created for this email address.",
    )
    _send_email(email, subject, html)


@celery.task(name="services.email_service.send_receipt_email")
def send_receipt_email(email: str, first_name: str, pdf_bytes: bytes, payment_ref: str) -> None:
    """Celery task — emails a payment receipt PDF."""
    subject = f"Your SahilPay receipt — {payment_ref}"
    html = T.render_email(
        heading="Payment received — thank you",
        intro=f"Hi {T.escape(first_name or 'there')}, we've recorded your payment. "
              f"Your receipt <strong>{T.escape(payment_ref)}</strong> is attached to this email as a PDF.",
        preheader=f"Your SahilPay receipt {payment_ref} is attached.",
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
    subject = "Your SahilPay account statement"
    html = T.render_email(
        heading="Your account statement",
        intro=f"Hi {T.escape(first_name or 'there')}, your latest SahilPay account statement is attached as a PDF.",
        preheader="Your SahilPay account statement is attached.",
    )
    _send_email(email, subject, html, pdf_bytes=pdf_bytes, pdf_filename="statement.pdf")


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
        blocks.append(T.button("View document", file_url))
    html = T.render_email(
        heading="A document from your landlord",
        intro=f"Hi {T.escape(first_name or 'there')}, your landlord has sent you a document: "
              f"<strong>{T.escape(template_name)}</strong>." +
              ("" if file_url and not pdf_bytes else " It's attached to this email as a PDF."),
        blocks=blocks,
        preheader=f"{template_name} from your landlord.",
    )
    _send_email(email, subject, html, pdf_bytes=pdf_bytes, pdf_filename=f"{template_name}.pdf" if pdf_bytes else None)
