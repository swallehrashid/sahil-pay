"""
SahilPay — services/token_service.py
=======================================
JWT revocation. app.py already wires a Redis-backed blocklist (set on
`app.revoke_token` inside _register_jwt_callbacks) — this module is the
service-layer name routes/auth_routes.py imports for the same operation.
"""

from __future__ import annotations

import logging

from flask import current_app

logger = logging.getLogger(__name__)


def blocklist_token(jti: str) -> None:
    """
    Add a JWT's jti to the Redis revocation set so token_in_blocklist_loader
    (registered in app.py) rejects it on every subsequent request. Used on
    logout.
    """
    if not jti:
        return
    try:
        current_app.revoke_token(jti)
    except Exception:
        # Fail open on a Redis outage rather than break logout for the user —
        # matches token_in_blocklist_loader's own fail-open behavior in app.py.
        logger.error("blocklist_token: failed to revoke jti=%s", jti, exc_info=True)
