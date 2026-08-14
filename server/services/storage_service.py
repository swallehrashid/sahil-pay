"""
SahilPay — services/storage_service.py
=========================================
File uploads (documents, receipts, expense/maintenance photos, logos,
signatures, bank statements). Every route in routes/*.py calls the single
upload_to_s3() function below regardless of file type.

Real AWS S3 upload when S3_BUCKET + AWS credentials are configured (see
config.py). Otherwise falls back to writing into server/uploads/ on local
disk and returning a URL served by the /uploads/<path> route registered in
app.py — so uploads still work end-to-end while testing without AWS creds.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from io import BytesIO

from flask import current_app

from utils import ApiError

logger = logging.getLogger(__name__)

_UPLOADS_DIR_NAME = "uploads"


def _sanitize_filename(name: str) -> str:
    name = os.path.basename(name or "upload")
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return name or "upload"


def _read_file_bytes(file_obj, filename: str | None, content_type: str | None):
    """Normalize a Werkzeug FileStorage, BytesIO, or raw bytes into (bytes, filename, content_type)."""
    if hasattr(file_obj, "filename") and hasattr(file_obj, "stream"):
        # werkzeug.datastructures.FileStorage (request.files[...])
        data = file_obj.stream.read()
        resolved_name = filename or file_obj.filename or "upload"
        resolved_type = content_type or file_obj.mimetype or "application/octet-stream"
    elif isinstance(file_obj, (bytes, bytearray)):
        data = bytes(file_obj)
        resolved_name = filename or "upload"
        resolved_type = content_type or "application/octet-stream"
    elif hasattr(file_obj, "read"):
        # BytesIO or any file-like object
        data = file_obj.read()
        resolved_name = filename or "upload"
        resolved_type = content_type or "application/octet-stream"
    else:
        raise ApiError("Unsupported file type for upload.", status=400, code="invalid_upload")

    return data, _sanitize_filename(resolved_name), resolved_type


# --- Upload policy -----------------------------------------------------------
# An allowlist, not a blocklist: anything not named here is refused. The risk
# being closed is a file that a browser will EXECUTE — an .html or .svg served
# from our own origin runs script with our cookies, and a stored .php or .py is
# a foothold if the storage directory is ever served by an interpreter.
#
# Sizes are in bytes and are enforced after reading, because a client-supplied
# Content-Length cannot be trusted.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024       # absolute ceiling, no profile exceeds it

UPLOAD_PROFILES: dict[str, dict] = {
    # profile      allowed extensions                     max bytes
    "image":     {"ext": {"png", "jpg", "jpeg", "webp"},   "max": 5 * 1024 * 1024},
    "document":  {"ext": {"pdf", "png", "jpg", "jpeg", "webp"}, "max": 10 * 1024 * 1024},
    "statement": {"ext": {"pdf", "csv", "xls", "xlsx"},    "max": 20 * 1024 * 1024},
    # A signed lease scanned on a phone: one PDF, or a page image.
    "lease":     {"ext": {"pdf", "png", "jpg", "jpeg", "webp"}, "max": 20 * 1024 * 1024},
    # Logos and signatures. Same file types as "image", but they are re-rendered
    # into every receipt and statement and appear on portal pages, so they are
    # optimised far harder — see IMAGE_RULES.
    "brand":     {"ext": {"png", "jpg", "jpeg", "webp"},   "max": 5 * 1024 * 1024},
    # The Co-pilot Android build. Deliberately its OWN profile rather than
    # widening "any": only .apk is accepted here, and the large ceiling applies
    # to nothing else. Release APKs routinely exceed 20MB, which is why the
    # shared ceiling used to reject every upload attempt.
    "apk":       {"ext": {"apk"},                          "max": 100 * 1024 * 1024},
    # The default stays deliberately tight — raising the absolute ceiling above
    # must not silently raise the limit for callers that never asked for it.
    "any":       {"ext": None,                             "max": 20 * 1024 * 1024},
}

# Never stored, whatever the profile: these are executable in some context.
# `apk` is absent on purpose — it is not executable by a browser, it is only
# ever served as a download, and it is confined to the "apk" profile above.
FORBIDDEN_EXTENSIONS = {
    "html", "htm", "xhtml", "svg", "js", "mjs", "php", "phtml", "py", "rb",
    "sh", "bash", "exe", "dll", "bat", "cmd", "com", "jar", "war", "cgi",
    "pl", "asp", "aspx", "jsp", "htaccess",
}


# --- Image optimisation & Cloudinary --------------------------------------
#
# WHY THIS IS AGGRESSIVE
# ----------------------
# Cloudinary's free tier is 25 credits a month, where ONE credit is 1GB of
# storage OR 1GB of delivery bandwidth OR 1,000 transformations — all drawn
# from the same 25. This account carries ~1,000 tenants, ~80 landlords and
# ~50 caretakers, so the arithmetic that matters is delivery, not storage:
# a 2MB phone photo served to a thousand portal sessions is 2TB of nonsense.
#
# Three rules keep it inside the free tier at that scale:
#
#   1. EVERY image is downscaled and recompressed HERE, before it is uploaded.
#      What lands on Cloudinary is already the size it will be served at, so
#      storage and bandwidth are both bounded at the source.
#   2. NO transformation URLs are ever generated. A `w_400,f_auto` in a
#      delivery URL creates a derived asset and bills a transformation. We
#      serve the plain secure_url, so transformations stay at zero.
#   3. Only IMAGES go to Cloudinary. PDFs, bank statements, signed leases and
#      the Co-pilot APK stay on the VPS, where bandwidth is not metered per GB.
#      Tutorial screenshots also stay local: they are read by every tenant, and
#      the CDN in front of the VPS serves them for nothing.
#
# Budget at the numbers above: roughly 0.2GB of logos and signatures, a few
# hundred MB a year of maintenance photos, and delivery measured in single-digit
# GB per month. Comfortably inside 25 credits, with the headroom coming from
# rule 1 rather than from hoping.

IMAGE_RULES: dict[str, dict] = {
    # Maintenance photos, property pictures — a person needs to see detail.
    "image": {"max_width": 1600, "target_bytes": 300 * 1024},
    # Logos and signatures are re-rendered into every receipt and statement and
    # sit on portal pages seen by every tenant, so they get the tightest budget.
    "brand": {"max_width": 600, "target_bytes": 80 * 1024},
}

# Profiles whose uploads are eligible for Cloudinary. Everything else is local.
CLOUD_IMAGE_PROFILES = frozenset(IMAGE_RULES)


def _extension_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def optimise_image(data: bytes, safe_name: str, profile: str) -> tuple[bytes, str, str]:
    """
    Downscale and recompress an image to the profile's budget.

    Returns (bytes, filename, content_type). Always JPEG: it is universally
    supported and predictably small, and these are photographs and logos rather
    than screenshots with flat colour.

    On any failure the ORIGINAL bytes are returned unchanged — a logo that
    Pillow cannot read must still upload rather than blocking the landlord from
    finishing their settings page.
    """
    rules = IMAGE_RULES.get(profile) or IMAGE_RULES["image"]
    try:
        from io import BytesIO

        from PIL import Image

        image = Image.open(BytesIO(data))
        # Flatten transparency onto white rather than letting JPEG turn it black.
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            backdrop = Image.new("RGB", image.size, (255, 255, 255))
            backdrop.paste(image, mask=image.split()[-1])
            image = backdrop
        elif image.mode != "RGB":
            image = image.convert("RGB")

        if image.width > rules["max_width"]:
            height = round(image.height * rules["max_width"] / image.width)
            image = image.resize((rules["max_width"], height), Image.LANCZOS)

        # Step quality down until it fits; keep the last (smallest) attempt.
        buffer = None
        for quality in (85, 75, 65, 55, 45):
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            if buffer.tell() <= rules["target_bytes"]:
                break

        stem = safe_name.rsplit(".", 1)[0] or "image"
        return buffer.getvalue(), f"{stem}.jpg", "image/jpeg"
    except Exception as exc:
        logger.warning("optimise_image: leaving %s unchanged (%s)", safe_name, exc)
        return data, safe_name, "image/jpeg"


def _cloudinary_configured() -> bool:
    cfg = current_app.config
    if cfg.get("CLOUDINARY_URL"):
        return True
    return bool(cfg.get("CLOUDINARY_CLOUD_NAME")
                and cfg.get("CLOUDINARY_API_KEY")
                and cfg.get("CLOUDINARY_API_SECRET"))


def _upload_to_cloudinary(data: bytes, key: str, folder: str) -> str | None:
    """
    Store an already-optimised image and return its delivery URL.

    Returns None on ANY failure so the caller falls back to local disk: an
    outage at a third party must not stop a landlord saving their logo.
    """
    try:
        from io import BytesIO

        import cloudinary
        import cloudinary.uploader

        cfg = current_app.config
        if cfg.get("CLOUDINARY_URL"):
            cloudinary.config(cloudinary_url=cfg["CLOUDINARY_URL"])
        else:
            cloudinary.config(
                cloud_name=cfg["CLOUDINARY_CLOUD_NAME"],
                api_key=cfg["CLOUDINARY_API_KEY"],
                api_secret=cfg["CLOUDINARY_API_SECRET"],
                secure=True,
            )

        result = cloudinary.uploader.upload(
            BytesIO(data),
            folder=f"sahilpay/{folder.strip('/')}",
            public_id=key.rsplit("/", 1)[-1].rsplit(".", 1)[0],
            resource_type="image",
            # The bytes are already the size we want delivered, so nothing is
            # transformed on the way in or on the way out. This is what keeps
            # transformation credits at zero.
            overwrite=False,
            unique_filename=True,
            invalidate=False,
        )
        url = result.get("secure_url")
        if url:
            logger.info("Cloudinary: stored %s (%.0f KB)", url, len(data) / 1024)
        return url
    except Exception as exc:
        logger.error("Cloudinary upload failed, falling back to local disk: %s", exc)
        return None


def validate_upload(data: bytes, safe_name: str, profile: str = "any") -> None:
    """
    Enforce the size and extension policy for *profile*. Raises ApiError(400).

    Called by upload_to_s3 for every upload, so no caller can skip it by
    forgetting — the check lives at the chokepoint, not at the call sites.
    """
    spec = UPLOAD_PROFILES.get(profile, UPLOAD_PROFILES["any"])
    extension = _extension_of(safe_name)

    if extension in FORBIDDEN_EXTENSIONS:
        raise ApiError(
            f"'.{extension}' files cannot be uploaded.",
            status=400, code="forbidden_file_type",
        )

    allowed = spec["ext"]
    if allowed is not None and extension not in allowed:
        raise ApiError(
            f"Unsupported file type '.{extension or 'unknown'}'. "
            f"Allowed: {', '.join(sorted(allowed))}.",
            status=400, code="invalid_file_type",
        )

    limit = min(spec["max"], MAX_UPLOAD_BYTES)
    if len(data) > limit:
        raise ApiError(
            f"File is too large ({len(data) / 1024 / 1024:.1f} MB). "
            f"The limit is {limit // 1024 // 1024} MB.",
            status=400, code="file_too_large",
        )
    if not data:
        raise ApiError("The uploaded file is empty.", status=400, code="empty_file")


def upload_to_s3(
    file,
    folder: str,
    filename: str | None = None,
    content_type: str | None = None,
    profile: str = "any",
    force_local: bool = False,
) -> str:
    """
    Upload *file* under *folder* and return a public URL.

    Parameters
    ----------
    file         : werkzeug FileStorage, BytesIO, or raw bytes.
    folder       : S3 "directory" prefix, e.g. "documents/12".
    filename     : optional override; defaults to the upload's own filename.
    content_type : optional MIME type override.
    profile      : upload policy to enforce — see UPLOAD_PROFILES
                   ("image", "document", "statement", "lease", "apk", "any").
    force_local  : keep the file on this server even when object storage is
                   configured. Used for the Co-pilot APK: it is one large file
                   fetched by every device on every release, and metered
                   object-storage egress is the wrong shape for that. Served
                   from /uploads/ behind the CDN instead.
    """
    data, safe_name, resolved_type = _read_file_bytes(file, filename, content_type)
    validate_upload(data, safe_name, profile)

    # Images are optimised BEFORE they go anywhere — local disk included, so a
    # deployment without Cloudinary still isn't storing 4MB phone photos.
    if profile in CLOUD_IMAGE_PROFILES:
        data, safe_name, resolved_type = optimise_image(data, safe_name, profile)

    key = f"{folder.strip('/')}/{secrets.token_hex(4)}_{safe_name}"

    # Cloudinary handles images only, and only when it is actually configured.
    # Anything else — documents, statements, signed leases, the APK — stays on
    # this server, where bandwidth is not billed by the gigabyte.
    if profile in CLOUD_IMAGE_PROFILES and not force_local and _cloudinary_configured():
        url = _upload_to_cloudinary(data, key, folder)
        if url:
            return url
        # Fell through: Cloudinary was unreachable. Keep the file locally rather
        # than failing the request the landlord was in the middle of.

    bucket = current_app.config.get("S3_BUCKET")
    aws_key = current_app.config.get("AWS_ACCESS_KEY_ID")
    aws_secret = current_app.config.get("AWS_SECRET_ACCESS_KEY")

    if not force_local and bucket and aws_key and aws_secret:
        return _upload_to_real_s3(data, key, resolved_type, bucket)

    return _upload_to_local_disk(data, key)


def _upload_to_real_s3(data: bytes, key: str, content_type: str, bucket: str) -> str:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    endpoint_url = current_app.config.get("S3_ENDPOINT_URL")
    region = current_app.config.get("S3_REGION", "us-east-1")
    public_base = current_app.config.get("S3_PUBLIC_BASE_URL", "")
    aws_key = current_app.config.get("AWS_ACCESS_KEY_ID")
    aws_secret = current_app.config.get("AWS_SECRET_ACCESS_KEY")

    try:
        kwargs: dict = dict(region_name=region, aws_access_key_id=aws_key, aws_secret_access_key=aws_secret)
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        s3 = boto3.client("s3", **kwargs)
        s3.upload_fileobj(BytesIO(data), bucket, key, ExtraArgs={"ContentType": content_type})
    except (BotoCoreError, ClientError) as exc:
        logger.error("upload_to_s3 failed for key '%s': %s", key, exc)
        raise ApiError("Failed to upload file. Please try again.", status=500, code="upload_error")

    if public_base:
        return f"{public_base.rstrip('/')}/{key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def _upload_to_local_disk(data: bytes, key: str) -> str:
    """
    Dev-mode fallback used whenever S3 isn't configured — writes under
    server/uploads/<key> and returns a URL served by app.py's /uploads route.
    """
    base_dir = os.path.join(current_app.root_path, _UPLOADS_DIR_NAME)
    full_path = os.path.join(base_dir, key)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "wb") as fh:
        fh.write(data)

    logger.info("storage_service: S3 not configured — saved upload locally at %s", full_path)
    return f"/uploads/{key}"
