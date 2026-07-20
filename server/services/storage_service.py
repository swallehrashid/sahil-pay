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


def upload_to_s3(
    file,
    folder: str,
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    """
    Upload *file* under *folder* and return a public URL.

    Parameters
    ----------
    file         : werkzeug FileStorage, BytesIO, or raw bytes.
    folder       : S3 "directory" prefix, e.g. "documents/12".
    filename     : optional override; defaults to the upload's own filename.
    content_type : optional MIME type override.
    """
    data, safe_name, resolved_type = _read_file_bytes(file, filename, content_type)
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
