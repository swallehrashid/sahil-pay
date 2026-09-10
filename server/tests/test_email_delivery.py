"""
How mail leaves the building — the Resend envelope, not the copy inside it.

Everything this app emails is a one-shot credential: a verification link, a
password reset, a team invitation, a receipt. Under SendGrid the payload
carried an explicit `tracking_settings` block turning link rewriting off,
because the ACCOUNT default had it ON — and a rewritten href through an
unauthenticated tracking host is a dead link the recipient cannot get past.

Resend has no per-message tracking override. The setting lives on the DOMAIN,
which means the code cannot pin it and these tests cannot assert it from a
payload. So the guarantee is split in two:

  * the payload tests below prove the links we BUILD are real destinations on
    our own domain, and that nothing in our own templates points at a tracker;
  * test_resend_domain_tracking_is_off (network-marked, skipped by default)
    reads the live domain settings back from Resend, so a dashboard toggle is
    caught by a deploy check rather than by a locked-out user.

The regression this all exists to prevent is documented at the bottom.
"""

import json
import os
import re
from unittest.mock import patch

import pytest

from services import email_service as es


class _FakeResponse:
    def __init__(self, body=b'{"id":"test-message-id"}'):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# Which Flask app a send actually reads its config from
# ------------------------------------------------------
# Every public function in email_service is a Celery task, and celery_app's
# _ContextTask.__call__ does `from app import app` and pushes THAT context —
# the module-level singleton, not the one tests/conftest.py builds. So setting
# config on the `app` fixture alone has no effect on a task body: it reads the
# real .env instead.
#
# That is not hypothetical. The SendGrid version of this suite set
# SENDGRID_API_KEY and COMMS_SIMULATION_MODE on the fixture app and passed
# anyway — because the developer's .env happened to carry a live key with
# simulation off. On a machine without those it would have asserted nothing.
# Configure both apps so a test means what it says.
_EMAIL_CONFIG_KEYS = ("COMMS_SIMULATION_MODE", "RESEND_API_KEY", "EMAIL_TEST_ALLOWLIST")


def _apps_under_test(fixture_app):
    from app import app as task_app

    return [a for a in dict.fromkeys([fixture_app, task_app]) if a is not None]


@pytest.fixture()
def email_config(app):
    """Set email config on every app a send might read, and restore it after."""
    apps = _apps_under_test(app)
    saved = [{k: a.config.get(k) for k in _EMAIL_CONFIG_KEYS} for a in apps]

    def configure(**values):
        for a in apps:
            a.config.update(values)

    configure(COMMS_SIMULATION_MODE=False, RESEND_API_KEY="re_test-key",
              EMAIL_TEST_ALLOWLIST="")
    try:
        yield configure
    finally:
        for a, previous in zip(apps, saved):
            a.config.update(previous)


@pytest.fixture()
def sent(app, email_config):
    """
    Capture the exact JSON body posted to Resend, with simulation mode off, the
    allowlist cleared and a stub API key, so the real send path runs.
    """
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["payload"] = json.loads(request.data.decode())
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return _FakeResponse()

    with app.app_context():
        with patch.object(es.urllib.request, "urlopen", fake_urlopen):
            yield captured


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------

def test_it_posts_to_resend(sent):
    """The transport actually changed — this fails if SendGrid comes back."""
    es.send_verification_email("someone@example.test", "tok-abc")

    assert sent["url"] == "https://api.resend.com/emails"
    assert "sendgrid" not in sent["url"]


def test_a_custom_user_agent_is_sent(sent):
    """
    Resend is behind Cloudflare, which bans stdlib urllib's default
    `Python-urllib/3.x` User-Agent with 403 / error code 1010 before the request
    reaches Resend at all. Because _send_email swallows errors by design, that
    failure is SILENT: every email in production would vanish with nothing to
    show for it but an unread 403.

    Verified against the live API — the same request succeeds with this header
    and 403s without it.
    """
    es.send_verification_email("someone@example.test", "tok-abc")

    headers = {k.lower(): v for k, v in sent["headers"].items()}
    agent = headers.get("User-agent".lower(), "")
    assert agent, "no User-Agent header — Cloudflare will 403 every send"
    assert "python-urllib" not in agent.lower(), \
        f"the banned default User-Agent is being sent: {agent}"


