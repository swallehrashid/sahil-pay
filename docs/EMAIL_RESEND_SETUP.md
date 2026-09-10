# Sahil Pay — Email / Resend Setup

Transactional email runs on **Resend**. SendGrid was removed entirely on
2026-09-09 (its free-tier limits were the reason); there is no fallback path and
no `SENDGRID_API_KEY` anywhere in the codebase.

Everything in this document was verified against the live account and the live
DNS on 2026-09-09, not copied from a dashboard screenshot.

---

## 1. Current state — all verified

| Check | Result |
|---|---|
| Resend domain `sahilpay.co.ke` | **verified**, sending enabled, region `eu-west-1` |
| `resend._domainkey.sahilpay.co.ke` TXT | **live** — DKIM, signs `d=sahilpay.co.ke` |
| `send.sahilpay.co.ke` TXT | **live** — `v=spf1 include:amazonses.com ~all` (the Return-Path) |
| `_dmarc.sahilpay.co.ke` TXT | **live** — `v=DMARC1; p=none;` |
| Click tracking (domain) | **OFF** |
| Open tracking (domain) | **OFF** |
| Test send to Gmail | `last_event: delivered` |

SPF and DKIM both align with the From domain under DMARC's relaxed alignment,
so **DMARC passes**. A DMARC record existing at all is what the Gmail and Yahoo
bulk-sender rules (February 2024) require, so that box is ticked too.

---

## 2. Why this mail stays out of spam

Five things do the work. Four carried over from the SendGrid setup; one is new.

### 2.1 Authenticated domain, aligned (carried over)
The From is `noreply@sahilpay.co.ke`. Resend signs with DKIM as
`d=sahilpay.co.ke` and sets the Return-Path on `send.sahilpay.co.ke`, which
carries its own SPF record. Both therefore align with the organisational domain
in the From, which is what DMARC checks. A message failing either is the single
biggest spam signal there is.

### 2.2 Click and open tracking OFF (carried over — and now load-bearing)
This is the one to be careful about.

Under SendGrid this was set **per message**, in a `tracking_settings` block, and
the code could guarantee it. **Resend has no per-message equivalent** — tracking
is a domain setting in the dashboard. It is currently off, and it must stay off.

Two reasons:

* Every link this app sends is a **one-shot credential** — a verification link,
  a password reset, a team invitation, a receipt link. Click tracking rewrites
  each `href` onto a tracking host. If that host is unauthenticated, stripped,
  or flagged as a phishing pattern, the recipient is locked out of their
  account and the send still looks successful in every log we have.
* It has already happened once. A team member clicked "Log in to Sahil Pay" in
  their invitation and got `url5446.sahilpay.co.ke` /
  `DNS_PROBE_FINISHED_NXDOMAIN` — SendGrid's click tracking had rewritten the
  link onto a branded subdomain whose CNAME was never created. Every link in
  every email pointed at nothing.

Because code can no longer enforce it, there is a check that reads the live
setting back:

```bash
cd server && source venv/bin/activate
RESEND_LIVE_CHECK=1 RESEND_API_KEY=re_xxx \
  python -m pytest tests/test_email_delivery.py -k tracking
```

**Run this after any change to the Resend account.** It fails if the domain is
unverified or either tracking toggle has been turned on.

### 2.3 A plain-text alternative on every message (NEW)
The SendGrid path sent HTML only. Every message now carries a `text/plain` part
generated from the HTML (`email_service.plain_text_from_html`). An HTML-only
body is one of the cheapest spam signals there is — Gmail and Outlook both
weight it — and this fixes it for every template at once.

### 2.4 A real Reply-To (NEW)
`reply_to` is set to `hello@sahilpay.co.ke`. The From stays no-reply, because
nobody should reply to an OTP, but a domain that accepts no reply anywhere
scores worse than one that offers a real address.

### 2.5 Only transactional mail goes through this path
No marketing, no bulk sends, no list mail. Every message is triggered by
something the recipient just did. That keeps complaint rates near zero, which
is what reputation is actually built on.

> **Not added, on purpose:** a `List-Unsubscribe` header. Gmail's bulk-sender
> rules require one-click unsubscribe for *promotional* mail only, and
> transactional mail is exempt. Offering to unsubscribe from a rent receipt or
> a password reset would be worse than not offering it.

---

## 3. Configuration

`server/.env` (and `deploy/server.env.production.example`):

```bash
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxx
MAIL_DEFAULT_SENDER=noreply@sahilpay.co.ke
MAIL_DEFAULT_SENDER_NAME=SahilPay

# MUST be false in production or nothing is actually sent.
COMMS_SIMULATION_MODE=false

# LEAVE BLANK IN PRODUCTION. See §4.
EMAIL_TEST_ALLOWLIST=
```

