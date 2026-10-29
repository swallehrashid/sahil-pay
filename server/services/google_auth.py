"""
SahilPay — services/google_auth.py
===================================
Verify a Google ID token ("credential") returned by Google Identity Services in
the browser, and hand back the trustworthy claims.

The browser never proves who the user is — Google does. The frontend runs the
Google Sign-In flow and receives a signed JWT (the ID token); this module checks
that signature against Google's published public keys and confirms the token was
minted for THIS application before anything downstream trusts the email inside
it. Done with PyJWT's JWKS client (already a dependency), so there is no extra
Google SDK to install or service-account key to manage.

Checks performed (any failure raises GoogleAuthError):
  * RS256 signature against Google's live JWKS;
  * audience == our configured GOOGLE_CLIENT_ID (the token was issued for us,
    not some other app that happens to use Google);
  * issuer is Google;
  * not expired.

The caller still decides what to do with an unverified email — we surface
`email_verified` rather than hard-failing, so the route can refuse it with a
message a human understands.
"""

from __future__ import annotations

import threading

_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
_GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"

# One JWKS client for the process — PyJWKClient caches Google's signing keys and
# only refetches when it sees a key id it does not know, so this is both correct
# and cheap. Guarded by a lock because the first request may race.
_jwks_client = None
_jwks_lock = threading.Lock()


class GoogleAuthError(Exception):
    """A Google credential could not be trusted. The message is safe to show."""


def _client():
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                from jwt import PyJWKClient
                _jwks_client = PyJWKClient(_GOOGLE_CERTS_URL)
    return _jwks_client


def verify_id_token(credential: str, audience: str) -> dict:
    """
    Verify a Google ID token and return its claims as a dict with at least:
    ``sub`` (Google's stable user id), ``email``, ``email_verified`` (bool),
    ``name`` (may be absent). Raises GoogleAuthError on any problem.
    """
    import jwt

    if not credential or not isinstance(credential, str):
        raise GoogleAuthError("No Google credential was provided.")
    if not audience:
        raise GoogleAuthError("Google Sign-In is not configured on this server.")

    try:
        signing_key = _client().get_signing_key_from_jwt(credential)
        claims = jwt.decode(
            credential,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise GoogleAuthError("Your Google sign-in expired. Please try again.") from exc
    except jwt.InvalidAudienceError as exc:
        raise GoogleAuthError("This Google sign-in was not issued for Sahil Pay.") from exc
    except GoogleAuthError:
        raise
    except Exception as exc:  # noqa: BLE001 — any decode/JWKS failure is untrusted
        raise GoogleAuthError("Could not verify your Google sign-in. Please try again.") from exc

    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise GoogleAuthError("This sign-in did not come from Google.")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise GoogleAuthError("Your Google account did not share an email address.")

    return {
        "sub":            claims.get("sub"),
        "email":          email,
        "email_verified": bool(claims.get("email_verified")),
        "name":           (claims.get("name") or "").strip(),
        "given_name":     (claims.get("given_name") or "").strip(),
        "family_name":    (claims.get("family_name") or "").strip(),
    }
