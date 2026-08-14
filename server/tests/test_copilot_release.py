"""
Co-pilot APK release pipeline — upload, publish, distribute, self-update.

This path was silently broken in production: every real release APK was
refused, and on the rare small one the public link handed the user the SPA's
index.html instead of a file. Three separate causes, so the tests below pin
each one independently rather than asserting "it works" once.

The self-update contract matters as much as the upload: the Android app decides
whether to prompt, force, or stay quiet by comparing its own version code to
`latest_version_code` and `min_supported_version_code`. Getting those wrong
either strands devices on an old build or nags everyone on every launch.
"""

import io
import uuid

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import CopilotAppRelease, SystemAdmin, User
from services.storage_service import UPLOAD_PROFILES, validate_upload
from utils import ApiError


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clean_uploaded_apks(app):
    """
    Remove APKs these tests write to disk.

    The db_session fixture rolls the database back, but nothing rolls back the
    filesystem — and these uploads are deliberately forced to local disk. Left
    alone, every run would leave another handful of files behind for good.
    Only files this test module created are removed: the directory is compared
    before and after.
    """
    import os

    uploads = os.path.join(app.root_path, "uploads", "copilot", "apks")
    before = set(os.listdir(uploads)) if os.path.isdir(uploads) else set()
    yield
    if not os.path.isdir(uploads):
        return
    for name in set(os.listdir(uploads)) - before:
        try:
            os.remove(os.path.join(uploads, name))
        except OSError:
            pass


@pytest.fixture()
def admin(app, db_session):
    s = db_session
    n = _uniq()
    user = User(
        email=f"apk-admin-{n}@test.sahilpay", phone=f"2545{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="system_admin", is_verified=True, is_active=True,
        totp_enabled=True,          # admin routes stay shut until 2FA is on
    )
    s.add(user)
    s.flush()
    s.add(SystemAdmin(user_id=user.id))
    s.flush()
    with app.app_context():
        token = create_access_token(identity=str(user.id),
                                    additional_claims={"role": "system_admin"})
    return {"user": user, "token": token}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _next_code() -> int:
    """
    A version code guaranteed free.

    These tests exercise real endpoints, which COMMIT — so rows survive the
    fixture rollback and accumulate across runs. Random codes in a small range
    eventually collide with a previous run's row and the endpoint (correctly)
    refuses the duplicate, failing a test for a reason that has nothing to do
    with what it is checking. Reading the current maximum sidesteps that.
    """
    from sqlalchemy import func

    current = db.session.query(func.max(CopilotAppRelease.version_code)).scalar()
    return int(current or 0) + 1


def _apk(size_mb: float = 0.05, name: str = "copilot.apk"):
    """A stand-in APK. Content is irrelevant — nothing parses it."""
    return (io.BytesIO(b"PK\x03\x04" + b"x" * int(size_mb * 1024 * 1024)), name)


# ---------------------------------------------------------------------------
# Upload policy — cause #1 of the production failure
# ---------------------------------------------------------------------------

def test_a_realistic_release_apk_is_accepted(app):
    """
    The original bug: a single 20MB ceiling applied to every upload, so any
    real release was refused with "File is too large". Release APKs are
    routinely 30-60MB.
    """
    with app.app_context():
        for mb in (5, 30, 60, 99):
            validate_upload(b"x" * (mb * 1024 * 1024), "copilot.apk", "apk")


def test_the_apk_ceiling_is_not_unlimited(app):
    with app.app_context():
        with pytest.raises(ApiError):
            validate_upload(b"x" * (101 * 1024 * 1024), "copilot.apk", "apk")


def test_the_apk_profile_accepts_nothing_but_apk(app):
    """
    Widening the shared "any" profile would have fixed the upload and opened a
    100MB hole for every other caller. The allowance is confined to this
    profile, so prove it refuses everything else.
    """
    with app.app_context():
        for name in ("payload.html", "shell.php", "photo.png", "book.pdf", "noext"):
            with pytest.raises(ApiError):
                validate_upload(b"x" * 1024, name, "apk")


def test_other_profiles_did_not_inherit_the_larger_ceiling(app):
    """Raising MAX_UPLOAD_BYTES must not silently raise everyone's limit."""
    with app.app_context():
        with pytest.raises(ApiError):
            validate_upload(b"x" * (11 * 1024 * 1024), "scan.pdf", "document")
        with pytest.raises(ApiError):
            validate_upload(b"x" * (6 * 1024 * 1024), "logo.png", "image")
        with pytest.raises(ApiError):
            validate_upload(b"x" * (21 * 1024 * 1024), "anything.pdf", "any")
    assert UPLOAD_PROFILES["any"]["max"] == 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------

