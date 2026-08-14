"""
services/login_guard.py — account lockout after repeated failed logins.

Rate limiting caps how fast ONE IP can guess. It does not stop a distributed
attempt against a single valuable account: rotate the source address and the
per-IP budget resets while the target account keeps absorbing guesses. This
tracks failures per ACCOUNT, so the account itself stops answering once it has
been guessed at too many times, whoever is asking.

State lives in Redis (already required for Celery and the rate limiter) rather
than a table: it is short-lived, high-churn, and must not survive as a permanent
record of somebody mistyping their password.

Deliberate behaviours:

  * A locked account returns the SAME generic "invalid email or password"
    message as a wrong password, plus a retry hint. Confirming "this account
    exists and is locked" would tell an attacker they found a real account.
  * Counters clear on a successful login, so an honest user who mistypes twice
    and then gets it right starts clean.
  * Redis being unreachable NEVER blocks a login. An outage in a defensive
    layer must not lock every customer out of the product.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_FAILURES = 8          # attempts allowed inside the window
WINDOW_SECONDS = 15 * 60  # failures older than this stop counting
LOCK_SECONDS = 15 * 60    # how long the account stays shut afterwards

_FAIL_KEY = "sahilpay:login:fail:{}"
_LOCK_KEY = "sahilpay:login:lock:{}"


def _redis():
    """The shared Redis client, or None when it is unavailable."""
    try:
        import redis
        from flask import current_app

        url = current_app.config.get("RATELIMIT_STORAGE_URI") or current_app.config.get("REDIS_URL")
        if not url:
            return None
        return redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    except Exception:
        return None


def _identity_key(identifier: str) -> str:
    return (identifier or "").strip().lower()


def lock_seconds_remaining(identifier: str) -> int:
    """Seconds until this account unlocks; 0 when it is not locked."""
    key = _identity_key(identifier)
    if not key:
        return 0
    client = _redis()
    if client is None:
        return 0
    try:
        ttl = client.ttl(_LOCK_KEY.format(key))
        return int(ttl) if ttl and ttl > 0 else 0
    except Exception:
        logger.warning("login_guard: could not read lock state", exc_info=True)
        return 0


def is_locked(identifier: str) -> bool:
    return lock_seconds_remaining(identifier) > 0


def record_failure(identifier: str) -> int:
    """
    Count one failed attempt. Returns the failure count; locks the account
    once it reaches MAX_FAILURES.
    """
    key = _identity_key(identifier)
    if not key:
        return 0
    client = _redis()
    if client is None:
        return 0
    try:
        fail_key = _FAIL_KEY.format(key)
        count = client.incr(fail_key)
        if count == 1:
            client.expire(fail_key, WINDOW_SECONDS)
        if count >= MAX_FAILURES:
            client.setex(_LOCK_KEY.format(key), LOCK_SECONDS, "1")
            client.delete(fail_key)
            logger.warning("login_guard: locked account '%s' after %s failures", key, count)
        return int(count)
    except Exception:
        logger.warning("login_guard: could not record failure", exc_info=True)
        return 0


def clear(identifier: str) -> None:
    """Wipe the counters — called after a successful login."""
    key = _identity_key(identifier)
    if not key:
        return
    client = _redis()
    if client is None:
        return
    try:
        client.delete(_FAIL_KEY.format(key), _LOCK_KEY.format(key))
    except Exception:
        logger.warning("login_guard: could not clear counters", exc_info=True)
