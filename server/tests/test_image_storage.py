"""
Image storage — optimisation, and the rules that keep Cloudinary's free tier
viable at this account's scale.

The free tier is 25 credits a month, where one credit is 1GB of storage OR 1GB
of delivery bandwidth OR 1,000 transformations, all from the same pool. With
~1,000 tenants, ~80 landlords and ~50 caretakers, the number that bites is
DELIVERY: an unoptimised 4MB phone photo served to a thousand portal sessions
is measured in terabytes.

So three properties are pinned here, because each one silently costs real money
if it regresses:

  * every image is shrunk BEFORE upload, so what is stored is what is served;
  * only images ever reach Cloudinary — statements, signed leases and the APK
    stay on the VPS, where bandwidth is not billed per gigabyte;
  * a Cloudinary outage falls back to local disk instead of failing the request
    the landlord was in the middle of.
"""

from io import BytesIO

import pytest
from PIL import Image

from services import storage_service
from services.storage_service import (
    CLOUD_IMAGE_PROFILES, IMAGE_RULES, UPLOAD_PROFILES, optimise_image,
    upload_to_s3, validate_upload,
)
from utils import ApiError


def _photo(width=4000, height=3000, fmt="JPEG", mode="RGB"):
    """A stand-in for a photo straight off a phone."""
    image = Image.new(mode, (width, height), (120, 90, 200))
    # Noise, so the encoder cannot compress it to nothing and flatter the test.
    for x in range(0, width, 5):
        for y in range(0, height, 61):
            image.putpixel((x, y), (x % 255, y % 255, 30))
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------

def test_a_phone_photo_is_shrunk_to_the_profile_budget(app):
    raw = _photo()
    with app.app_context():
        data, name, ctype = optimise_image(raw, "photo.jpg", "image")

    assert len(data) < len(raw)
    assert len(data) <= IMAGE_RULES["image"]["target_bytes"] * 1.2
    assert Image.open(BytesIO(data)).width <= IMAGE_RULES["image"]["max_width"]
    assert name.endswith(".jpg")
    assert ctype == "image/jpeg"


def test_logos_get_a_much_tighter_budget_than_photos(app):
    """
    A logo is re-rendered into every receipt and sits on portal pages seen by
    every tenant, so it is the one image whose delivery cost multiplies by the
    tenant count.
    """
    raw = _photo()
    with app.app_context():
        photo, _, _ = optimise_image(raw, "photo.jpg", "image")
        brand, _, _ = optimise_image(raw, "logo.png", "brand")

    assert len(brand) < len(photo)
    assert Image.open(BytesIO(brand)).width <= IMAGE_RULES["brand"]["max_width"]
    assert IMAGE_RULES["brand"]["max_width"] < IMAGE_RULES["image"]["max_width"]


def test_a_small_image_is_not_upscaled(app):
    """Shrinking is the job; enlarging would add bytes for no benefit."""
    raw = _photo(width=320, height=240)
    with app.app_context():
        data, _, _ = optimise_image(raw, "small.jpg", "image")
    assert Image.open(BytesIO(data)).width == 320


def test_transparency_is_flattened_onto_white_not_black(app):
    """
    A PNG logo with an alpha channel saved straight to JPEG goes black behind
    the mark. Landlords upload transparent PNG logos constantly.
    """
    image = Image.new("RGBA", (400, 400), (255, 0, 0, 0))     # fully transparent
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    with app.app_context():
        data, _, _ = optimise_image(buffer.getvalue(), "logo.png", "brand")

    corner = Image.open(BytesIO(data)).convert("RGB").getpixel((5, 5))
    assert all(channel > 200 for channel in corner), f"expected white, got {corner}"


def test_an_unreadable_file_is_passed_through_untouched(app):
    """
    A logo Pillow cannot parse must still upload. Blocking the settings page
    over a thumbnail is a worse outcome than storing the original.
    """
    junk = b"this is not an image"
    with app.app_context():
        data, name, _ = optimise_image(junk, "weird.jpg", "image")
    assert data == junk
    assert name == "weird.jpg"


# ---------------------------------------------------------------------------
# What may reach Cloudinary at all
# ---------------------------------------------------------------------------

def test_only_image_profiles_are_cloud_eligible():
    """
    Statements, signed leases and the APK must stay on the VPS. They are large,
    rarely viewed, and metered egress is the wrong shape for them.
    """
    assert CLOUD_IMAGE_PROFILES == frozenset({"image", "brand"})
    for profile in ("document", "statement", "lease", "apk", "any"):
        assert profile not in CLOUD_IMAGE_PROFILES
        assert profile in UPLOAD_PROFILES


