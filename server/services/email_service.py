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

logger = logging.getLogger(__name__)

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


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
    body = f"<p>Hi {first_name},</p><p>Your SahilPay login code is <strong>{code}</strong>. It expires shortly — do not share it.</p>"
    _send_email(identifier, subject, body)


@celery.task(name="services.email_service.send_verification_email")
def send_verification_email(email: str, verification_token: str) -> None:
    """Celery task — sends the email-verification link after registration."""
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url.rstrip('/')}/verify-email/{verification_token}"
    subject = "Verify your SahilPay account"
    body = f"<p>Welcome to SahilPay!</p><p>Please confirm your email address by clicking the link below:</p><p><a href=\"{link}\">{link}</a></p>"
    _send_email(email, subject, body)


@celery.task(name="services.email_service.send_password_reset_email")
def send_password_reset_email(email: str, reset_token: str) -> None:
    """Celery task — sends a password-reset link."""
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url.rstrip('/')}/reset-password?token={reset_token}"
    subject = "Reset your SahilPay password"
    body = (
        f"<p>We received a request to reset your SahilPay password.</p>"
        f"<p><a href=\"{link}\">{link}</a></p>"
        f"<p>If you didn't request this, you can safely ignore this email.</p>"
    )
    _send_email(email, subject, body)


@celery.task(name="services.email_service.send_team_activation_email")
def send_team_activation_email(email: str, activation_token: str, username: str) -> None:
    """Celery task — sends a new team member their account-activation link."""
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url.rstrip('/')}/team-activate/{activation_token}"
    subject = "Activate your SahilPay team account"
    body = (
        f"<p>Hi {username},</p>"
        f"<p>You've been added as a team member on SahilPay. Activate your account and set a password here:</p>"
        f"<p><a href=\"{link}\">{link}</a></p>"
    )
    _send_email(email, subject, body)


@celery.task(name="services.email_service.send_receipt_email")
def send_receipt_email(email: str, first_name: str, pdf_bytes: bytes, payment_ref: str) -> None:
    """Celery task — emails a payment receipt PDF."""
    subject = f"Your SahilPay receipt — {payment_ref}"
    body = f"<p>Hi {first_name},</p><p>Thank you for your payment. Your receipt ({payment_ref}) is attached.</p>"
    _send_email(email, subject, body, pdf_bytes=pdf_bytes, pdf_filename=f"{payment_ref}.pdf")


@celery.task(name="services.email_service.send_invoice_email")
def send_invoice_email(email: str, first_name: str, pdf_bytes: bytes, invoice_number: str) -> None:
    """Celery task — emails an invoice PDF."""
    subject = f"New invoice from your landlord — {invoice_number}"
    body = f"<p>Hi {first_name},</p><p>A new invoice ({invoice_number}) has been issued to you. It's attached as a PDF.</p>"
    _send_email(email, subject, body, pdf_bytes=pdf_bytes, pdf_filename=f"{invoice_number}.pdf")


@celery.task(name="services.email_service.send_statement_email")
def send_statement_email(email: str, first_name: str, pdf_bytes: bytes) -> None:
    """Celery task — emails a tenant statement PDF."""
    subject = "Your SahilPay account statement"
    body = f"<p>Hi {first_name},</p><p>Your latest account statement is attached.</p>"
    _send_email(email, subject, body, pdf_bytes=pdf_bytes, pdf_filename="statement.pdf")


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
    body = f"<p>Hi {first_name},</p><p>Your landlord has sent you a document: <strong>{template_name}</strong>.</p>"
    if file_url and not pdf_bytes:
        body += f"<p>You can view it here: <a href=\"{file_url}\">{file_url}</a></p>"
    _send_email(email, subject, body, pdf_bytes=pdf_bytes, pdf_filename=f"{template_name}.pdf" if pdf_bytes else None)
