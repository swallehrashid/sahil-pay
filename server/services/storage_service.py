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
MAX_UPLOAD_BYTES = 20 * 1024 * 1024        # hard ceiling for any upload

UPLOAD_PROFILES: dict[str, dict] = {
    # profile      allowed extensions                     max bytes
    "image":     {"ext": {"png", "jpg", "jpeg", "webp"},   "max": 5 * 1024 * 1024},
    "document":  {"ext": {"pdf", "png", "jpg", "jpeg", "webp"}, "max": 10 * 1024 * 1024},
    "statement": {"ext": {"pdf", "csv", "xls", "xlsx"},    "max": 20 * 1024 * 1024},
    "any":       {"ext": None,                             "max": MAX_UPLOAD_BYTES},
}

# Never stored, whatever the profile: these are executable in some context.
FORBIDDEN_EXTENSIONS = {
    "html", "htm", "xhtml", "svg", "js", "mjs", "php", "phtml", "py", "rb",
    "sh", "bash", "exe", "dll", "bat", "cmd", "com", "jar", "war", "cgi",
    "pl", "asp", "aspx", "jsp", "htaccess",
}


def _extension_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


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
                   ("image", "document", "statement", or "any").
    """
    data, safe_name, resolved_type = _read_file_bytes(file, filename, content_type)
    validate_upload(data, safe_name, profile)
    key = f"{folder.strip('/')}/{secrets.token_hex(4)}_{safe_name}"

    bucket = current_app.config.get("S3_BUCKET")
    aws_key = current_app.config.get("AWS_ACCESS_KEY_ID")
    aws_secret = current_app.config.get("AWS_SECRET_ACCESS_KEY")

    if bucket and aws_key and aws_secret:
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