def test_the_from_header_uses_resend_display_name_form(sent):
    """
    Resend takes a single RFC 5322 string, not SendGrid's {"email", "name"}
    object. Sending the old shape is accepted as a literal address and produces
    mail from a nonsense sender.
    """
    es.send_verification_email("someone@example.test", "tok-abc")

    sender = sent["payload"]["from"]
    # The shape, not a hard-coded display name — MAIL_DEFAULT_SENDER_NAME is
    # deployment config, and pinning its current value here would make this
    # test fail on a rename that is not a bug.
    assert re.fullmatch(r".+ <[^<>@\s]+@sahilpay\.co\.ke>", sender), sender
    assert not sender.startswith("<"), "display name is missing"
    assert sent["payload"]["to"] == ["someone@example.test"]


def test_every_email_carries_a_plain_text_alternative(sent):
    """
    HTML-only mail scores worse at Gmail and Outlook, and this is the one place
    that can fix it for every template at once. A body that is present but
    empty is the failure mode worth pinning.
    """
    es.send_verification_email("someone@example.test", "tok-abc")

    text = sent["payload"]["text"]
    assert text.strip(), "no text/plain alternative"
    assert "<" not in text, "the text part still contains markup"
    # The actionable thing in the mail must survive into the text part.
    assert "/verify-email/tok-abc" in text


def test_a_reply_to_is_offered(sent):
    """The From is no-reply; a domain that accepts no reply anywhere reads as
    unattended bulk mail."""
    es.send_verification_email("someone@example.test", "tok-abc")

    assert sent["payload"]["reply_to"] == "hello@sahilpay.co.ke"


def test_an_attachment_uses_resends_field_names(sent):
    """
    Resend names it `content_type`; SendGrid named it `type` and also wanted a
    `disposition`. Sending the SendGrid shape silently produces an attachment
    with the wrong MIME type, which mail clients then refuse to open.
    """
    es.send_receipt_email("t@example.test", "Jane", b"%PDF-1.4 fake", "RCP-001")

    attachment = sent["payload"]["attachments"][0]
    assert attachment["content_type"] == "application/pdf"
    assert attachment["filename"] == "RCP-001.pdf"
    assert attachment["content"], "attachment body is empty"


# ---------------------------------------------------------------------------
# The links — unchanged in intent from the SendGrid suite
# ---------------------------------------------------------------------------

def test_the_link_in_the_body_is_the_real_destination(sent):
    """
    A verification link must point at the app itself. Someone checking that a
    login link goes to sahilpay.co.ke before clicking is doing exactly the right
    thing, and an opaque redirect defeats it.
    """
    es.send_verification_email("someone@example.test", "tok-abc")

    body = sent["payload"]["html"]
    assert "/verify-email/tok-abc" in body
    assert "sendgrid.net" not in body
    assert "resend" not in body.lower()


def test_an_invitation_link_points_at_our_own_domain(sent):
    """
    The exact regression: the href a team member clicks must be a real Sahil Pay
    URL, not a tracking host that has to resolve separately.
    """
    es.send_team_credentials_email("newcolleague@example.test", "jdoe", "TempPw1!",
                                   verification_token="tok-123")

    hrefs = re.findall(r'href="([^"]+)"', sent["payload"]["html"])
    assert hrefs, "the invitation has no link at all"
    for href in hrefs:
        # urlNNNN.sahilpay.co.ke is the shape that broke.
        assert not re.match(r"https?://url\d+\.", href), f"tracking-rewritten link: {href}"
        assert "sendgrid.net" not in href
        assert "ct.sendgrid" not in href
    assert any("/verify-email/tok-123" in h for h in hrefs), \
        "the invitation must link somewhere that actually signs the person in"


def test_a_document_link_is_absolute(sent):
    """
    Uploaded files are stored with RELATIVE urls ("/uploads/leases/1/a.pdf"),
    which is right for the app and useless in an email: a mail client has no
    base URL, so the link either does nothing or resolves against the webmail
    provider's own domain. Same visible symptom as the tracking rewrite, an
    entirely different cause.
    """
    es.send_document_email("t@example.test", "Jane", "Tenancy Agreement",
                           None, "/uploads/leases/1/agreement.pdf")

    hrefs = re.findall(r'href="([^"]+)"', sent["payload"]["html"])
    assert hrefs, "the email offers no way to reach the document"
    for href in hrefs:
        assert href.startswith("http"), f"relative link in an email: {href}"


# ---------------------------------------------------------------------------
# The guards that stop mail reaching people it shouldn't
# ---------------------------------------------------------------------------