`RESEND_API_KEY` is required in production — `config.py::_validate` refuses to
boot without it. If it is absent outside production, emails are logged to the
console instead of sent, so nothing breaks while setting up.

---

## 4. `EMAIL_TEST_ALLOWLIST` — the non-production safety valve

The dev database is seeded with roughly a thousand tenants carrying
real-looking email addresses. Proving an email flow by hand requires
`COMMS_SIMULATION_MODE=false`, and in that state one bulk action would mail all
of them.

Set on a dev machine, only the listed addresses are delivered to; everything
else is logged with a warning and dropped:

```bash
EMAIL_TEST_ALLOWLIST=you@example.com,colleague@example.com
```

**It must be blank or absent in production.** Set there, it silently suppresses
live mail to every customer.

---

## 5. Verifying a deploy

```bash
cd server && source venv/bin/activate

# 1. The envelope, offline (16 tests, no network)
python -m pytest tests/test_email_delivery.py -q

# 2. The live domain posture — tracking off, domain verified
RESEND_LIVE_CHECK=1 RESEND_API_KEY=re_xxx \
  python -m pytest tests/test_email_delivery.py -k tracking

# 3. A real send through the real code path
python - <<'PY'
from app import app
from services import email_service as es
with app.app_context():
    print(es.assert_tracking_disabled())
    print(es._send_email("you@example.com", "Deploy check", "<p>Hello.</p>"))
PY
```

Then open the message and confirm it landed in **Inbox**, not Spam, and that
the link in it points at `sahilpay.co.ke` and not at any other host.

---

## 6. The trap that cost the most time

**Resend sits behind Cloudflare, and Cloudflare rejects Python's default
`urllib` User-Agent outright** — `403 Forbidden`, `error code: 1010`, a
browser-signature ban that happens before the request reaches Resend. The API
key is irrelevant; every call fails identically.

A straight port of the SendGrid code (same stdlib `urllib`, new URL) therefore
fails **100% of sends**. And because `_send_email` deliberately swallows errors
— a dead mailer must not fail the payment that triggered a receipt — it fails
**silently**: registrations never verify, resets never arrive, and the only
trace is a 403 in a log nobody is reading.

The fix is one header:

```python
USER_AGENT = "SahilPay/1.0 (+https://sahilpay.co.ke)"
```

It is sent on every request in `services/email_service.py` and pinned by
`test_a_custom_user_agent_is_sent`. **Do not remove it, and do not replace
`urllib` with anything that sets a default Python User-Agent.**

---

## 7. What each email is, and where it lives

| Capability | How it works | Where |
|------------|--------------|-------|
| **Tenant OTP by SMS *or* email** | The tenant types their **phone** → OTP via SMS, or their **email** → OTP via email. The channel is chosen by what they enter. | `routes/otp_routes.py`, `send_otp_email` |
| **Landlord email verification** | On signup a verification email is sent. Clicking the link sets `is_verified = true`. Required before login when `ENFORCE_EMAIL_VERIFICATION=true`. | `auth_routes.py::register / verify_email`, `send_verification_email` |
| **Team member onboarding** | Creating a team member generates a **temporary password** and emails them their email + username + temp password. They are forced to change it on first login. | `team_routes.py::create_team_member`, `send_team_credentials_email` |
| **Password reset (all roles)** | "Forgot password" emails a reset link that works for landlords, team members and tenants. | `auth_routes.py::forgot_password / reset_password`, `send_password_reset_email` |
| **Receipts, invoices, statements** | PDF attached, generated by the branded renderers. | `send_receipt_email`, `send_invoice_email`, `send_statement_email` |
| **Owner statements** | Sent by a property manager to the landlord who owns the block; the copy speaks as the management company. | `send_owner_statement_email` |
| **Documents** | Leases, tenancy agreements and deposit letters, as an attachment or an absolute link. | `send_document_email` |
| **Branded template** | One themed HTML template behind all of them. | `services/email_templates.py` |
| **Resend verification** | `POST /api/auth/resend-verification` re-issues the link. | `auth_routes.py` |

Every function above is a Celery task; routes call them with `.delay(...)`.

---

## 8. A note for whoever writes the next test here

`celery_app._ContextTask.__call__` does `from app import app` and pushes **that**
app's context — the module-level singleton, not the one `tests/conftest.py`
builds. Setting config on the `app` fixture alone therefore has no effect inside
a task body: it reads the real `.env` instead.

The SendGrid version of this suite did exactly that, and passed anyway, because
the developer's `.env` happened to carry a live key with simulation off. On a
machine without those it asserted nothing at all.

`tests/test_email_delivery.py` now has an `email_config` fixture that configures
every app a send might read from. Use it.
