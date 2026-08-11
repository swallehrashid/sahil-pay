"""
services/twofa_service.py — time-based two-factor authentication (TOTP).

A stolen admin password should not be enough to take the platform. This adds the
second factor: a 6-digit code from an authenticator app (Google Authenticator,
Authy, 1Password — anything speaking RFC 6238), which changes every 30 seconds
and never travels over the network.

Mandatory for system admins, optional for landlords. An admin can reach every
landlord's money and every tenant's phone number, so their account is the single
most valuable target in the system and is not left on a password alone.

WHAT IS STORED, AND HOW
    The TOTP secret is the whole security of the scheme: anyone holding it can
    generate valid codes forever. It is therefore encrypted at rest with Fernet
    (AES-128-CBC + HMAC) using FIELD_ENCRYPTION_KEY, so a leaked database dump
    does not hand over working second factors.

    Backup codes are stored only as salted hashes — the same reasoning as
    passwords. Each one works once.

KEY MANAGEMENT
    FIELD_ENCRYPTION_KEY must be set in production and must NEVER be rotated
    casually: rotating it makes every stored secret undecryptable and locks every
    2FA user out. In development a key is derived from SECRET_KEY so the feature
    works out of the box without a second variable to configure.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets

logger = logging.getLogger(__name__)

ISSUER = "Sahil Pay"
BACKUP_CODE_COUNT = 8
# A window of 1 accepts the previous and next 30-second step, which absorbs
# ordinary clock drift between the phone and the server. Wider than that starts
# meaningfully extending how long an intercepted code stays usable.
VALID_WINDOW = 1


# ---------------------------------------------------------------------------
# Encryption of the stored secret
# ---------------------------------------------------------------------------

def _fernet():
    from cryptography.fernet import Fernet
    from flask import current_app

    key = current_app.config.get("FIELD_ENCRYPTION_KEY")
    if not key:
        # Derive a stable key from SECRET_KEY so development works with no extra
        # configuration. Production sets a real, independent key — see config.py,
        # which refuses to start without one.
        digest = hashlib.sha256(
            str(current_app.config["SECRET_KEY"]).encode("utf-8")
        ).digest()
        key = base64.urlsafe_b64encode(digest)
    elif isinstance(key, str):
        key = key.encode("utf-8")

    return Fernet(key)


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        # Almost always means FIELD_ENCRYPTION_KEY changed. Fail closed: the
        # user must re-enrol rather than be let in without a second factor.
        logger.error("2FA: stored secret could not be decrypted — key rotated?")
        return None


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------

def generate_secret() -> str:
    import pyotp

    return pyotp.random_base32()


def provisioning_uri(secret: str, account_label: str) -> str:
    """The otpauth:// URI an authenticator app scans as a QR code."""
    import pyotp

    return pyotp.TOTP(secret).provisioning_uri(name=account_label, issuer_name=ISSUER)


def verify_code(secret: str | None, code: str | None) -> bool:
    """True when `code` is currently valid for `secret`."""
    if not secret or not code:
        return False
    import pyotp

    cleaned = str(code).strip().replace(" ", "")
    if not cleaned.isdigit():
        return False
    return pyotp.TOTP(secret).verify(cleaned, valid_window=VALID_WINDOW)


# ---------------------------------------------------------------------------
# Backup codes
# ---------------------------------------------------------------------------

def _hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> tuple[list[str], str]:
    """
    Fresh backup codes. Returns (plaintext codes, JSON of their hashes).

    The plaintext is shown to the user exactly once — losing a phone must not
    mean losing the account, but we must not be able to read the codes back
    either, so only the hashes are stored.
    """
    codes = [
        f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        for _ in range(count)
    ]
    return codes, json.dumps([_hash_backup_code(c) for c in codes])


def consume_backup_code(stored_json: str | None, code: str | None) -> tuple[bool, str | None]:
    """
    Try to spend one backup code.

    Returns (matched, remaining_json). A used code is removed, so each works
    exactly once — otherwise a code read over someone's shoulder would be a
    permanent second key.
    """
    if not stored_json or not code:
        return False, stored_json
    try:
        hashes = json.loads(stored_json)
    except (TypeError, ValueError):
        return False, stored_json

    candidate = _hash_backup_code(code)
    if candidate not in hashes:
        return False, stored_json

    hashes.remove(candidate)
    return True, json.dumps(hashes)


def backup_codes_remaining(stored_json: str | None) -> int:
    if not stored_json:
        return 0
    try:
        return len(json.loads(stored_json))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def is_required_for(user) -> bool:
    """
    Whether this user MUST have 2FA enabled.

    System admins: always. They can reach every landlord's money and every
    tenant's personal data; a password alone is not an acceptable guard on that.
    Everyone else: optional, their choice.
    """
    from models import UserRole

    return bool(user) and user.role == UserRole.system_admin.value