def test_simulation_mode_still_suppresses_the_send(app, email_config):
    """
    The guard that stops a non-production environment carrying a real API key
    from emailing real people must not have been weakened by the provider swap.
    """
    email_config(COMMS_SIMULATION_MODE=True)
    with app.app_context():
        def explode(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("attempted a real send in simulation mode")

        with patch.object(es.urllib.request, "urlopen", explode):
            assert es._send_email("a@example.test", "subject", "<p>body</p>") is False


def test_the_allowlist_blocks_everyone_not_on_it(app, email_config):
    """
    The dev database holds ~1,000 seeded tenants with real-looking addresses.
    With COMMS_SIMULATION_MODE off — which is exactly the state needed to prove
    a flow by hand — one bulk action would mail all of them.
    """
    email_config(EMAIL_TEST_ALLOWLIST="me@example.test")
    with app.app_context():
        def explode(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("sent to an address outside the allowlist")

        with patch.object(es.urllib.request, "urlopen", explode):
            assert es._send_email("stranger@example.test", "s", "<p>b</p>") is False


def test_the_allowlist_lets_the_listed_address_through(app, email_config):
    """The valve must not be a blanket off switch — the listed address still
    receives, or nobody can verify anything."""
    email_config(EMAIL_TEST_ALLOWLIST="me@example.test, other@example.test")
    with app.app_context():
        with patch.object(es.urllib.request, "urlopen", lambda *a, **k: _FakeResponse()):
            assert es._send_email("ME@example.test", "s", "<p>b</p>") is True


def test_an_empty_allowlist_is_inert(app, email_config):
    """This is the PRODUCTION state. A blank value must never suppress mail."""
    email_config(EMAIL_TEST_ALLOWLIST="   ")
    with app.app_context():
        with patch.object(es.urllib.request, "urlopen", lambda *a, **k: _FakeResponse()):
            assert es._send_email("anyone@example.test", "s", "<p>b</p>") is True


def test_a_rejected_send_never_raises(app, email_config):
    """
    A failed email must never fail the request or task that triggered it —
    recording a payment must not 500 because the receipt could not go out.
    """
    with app.app_context():
        def reject(*a, **k):
            raise es.urllib.error.HTTPError(
                es.RESEND_URL, 422, "Unprocessable", {},
                __import__("io").BytesIO(b'{"message":"domain not verified"}'),
            )

        with patch.object(es.urllib.request, "urlopen", reject):
            assert es._send_email("a@example.test", "s", "<p>b</p>") is False


# ---------------------------------------------------------------------------
# The plain-text converter
# ---------------------------------------------------------------------------

def test_plain_text_keeps_the_url_a_reader_has_to_act_on():
    """A text-only reader cannot click anchor text — they need the bare URL."""
    text = es.plain_text_from_html(
        '<p>Hello</p><a href="https://sahilpay.co.ke/reset?token=x">Reset my password</a>'
    )
    assert "Reset my password" in text
    assert "https://sahilpay.co.ke/reset?token=x" in text
    assert "<" not in text


def test_plain_text_survives_an_empty_body():
    assert es.plain_text_from_html("") == ""
    assert es.plain_text_from_html(None) == ""


# ---------------------------------------------------------------------------
# Live domain check — the half the payload cannot prove
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("RESEND_LIVE_CHECK"),
    reason="hits the Resend API; set RESEND_LIVE_CHECK=1 to run (deploy check).",
)
def test_resend_domain_tracking_is_off(app):
    """
    Resend has no per-message tracking override, so this is the ONLY place the
    "links are never rewritten" guarantee can be verified. Run it as part of a
    deploy check: the failure it catches is invisible in our own logs, because
    as far as the API is concerned the send succeeded.
    """
    with app.app_context():
        app.config["RESEND_API_KEY"] = os.environ["RESEND_API_KEY"]
        result = es.assert_tracking_disabled()

    assert result["error"] is None, result["error"]
    assert result["domains"], "no sending domain is configured in Resend"
    for domain in result["domains"]:
        assert domain["status"] == "verified", f"{domain['name']} is {domain['status']}"
        assert domain["click_tracking"] is False, \
            f"click tracking is ON for {domain['name']} — every credential link is being rewritten"
        assert domain["open_tracking"] is False, \
            f"open tracking is ON for {domain['name']} — a remote pixel in every receipt"
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# The failure this suite actually exists because of
# ---------------------------------------------------------------------------
# A team member clicked "Log in to Sahil Pay" in their invitation and got:
#
#     url5446.sahilpay.co.ke
#     DNS_PROBE_FINISHED_NXDOMAIN
#
# That hostname is not ours. SendGrid's click tracking had rewritten the link
# onto a branded tracking subdomain (urlNNNN.<domain>) whose CNAME was never
# created, so every link in every email resolved to nothing. The app was fine;
# the links never reached it.
#
# Two things make this hard to catch by eye: the send succeeds as far as our
# logs are concerned, and the rewritten host still ends in sahilpay.co.ke, so it
# looks plausible in a screenshot.
#
# Resend does not do this by default and the domain has tracking off, but it is
# one dashboard toggle away from happening again — hence the live check above.