def test_the_apk_never_goes_to_a_metered_cdn(app, monkeypatch):
    """The APK is one big file every device fetches on every release."""
    called = []
    monkeypatch.setattr(storage_service, "_upload_to_cloudinary",
                        lambda *a, **k: called.append(a) or "https://cdn/x.apk")

    with app.app_context():
        url = upload_to_s3(BytesIO(b"PK\x03\x04" + b"x" * 2048),
                           folder="copilot/apks", filename="app.apk",
                           profile="apk", force_local=True)
    assert called == []
    assert url.startswith("/uploads/")


def test_a_document_is_not_sent_to_cloudinary(app, monkeypatch):
    called = []
    monkeypatch.setattr(storage_service, "_upload_to_cloudinary",
                        lambda *a, **k: called.append(a) or "https://cdn/x.jpg")

    with app.app_context():
        upload_to_s3(BytesIO(b"%PDF-1.4 fake"), folder="documents/1",
                     filename="lease.pdf", profile="document")
    assert called == []


# ---------------------------------------------------------------------------
# Resilience and cost control
# ---------------------------------------------------------------------------

def test_a_cloudinary_outage_falls_back_to_local_disk(app, monkeypatch):
    """
    A third party being down must not stop a landlord saving their logo. The
    helper returns None on failure and the caller keeps the file locally.
    """
    monkeypatch.setattr(storage_service, "_cloudinary_configured", lambda: True)
    monkeypatch.setattr(storage_service, "_upload_to_cloudinary", lambda *a, **k: None)

    with app.app_context():
        url = upload_to_s3(BytesIO(_photo(800, 600)), folder="logos/1",
                           filename="logo.jpg", profile="brand")
    assert url.startswith("/uploads/")


def test_images_are_optimised_even_without_cloudinary(app, monkeypatch):
    """
    A deployment with no Cloudinary must still not store 4MB phone photos —
    the shrink happens before the destination is chosen.
    """
    monkeypatch.setattr(storage_service, "_cloudinary_configured", lambda: False)
    raw = _photo()

    with app.app_context():
        url = upload_to_s3(BytesIO(raw), folder="maintenance/1",
                           filename="photo.jpg", profile="image")

    import os
    from flask import current_app
    with app.app_context():
        path = os.path.join(current_app.root_path, url.lstrip("/"))
        stored = os.path.getsize(path)
        os.remove(path)

    assert stored < len(raw)
    assert stored <= IMAGE_RULES["image"]["target_bytes"] * 1.2


def test_what_is_uploaded_is_what_is_delivered(app, monkeypatch):
    """
    The bytes handed to Cloudinary are already the delivered size, which is what
    keeps transformation credits at zero — nothing is resized on the way out.
    """
    captured = {}

    def fake_upload(data, key, folder):
        captured["bytes"] = data
        return "https://res.cloudinary.com/x/image/upload/v1/sahilpay/a.jpg"

    monkeypatch.setattr(storage_service, "_cloudinary_configured", lambda: True)
    monkeypatch.setattr(storage_service, "_upload_to_cloudinary", fake_upload)

    with app.app_context():
        url = upload_to_s3(BytesIO(_photo()), folder="maintenance/1",
                           filename="photo.jpg", profile="image")

    assert len(captured["bytes"]) <= IMAGE_RULES["image"]["target_bytes"] * 1.2
    # No transformation segment: the path after /upload/ is the version marker.
    assert url.split("/upload/")[1].split("/")[0].startswith("v")


def test_oversized_images_are_still_refused_before_any_work(app):
    """The size cap runs first, so a 50MB upload never reaches Pillow."""
    with app.app_context():
        with pytest.raises(ApiError):
            validate_upload(b"x" * (6 * 1024 * 1024), "huge.jpg", "image")
        with pytest.raises(ApiError):
            validate_upload(b"x" * (6 * 1024 * 1024), "huge.jpg", "brand")


def test_the_test_suite_can_never_reach_the_real_cdn(app):
    """
    The developer .env carries live Cloudinary credentials and the account is on
    a metered free tier. A test that uploads an image must fall back to local
    disk rather than spending the month's credits and leaving orphaned assets
    behind — so the testing config blanks the credentials outright.

    Asserted here rather than trusted, because the failure is silent: the suite
    would pass either way and the cost would only show up on the dashboard.
    """
    with app.app_context():
        assert storage_service._cloudinary_configured() is False
