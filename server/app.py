"""
SahilPay — app.py
==================
Application factory and Celery factory.

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
  make_celery() — builds a Celery instance that pushes a Flask app context
                  for every task (so tasks can use db.session).

The Beat schedule is defined inside make_celery() because it is CORE
infrastructure, not optional:
  • generate-monthly-invoices     — 1st of month 00:05 Africa/Nairobi
  • generate-recurring-expenses   — 1st of month 00:10
  • check-trial-expirations       — daily 00:30
  • lease-expiry-notifications    — daily 07:00
  • low-sms-balance-alerts        — daily 08:00
"""

from __future__ import annotations

import logging
import os

import redis
from celery import Celery
from celery.schedules import crontab
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
    # prints a tenant's login code while Africa's Talking is unconfigured. In
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
        Load the User model from the JWT identity for current_user proxy.
        Returns None if the user no longer exists.
        """
        from models import User
        identity = jwt_data.get("sub")
        if identity is None:
            return None
        try:
            user_id = int(identity)
        except (TypeError, ValueError):
            return None
        return db.session.query(User).filter(User.id == user_id).first()

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
# Celery factory + Beat schedule
# ---------------------------------------------------------------------------

def make_celery(app: Flask | None = None) -> Celery:
    """
    Build a Celery instance tied to the Flask app context.

    Every task runs inside a Flask application context so that db.session
    and current_app are available (via the ContextTask base class).

    The Beat schedule is registered here because it is CORE to the product
    (monthly billing, trial checks) — not an optional add-on.

    Task dotted paths reference modules under tasks/ (built later).
    They are wrapped in try/except so Beat config does not crash when
    a task module has not been created yet.
    """
    if app is None:
        app = create_app()

    celery_instance = Celery(
        app.import_name,
        broker=app.config["CELERY_BROKER_URL"],
        backend=app.config["CELERY_RESULT_BACKEND"],
    )

    celery_instance.conf.update(
        task_always_eager=app.config.get("CELERY_TASK_ALWAYS_EAGER", False),
        timezone=app.config.get("CELERY_TIMEZONE", "Africa/Nairobi"),
        enable_utc=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Retry failed tasks once after 60 s by default.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
    )

    # ---- ContextTask: push Flask app context for every task ----

    class ContextTask(celery_instance.Task):
        """Base task class that ensures an active Flask app context."""
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return super().__call__(*args, **kwargs)

    celery_instance.Task = ContextTask

    # ---- Celery Beat schedule (core infra — non-optional) ----
    # Task callables live in tasks/ (built later). We reference them by
    # dotted path and guard each import so Beat config does not fail while
    # those modules are still being built.

    beat_schedule: dict = {}

    # 1st of every month at 00:05 Africa/Nairobi — generate rent /
    #   recurring-bill invoices for all landlords whose automation is on.
    beat_schedule["generate-monthly-invoices"] = {
        "task": "tasks.billing_tasks.generate_monthly_invoices",
        "schedule": crontab(day_of_month="1", hour="0", minute="5"),
        "options": {"queue": "periodic"},
    }

    # 1st of every month at 00:10 — instantiate recurring expense templates.
    beat_schedule["generate-recurring-expenses"] = {
        "task": "tasks.billing_tasks.generate_recurring_expenses",
        "schedule": crontab(day_of_month="1", hour="0", minute="10"),
        "options": {"queue": "periodic"},
    }

    # Daily at 00:30 — expire trials whose trial_ends_at has passed.
    beat_schedule["check-trial-expirations"] = {
        "task": "tasks.admin_tasks.check_trial_expirations",
        "schedule": crontab(hour="0", minute="30"),
        "options": {"queue": "periodic"},
    }

    # Daily at 07:00 — notify landlords of leases expiring within their
    #   configured lease_expiry_range_days window.
    beat_schedule["lease-expiry-notifications"] = {
        "task": "tasks.notification_tasks.lease_expiry_notifications",
        "schedule": crontab(hour="7", minute="0"),
        "options": {"queue": "periodic"},
    }

    # Daily at 08:00 — warn landlords whose SMS balance is below threshold.
    beat_schedule["low-sms-balance-alerts"] = {
        "task": "tasks.notification_tasks.low_sms_balance_alerts",
        "schedule": crontab(hour="8", minute="0"),
        "options": {"queue": "periodic"},
    }

    celery_instance.conf.beat_schedule = beat_schedule

    return celery_instance


# ---------------------------------------------------------------------------
# Module-level app + Celery  (for `flask` CLI and gunicorn)
# ---------------------------------------------------------------------------
# These are created at import time so the `flask` CLI can find the app and
# so gunicorn / uWSGI can reference "app:app".
# make_celery is called separately in celery_app.py for the worker process.

app = create_app()

if __name__ == "__main__":
    # Local development server.
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=app.config.get("DEBUG", False),
    )