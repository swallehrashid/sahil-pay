"""
SahilPay — app.py
==================
Application factory.

Usage
-----
  # Flask dev server
  python app.py

  # Gunicorn
  gunicorn "app:create_app()" -w 4 -b 0.0.0.0:5000

  # Celery worker  (once celery_app.py exists)
  celery -A celery_app worker --loglevel=info

  # Celery Beat scheduler
  celery -A celery_app beat --loglevel=info

Design
------
  create_app()  — builds the Flask app; registers extensions, blueprints,
                  JWT callbacks, and error handlers in a fixed order.

The Celery instance, its task registry (via `include=`) and the Beat
schedule all live in celery_app.py — that is the single instance the
worker and beat entrypoints above actually load. There is deliberately no
Celery factory here: an earlier make_celery() built a second, orphaned
instance that nothing ever called, so the Beat schedule it defined was
invisible to the running beat process.
"""

from __future__ import annotations

import logging
import os

import redis
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from sqlalchemy.exc import IntegrityError

from config import get_config
from extensions import cors, db, jwt, limiter, ma, migrate, swagger
from utils import ApiError, error, success

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(config_name: str | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Steps (in order — do not reorder):
      1.  Create Flask instance.
      2.  Load config.
      3.  Bind extensions (db → migrate → jwt → limiter → ma → cors → swagger).
      4.  Import models (registers mappers on Base.metadata).
      5.  Register JWT callbacks.
      6.  Register blueprints (tolerates absence — app boots before routes exist).
      7.  Register error handlers.
      8.  Register /api/health liveness route.
      9.  Register shell context.
      10. Return app.
    """

    # ------------------------------------------------------------------
    # Step 1 — Flask instance
    # ------------------------------------------------------------------
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Step 2 — Load configuration
    # ------------------------------------------------------------------
    cfg = get_config(config_name)
    app.config.from_object(cfg)

    # ------------------------------------------------------------------
    # Step 2b — Logging
    # ------------------------------------------------------------------
    # Python's root logger defaults to WARNING, which silently swallows every
    # logger.info(...) the app emits — including the dev SMS/OTP stub line that
    # prints a tenant's login code while FluxSMS is unconfigured. In
    # development we lower the threshold to INFO so those show up in the same
    # terminal that runs `python app.py` (no separate Celery worker needed when
    # CELERY_TASK_ALWAYS_EAGER is on). basicConfig only installs a handler if
    # none exists yet; the explicit setLevel covers the reloader's second pass.
    log_level = logging.INFO if app.config.get("DEBUG") else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger().setLevel(log_level)

    # ------------------------------------------------------------------
    # Step 3 — Bind extensions  (order matters for dependency reasons)
    # ------------------------------------------------------------------

    # PostgreSQL via SQLAlchemy (metadata shared with plain Base — see extensions.py)
    db.init_app(app)

    # Flask-Migrate drives Alembic: `flask db migrate` / `flask db upgrade`
    migrate.init_app(app, db)

    # JWT — stateless auth
    jwt.init_app(app)

    # Rate limiter — uses Redis storage URI from config
    limiter.init_app(app)

    # Marshmallow — request/response (de)serialisation
    ma.init_app(app)

    # CORS — restrict cross-origin requests to configured origins on /api/*
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config.get("CORS_ORIGINS", [])}},
        supports_credentials=True,
    )

    # Swagger / flasgger — OpenAPI 3 UI at /api/docs/
    #
    # NOT mounted in production: the spec enumerates every endpoint, its
    # parameters and its auth requirements, which is a free reconnaissance map
    # for anyone probing the API. Developers keep it locally; the public
    # deployment doesn't publish its own attack surface. Set
    # ENABLE_API_DOCS=true to override deliberately (e.g. a staging box).
    if app.config.get("ENABLE_API_DOCS", not app.config.get("IS_PRODUCTION", False)):
        swagger.init_app(app)

    # ------------------------------------------------------------------
    # Step 4 — Import models so all 39 tables register on Base.metadata
    # ------------------------------------------------------------------
    # This bare import is REQUIRED even though nothing from models is used
    # directly in this file.  Without it, Alembic autogenerate and
    # db.create_all() would see an empty metadata.
    import models  # noqa: F401

    # ------------------------------------------------------------------
    # Step 5 — JWT callbacks
    # ------------------------------------------------------------------
    _register_jwt_callbacks(app, jwt)

    # ------------------------------------------------------------------
    # Step 6 — Blueprints
    # ------------------------------------------------------------------
    # Imported inside try/except so the app boots cleanly before the
    # routes/ folder exists.  Once routes are built this becomes the
    # normal (non-exception) path.
    try:
        # Collection routes are registered as @bp.route("/") (e.g. /api/properties/),
        # but the frontend calls them without the trailing slash (/api/properties).
        # With the default strict_slashes=True, Werkzeug answers the OPTIONS preflight
        # with a 308 redirect to the slashed URL — and browsers refuse to follow a
        # redirect on a preflight, so every authenticated list/create request is blocked
        # by CORS. Disabling strict slashes makes both forms match the same rule with
        # no redirect. Must be set before blueprints register so every rule inherits it.
        app.url_map.strict_slashes = False
        from routes import register_blueprints  # type: ignore[import]
        register_blueprints(app)
        logger.info("Blueprints registered successfully.")
    except ImportError:
        logger.warning(
            "routes/__init__.py not found — running without API blueprints. "
            "Build the routes/ folder to enable API endpoints."
        )

    # ------------------------------------------------------------------
    # Step 7 — Error handlers
    # ------------------------------------------------------------------
    _register_error_handlers(app)

    # ------------------------------------------------------------------
    # Step 8 — Liveness endpoint  (unauthenticated, rate-limit exempt)
    # ------------------------------------------------------------------
    @app.get("/api/health")
    @limiter.exempt
    def health():
        """
        GET /api/health
        Simple liveness check for load balancers and monitoring tools.
        ---
        tags:
          - Health
        responses:
          200:
            description: Application is alive.
        """
        return success(
            data={"status": "ok", "env": app.config.get("APP_ENV", "unknown")},
            message="SahilPay API is running.",
        )

    # ------------------------------------------------------------------
    # Step 8b — Local-disk upload serving (dev-mode storage_service fallback)
    # ------------------------------------------------------------------
    # services/storage_service.upload_to_s3() writes here whenever S3 isn't
    # configured, so uploads still round-trip while testing without AWS
    # creds. Never used when S3_BUCKET + AWS credentials are set.
    @app.get("/uploads/<path:subpath>")
    @limiter.exempt
    def serve_local_upload(subpath: str):
        from flask import send_from_directory

        uploads_dir = os.path.join(app.root_path, "uploads")
        return send_from_directory(uploads_dir, subpath)

    # ------------------------------------------------------------------
    # Step 9 — Shell context  (flask shell)
    # ------------------------------------------------------------------
    @app.shell_context_processor
    def _shell_ctx():
        """Expose key objects for `flask shell` development sessions."""
        import models as m
        return {
            "db": db,
            "models": m,
            # Most-used models for quick ad-hoc queries in the shell:
            "User": m.User,
            "Landlord": m.Landlord,
            "TeamMember": m.TeamMember,
            "Tenant": m.Tenant,
            "Property": m.Property,
            "Unit": m.Unit,
            "Invoice": m.Invoice,
            "Payment": m.Payment,
            "Expense": m.Expense,
            "AuditLog": m.AuditLog,
        }

    # ------------------------------------------------------------------
    # Step 10 — Return
    # ------------------------------------------------------------------
    return app


# ---------------------------------------------------------------------------
# JWT callbacks
# ---------------------------------------------------------------------------

def _register_jwt_callbacks(app: Flask, jwt_manager: JWTManager) -> None:
    """Register all Flask-JWT-Extended callbacks on the app."""

    # Build a Redis client for the token blocklist (revoked refresh tokens).
    # The client is lazy — connection is made on first use.
    _redis_client: redis.Redis | None = None

    def _get_redis() -> redis.Redis:
        nonlocal _redis_client
        if _redis_client is None:
            redis_url = app.config.get("REDIS_URL", "redis://localhost:6379/0")
            _redis_client = redis.from_url(redis_url, decode_responses=True)
        return _redis_client

    BLOCKLIST_KEY = "sahilpay:jwt_blocklist"

    @jwt_manager.user_identity_loader
    def user_identity_loader(user) -> str:
        """
        Serialise the user into the JWT identity (stored as users.id, as a
        string — JWT 'sub' claims are conventionally strings, and routes/*.py
        consistently does int(get_jwt_identity())  on the way back out).
        Accepts an int, a str, or a full User model instance, since routes
        call create_access_token() with all three shapes depending on file.
        """
        if isinstance(user, (int, str)):
            return str(user)
        return str(user.id)

    @jwt_manager.user_lookup_loader
    def user_lookup_loader(_jwt_header, jwt_data):
        """
        Resolve the JWT identity into the current_user proxy.

        SECURITY — tenant identity isolation:
        Tenant tokens use a namespaced identity ("tenant:<id>", see
        otp_routes.py). This exists because tenants are OTP-only and usually
        have NO linked User row (tenant_routes.py creates no User), so the old
        str(tenant.user_id or tenant.id) identity fell back to tenant.id — a
        bare integer that this loader then resolved as a User.id, silently
        logging the tenant into whatever unrelated User (often a landlord's
        team member) shared that number. A namespaced identity can never
        collide with a numeric User.id.

        For a tenant identity we must NOT load a real User (that is the bug),
        but we also must NOT return None: flask-jwt-extended raises
        UserLookupError -> 401 when a registered loader returns None, which
        would break every tenant request. So we return a transient, unpersisted
        sentinel User carrying the tenant's real id/role and nothing else — it
        is never added to the session, never queried back, and only ever exists
        to keep current_user truthy. Tenant routes authorise off the tenant_id
        claim, not current_user, so this sentinel is never used for access
        decisions.
        """
        from models import User, UserRole
        identity = jwt_data.get("sub")
        if identity is None:
            return None

        identity = str(identity)
        if identity.startswith("tenant:"):
            tenant_id_str = identity.split(":", 1)[1]
            sentinel = User(role=UserRole.tenant.value)
            sentinel.id = int(tenant_id_str) if tenant_id_str.isdigit() else None
            sentinel._is_tenant_token = True  # marker for any code that must distinguish
            return sentinel

        if not identity.isdigit():
            return None
        return db.session.query(User).filter(User.id == int(identity)).first()

    @jwt_manager.token_in_blocklist_loader
    def token_in_blocklist_loader(_jwt_header, jwt_data: dict) -> bool:
        """
        Return True if the JWT's jti is in the Redis blocklist (revoked).
        Called on every protected request.
        """
        jti = jwt_data.get("jti")
        if not jti:
            return False
        try:
            return _get_redis().sismember(BLOCKLIST_KEY, jti)
        except Exception as exc:
            logger.error("Redis blocklist check failed: %s", exc)
            # Fail open (allow) rather than block all users on Redis outage.
            return False

    # Public helper so auth_routes.py can revoke a token on logout.
    app.revoke_token = lambda jti: _get_redis().sadd(BLOCKLIST_KEY, jti)  # type: ignore[attr-defined]

    # ---- Uniform JWT error responses ----

    @jwt_manager.expired_token_loader
    def expired_token_loader(_jwt_header, _jwt_data):
        return error("Your session has expired. Please log in again.", status=401, code="token_expired")

    @jwt_manager.invalid_token_loader
    def invalid_token_loader(reason: str):
        return error(f"Invalid token: {reason}", status=401, code="invalid_token")

    @jwt_manager.unauthorized_loader
    def unauthorized_loader(reason: str):
        return error(f"Authentication required: {reason}", status=401, code="unauthorized")

    @jwt_manager.revoked_token_loader
    def revoked_token_loader(_jwt_header, _jwt_data):
        return error("This session has been revoked. Please log in again.", status=401, code="token_revoked")

    @jwt_manager.needs_fresh_token_loader
    def needs_fresh_token_loader(_jwt_header, _jwt_data):
        return error("A fresh login is required for this action.", status=401, code="fresh_token_required")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

def _register_error_handlers(app: Flask) -> None:
    """Register uniform JSON error handlers for all exception types."""

    import marshmallow

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error(exc.message, status=exc.status, errors=exc.errors, code=exc.code)

    @app.errorhandler(marshmallow.ValidationError)
    def handle_marshmallow_validation(exc: marshmallow.ValidationError):
        return error(
            "Validation failed. Please check the highlighted fields.",
            status=422,
            errors=exc.messages,
            code="validation_error",
        )

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(exc: IntegrityError):
        db.session.rollback()
        logger.warning("IntegrityError: %s", exc.orig)
        return error(
            "A record with these details already exists, or a required reference is missing.",
            status=409,
            code="integrity_error",
        )

    @app.errorhandler(400)
    def handle_400(_exc):
        return error("Bad request.", status=400, code="bad_request")

    @app.errorhandler(401)
    def handle_401(_exc):
        return error("Authentication required.", status=401, code="unauthorized")

    @app.errorhandler(403)
    def handle_403(_exc):
        return error("You do not have permission to perform this action.", status=403, code="forbidden")

    @app.errorhandler(404)
    def handle_404(_exc):
        return error("The requested resource was not found.", status=404, code="not_found")

    @app.errorhandler(405)
    def handle_405(_exc):
        return error("HTTP method not allowed on this endpoint.", status=405, code="method_not_allowed")

    @app.errorhandler(429)
    def handle_429(_exc):
        return error(
            "Too many requests. Please slow down and try again shortly.",
            status=429,
            code="rate_limit_exceeded",
        )

    @app.errorhandler(500)
    def handle_500(exc):
        logger.exception("Unhandled 500 error: %s", exc)
        # Never leak internal details in the HTTP response.
        return error(
            "An unexpected error occurred. Our team has been notified.",
            status=500,
            code="internal_server_error",
        )


# ---------------------------------------------------------------------------
# Module-level app  (for `flask` CLI and gunicorn)
# ---------------------------------------------------------------------------
# Created at import time so the `flask` CLI can find the app and so
# gunicorn / uWSGI can reference "app:app". The Celery instance lives in
# celery_app.py and is loaded independently by the worker/beat processes.

app = create_app()

if __name__ == "__main__":
    # Local development server.
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=app.config.get("DEBUG", False),
    )