"""
How mail leaves the building — the SendGrid envelope, not the copy inside it.

Everything this app emails is a one-shot credential: a verification link, a
password reset, a team invitation, a receipt. The payload previously carried no
`tracking_settings`, which means SendGrid applied the ACCOUNT default — and with
click tracking on, every href is rewritten into a ct.sendgrid.net redirect
before it reaches the recipient.

That is the difference between "here is your login link" and "here is an opaque
redirect through a third-party domain". If the tracking domain is not
authenticated, or the redirect is stripped or flagged, the link is dead and the
person cannot get into their account — with nothing in our logs to show for it,
because as far as SendGrid is concerned the send succeeded.

These tests assert the envelope, so the behaviour cannot regress by someone
changing an account-level toggle in a dashboard we do not control.
"""

import json
from unittest.mock import patch

import pytest

from services import email_service as es


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def sent(app):
    """
    Capture the exact JSON body posted to SendGrid, with simulation mode off
    and a stub API key so the real send path runs.
    """
    captured = {}

    with app.app_context():
        previous = (
            app.config.get("COMMS_SIMULATION_MODE"),
            app.config.get("SENDGRID_API_KEY"),
        )
        app.config["COMMS_SIMULATION_MODE"] = False
        app.config["SENDGRID_API_KEY"] = "SG.test-key"

        def fake_urlopen(request, timeout=None):
            captured["payload"] = json.loads(request.data.decode())
            captured["url"] = request.full_url
            return _FakeResponse()

        try:
            with patch.object(es.urllib.request, "urlopen", fake_urlopen):
                yield captured
        finally:
            app.config["COMMS_SIMULATION_MODE"] = previous[0]
            app.config["SENDGRID_API_KEY"] = previous[1]


def test_click_tracking_is_explicitly_disabled(sent):
    """
    The whole point: SendGrid must be told NOT to rewrite hrefs, rather than
    left to apply whatever the account dashboard happens to be set to.
    """
    es.send_verification_email("someone@example.test", "tok-abc")

    tracking = sent["payload"]["tracking_settings"]
    assert tracking["click_tracking"]["enable"] is False
    assert tracking["click_tracking"]["enable_text"] is False


def test_open_tracking_is_disabled(sent):
    """No remote pixel in a receipt — it triggers "images blocked" on mail
    that should look plain and legitimate."""
    es.send_verification_email("someone@example.test", "tok-abc")

    assert sent["payload"]["tracking_settings"]["open_tracking"]["enable"] is False


def test_the_link_in_the_body_is_the_real_destination(sent):
    """
    A verification link must point at the app itself. Someone checking that a
    login link goes to sahilpay.co.ke before clicking is doing exactly the right
    thing, and an opaque redirect defeats it.
    """
    es.send_verification_email("someone@example.test", "tok-abc")

    body = sent["payload"]["content"][0]["value"]
    assert "/verify-email/tok-abc" in body
    assert "sendgrid.net" not in body


@pytest.mark.parametrize(
    "send, args",
    [
        (es.send_verification_email, ("a@example.test", "tok")),
        (es.send_password_reset_email, ("a@example.test", "tok")),
        (es.send_team_credentials_email, ("a@example.test", "user", "TempPw1!")),
    ],
)
def test_every_credential_email_disables_tracking(sent, send, args):
    """One shared envelope, so this holds for all of them — pin it anyway,
    because a future template that builds its own payload would not."""
    send(*args)

    assert sent["payload"]["tracking_settings"]["click_tracking"]["enable"] is False


def test_simulation_mode_still_suppresses_the_send(app):
    """
    The guard that stops a non-production environment carrying a real API key
    from emailing real people must not have been weakened by any of this.
    """
    with app.app_context():
        previous = app.config.get("COMMS_SIMULATION_MODE")
        app.config["COMMS_SIMULATION_MODE"] = True
        try:
            def explode(*a, **k):  # pragma: no cover - must never run
                raise AssertionError("attempted a real send in simulation mode")

            with patch.object(es.urllib.request, "urlopen", explode):
                assert es._send_email("a@example.test", "subject", "<p>body</p>") is False
        finally:
            app.config["COMMS_SIMULATION_MODE"] = previous