def test_admin_can_upload_a_release(client, db_session, admin):
    code = _next_code()
    res = client.post(
        "/api/admin/copilot/releases",
        headers=_auth(admin["token"]),
        data={
            "file": _apk(),
            "version_name": "1.4.0",
            "version_code": str(code),
            "release_notes": "Faster matching.",
            "is_latest": "true",
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 201, res.get_data(as_text=True)
    body = res.get_json()
    assert body["version_name"] == "1.4.0"
    assert body["is_latest"] is True
    assert body["apk_path"]


def test_duplicate_version_code_is_refused(client, db_session, admin):
    code = str(_next_code())
    common = {"version_name": "1.0.0", "version_code": code, "is_latest": "false"}
    first = client.post("/api/admin/copilot/releases", headers=_auth(admin["token"]),
                        data={"file": _apk(), **common},
                        content_type="multipart/form-data")
    assert first.status_code == 201, first.get_data(as_text=True)

    second = client.post("/api/admin/copilot/releases", headers=_auth(admin["token"]),
                         data={"file": _apk(), **common},
                         content_type="multipart/form-data")
    assert second.status_code == 400
    assert "already exists" in second.get_json()["error"]


def test_marking_latest_demotes_the_previous_latest(client, db_session, admin):
    """Two rows flagged latest would make the public link non-deterministic."""
    base = _next_code()
    for i, name in enumerate(["1.0.0", "1.1.0"]):
        res = client.post("/api/admin/copilot/releases", headers=_auth(admin["token"]),
                          data={"file": _apk(), "version_name": name,
                                "version_code": str(base + i), "is_latest": "true"},
                          content_type="multipart/form-data")
        assert res.status_code == 201, res.get_data(as_text=True)

    latest = db_session.query(CopilotAppRelease).filter_by(is_latest=True).all()
    assert len(latest) == 1
    assert latest[0].version_name == "1.1.0"


def test_upload_is_closed_to_non_admins(client):
    res = client.post("/api/admin/copilot/releases",
                      data={"file": _apk(), "version_name": "9.9.9",
                            "version_code": "99999"},
                      content_type="multipart/form-data")
    assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Distribution — cause #2/#3 of the production failure
# ---------------------------------------------------------------------------

def test_the_public_link_returns_the_apk_itself(client, db_session, admin):
    """
    The link clients are given. It must return the binary with the Android
    package MIME type and a sensible download name — NOT a redirect that a
    misconfigured proxy answers with index.html, which is what shipped.
    """
    code = _next_code()
    up = client.post("/api/admin/copilot/releases", headers=_auth(admin["token"]),
                     data={"file": _apk(), "version_name": "2.0.1",
                           "version_code": str(code), "is_latest": "true"},
                     content_type="multipart/form-data")
    assert up.status_code == 201, up.get_data(as_text=True)

    res = client.get("/api/copilot/app/download")
    assert res.status_code == 200, res.get_data(as_text=True)[:300]
    assert res.mimetype == "application/vnd.android.package-archive"
    disposition = res.headers.get("Content-Disposition", "")
    assert "attachment" in disposition
    # Named for humans, not for the collision-avoiding storage key.
    assert "sahilpay-copilot-2.0.1.apk" in disposition
    assert res.data.startswith(b"PK\x03\x04")


def test_the_public_link_needs_no_authentication(client, db_session, admin):
    """It is shared by WhatsApp with caretakers who have no SahilPay login."""
    code = _next_code()
    client.post("/api/admin/copilot/releases", headers=_auth(admin["token"]),
                data={"file": _apk(), "version_name": "2.1.0",
                      "version_code": str(code), "is_latest": "true"},
                content_type="multipart/form-data")

    res = client.get("/api/copilot/app/download")   # no Authorization header
    assert res.status_code == 200


def test_download_is_404_when_nothing_is_published(client, db_session):
    """A release uploaded but never marked latest must not be served."""
    db_session.query(CopilotAppRelease).update({"is_latest": False})
    db_session.flush()
    res = client.get("/api/copilot/app/download")
    assert res.status_code == 404


def test_a_missing_file_reports_clearly_instead_of_500(client, db_session):
    """Restored database, wiped disk — a public link must not throw."""
    db_session.query(CopilotAppRelease).update({"is_latest": False})
    db_session.add(CopilotAppRelease(
        version_name="3.0.0", version_code=_next_code(),
        apk_path="/uploads/copilot/apks/deadbeef_gone.apk", is_latest=True,
    ))
    db_session.flush()

    res = client.get("/api/copilot/app/download")
    assert res.status_code == 404
    assert "missing from storage" in res.get_json()["error"]


# ---------------------------------------------------------------------------
# Self-update contract
# ---------------------------------------------------------------------------

def test_version_check_payload_drives_the_update_prompt(client, db_session, admin):
    """
    What the app polls to decide: stay quiet, offer an update, or force one.
    Both codes must be present or the app cannot tell those apart.
    """
    code = _next_code()
    res = client.post("/api/admin/copilot/releases", headers=_auth(admin["token"]),
                      data={"file": _apk(), "version_name": "4.0.0",
                            "version_code": str(code),
                            "min_supported_version_code": str(code - 10),
                            "is_latest": "true"},
                      content_type="multipart/form-data")
    assert res.status_code == 201, res.get_data(as_text=True)

    latest = client.get("/api/copilot/app/latest")
    assert latest.status_code == 200
    body = latest.get_json()
    assert body["version_code"] == code
    assert body["min_supported_version_code"] == code - 10
    assert body["version_name"] == "4.0.0"


def test_version_check_is_public(client):
    """Checked before the device has paired, so it cannot require a token."""
    res = client.get("/api/copilot/app/latest")
    assert res.status_code in (200, 404)     # 404 only when nothing is published
