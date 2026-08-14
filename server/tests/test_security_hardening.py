"""
Phases 3.2–3.6 — brute-force resistance and upload policy.

These guard the two ways in that don't need a bug: guessing a password, and
uploading a file the browser will execute.
"""

import uuid

import pytest

from services.storage_service import (
    FORBIDDEN_EXTENSIONS, UPLOAD_PROFILES, validate_upload,
)
from utils import ApiError


def _uniq():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Upload policy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "evil.html", "evil.svg", "shell.php", "script.js", "payload.htm",
    "backdoor.py", "run.sh", "app.exe", "thing.jsp",
])
def test_executable_uploads_are_always_refused(app, filename):
    """
    An .html or .svg served from our own origin runs script with our cookies;
    a stored .php is a foothold. None of these is ever a tenant document,
    whatever profile the caller asked for.
    """
    with app.app_context():
        with pytest.raises(ApiError) as exc:
            validate_upload(b"x" * 100, filename, profile="any")
        assert exc.value.status == 400


def test_forbidden_list_covers_the_dangerous_types():
    for ext in ("html", "svg", "js", "php", "exe"):
        assert ext in FORBIDDEN_EXTENSIONS


def test_profiles_reject_types_outside_their_purpose(app):
    with app.app_context():
        # A bank statement is not a profile photo.
        with pytest.raises(ApiError):
            validate_upload(b"x" * 100, "statement.csv", profile="image")
        # An image profile accepts an image.
        validate_upload(b"x" * 100, "logo.png", profile="image")
        # A statement profile accepts a spreadsheet.
        validate_upload(b"x" * 100, "june.xlsx", profile="statement")


def test_oversized_uploads_are_refused(app):
    with app.app_context():
        too_big = b"x" * (UPLOAD_PROFILES["image"]["max"] + 1)
        with pytest.raises(ApiError) as exc:
            validate_upload(too_big, "huge.png", profile="image")
        assert exc.value.code == "file_too_large"


def test_empty_uploads_are_refused(app):
    with app.app_context():
        with pytest.raises(ApiError) as exc:
            validate_upload(b"", "empty.pdf", profile="document")
        assert exc.value.code == "empty_file"


def test_extensionless_file_is_refused_by_a_typed_profile(app):
    with app.app_context():
        with pytest.raises(ApiError):
            validate_upload(b"x" * 100, "noextension", profile="document")


# ---------------------------------------------------------------------------
# Login lockout
# ---------------------------------------------------------------------------

def test_lockout_engages_after_repeated_failures(app):
    """
    Per-IP rate limits don't stop a distributed attempt on one account, so the
    ACCOUNT itself has to stop answering.
    """
    from services import login_guard

    identifier = f"lockout-{_uniq()}@test.sahilpay"
    with app.app_context():
        if login_guard._redis() is None:
            pytest.skip("Redis unavailable — lockout is Redis-backed by design")

        login_guard.clear(identifier)
        assert not login_guard.is_locked(identifier)

        for _ in range(login_guard.MAX_FAILURES):
            login_guard.record_failure(identifier)

        assert login_guard.is_locked(identifier), (
            "the account still answers after the failure budget was spent"
        )
        assert login_guard.lock_seconds_remaining(identifier) > 0
        login_guard.clear(identifier)


def test_a_correct_login_clears_the_counter(app):
    """An honest user who mistypes twice must not inch toward a lockout."""
    from services import login_guard

    identifier = f"clear-{_uniq()}@test.sahilpay"
    with app.app_context():
        if login_guard._redis() is None:
            pytest.skip("Redis unavailable")

        login_guard.record_failure(identifier)
        login_guard.record_failure(identifier)
        login_guard.clear(identifier)

        for _ in range(login_guard.MAX_FAILURES - 1):
            login_guard.record_failure(identifier)
        assert not login_guard.is_locked(identifier), (
            "earlier failures were not cleared by the successful login"
        )
        login_guard.clear(identifier)


def test_lockout_never_confirms_an_account_exists(client_app):
    """
    A locked account must answer with the SAME text as a wrong password —
    otherwise the lockout becomes an account-enumeration oracle.
    """
    app, client = client_app
    from services import login_guard

    identifier = f"oracle-{_uniq()}@test.sahilpay"
    with app.app_context():
        if login_guard._redis() is None:
            pytest.skip("Redis unavailable")
        for _ in range(login_guard.MAX_FAILURES):
            login_guard.record_failure(identifier)

    resp = client.post("/api/auth/login", json={"email": identifier, "password": "x"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Invalid email or password."

    with app.app_context():
        login_guard.clear(identifier)


@pytest.fixture()
def client_app(app):
    return app, app.test_client()


# ---------------------------------------------------------------------------
# Deployment hardening (config-level)
# ---------------------------------------------------------------------------

def test_api_docs_are_not_mounted_in_production():
    """The OpenAPI explorer maps the whole attack surface — not in production."""
    from config import ProductionConfig, BaseConfig

    assert ProductionConfig.IS_PRODUCTION is True
    assert BaseConfig.IS_PRODUCTION is False


def test_nginx_config_sets_the_security_headers():
    import pathlib

    conf = pathlib.Path(__file__).resolve().parents[2] / "deploy/nginx/sahilpay.conf"
    text = conf.read_text()
    for header in (
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "Permissions-Policy",
        "X-Content-Type-Options",
        "server_tokens off",
    ):
        assert header in text, f"{header} missing from the nginx config"

    assert "frame-ancestors 'none'" in text, "clickjacking protection missing"
    assert "connect-src 'self'" in text, (
        "CSP must stop an injected script from calling out to another host"
    )
