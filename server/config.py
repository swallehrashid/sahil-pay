"""
SahilPay — config.py
====================
Class-based configuration hierarchy driven entirely by environment variables.
No secrets are hard-coded.  Load a `.env` file (via python-dotenv) and override
with real env vars in CI/staging/production.

Usage
-----
    from config import get_config
    app.config.from_object(get_config())          # auto-detects APP_ENV / FLASK_ENV
    app.config.from_object(get_config("testing")) # explicit

Environment selection
---------------------
    APP_ENV  (preferred) → "development" | "testing" | "production"
    FLASK_ENV (fallback) → same values
    Default              → "development"
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from decimal import Decimal

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env before any os.environ reads so local dev works without system vars.
load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str | None = None) -> str | None:
    """Return os.environ[key] or default.  Use _require() for mandatory keys."""
    return os.environ.get(key, default)


def _require(key: str, context: str = "") -> str:
    """Return os.environ[key] or raise a clear RuntimeError."""
    val = os.environ.get(key)
    if not val:
        ctx = f" ({context})" if context else ""
        raise RuntimeError(
            f"[SahilPay] Required environment variable '{key}' is missing or empty{ctx}. "
            f"Check your .env or server environment."
        )
    return val


def _normalize_db_url(url: str) -> str:
    """
    Heroku / managed hosts sometimes supply 'postgres://...' but SQLAlchemy
    requires 'postgresql+psycopg2://...'.  Normalize both quirks here.
    """
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _split_origins(raw: str) -> list[str]:
    """'http://a.com,http://b.com' → ['http://a.com', 'http://b.com']"""
    return [o.strip() for o in raw.split(",") if o.strip()]


# ---------------------------------------------------------------------------
# Base configuration (all environments inherit from this)
# ---------------------------------------------------------------------------

class BaseConfig:
    """
    All shared settings.  Subclasses override only what changes per environment.
    Every value is read from the environment; non-secret values have sane defaults.
    """

    # ------------------------------------------------------------------
    # Core / Flask
    # ------------------------------------------------------------------
    APP_ENV: str = _env("APP_ENV", "development")
    DEBUG: bool = False
    TESTING: bool = False
    IS_PRODUCTION: bool = False

    # The interactive OpenAPI explorer at /api/docs/. Off in production (it maps
    # the whole attack surface for free); flip on per-environment when a staging
    # box genuinely needs it.
    ENABLE_API_DOCS: bool = _env("ENABLE_API_DOCS", "").lower() in ("1", "true", "yes")

    # Encrypts sensitive columns at rest — currently the TOTP secrets that back
    # two-factor auth. Must be a urlsafe-base64 32-byte Fernet key.
    # Generate one with:
    #     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # NEVER rotate this casually: every stored secret becomes undecryptable and
    # every 2FA user is locked out. In development a key is derived from
    # SECRET_KEY so the feature works with no extra configuration.
    FIELD_ENCRYPTION_KEY: str | None = _env("FIELD_ENCRYPTION_KEY")

    # Secret key: dev gets a fallback, prod MUST have a real value (enforced
    # in ProductionConfig).
    SECRET_KEY: str = _env("SECRET_KEY", "dev-secret-key-change-in-production-!!!")

    # Prevent Flask from sorting JSON keys so client receives them in definition
    # order; keeps API responses predictable.
    JSON_SORT_KEYS: bool = False

    # Surface exceptions through Werkzeug's debugger / propagate to error handlers.
    PROPAGATE_EXCEPTIONS: bool = True

    # ------------------------------------------------------------------
    # Database — PostgreSQL (ACID required for the financial ledger)
    # ------------------------------------------------------------------
    _raw_db_url: str = _env(
        "DATABASE_URL",
        "postgresql+psycopg2://sahilpay:sahilpay@localhost:5432/sahilpay",
    )
    SQLALCHEMY_DATABASE_URI: str = _normalize_db_url(_raw_db_url)

    # Never emit modification-tracking signals (performance overhead, unused).
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Connection-pool tuning for a long-running Flask/gunicorn app.
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,      # verify connections before use
        "pool_recycle": 1800,       # recycle connections every 30 minutes
        "pool_size": 10,            # maintained connections in the pool
        "max_overflow": 20,         # extra connections allowed under burst load
    }

    # ------------------------------------------------------------------
    # JWT — Flask-JWT-Extended  (stateless; §2 Auth & Security)
    # ------------------------------------------------------------------
    JWT_SECRET_KEY: str = _env("JWT_SECRET_KEY") or SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(
        minutes=int(_env("JWT_ACCESS_MINUTES", "30"))
    )
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(
        days=int(_env("JWT_REFRESH_DAYS", "30"))
    )
    JWT_TOKEN_LOCATION: list[str] = ["headers"]
    JWT_HEADER_TYPE: str = "Bearer"

    # ------------------------------------------------------------------
    # Redis  (shared by Celery broker, result backend, rate-limiter)
    # ------------------------------------------------------------------
    REDIS_URL: str = _env("REDIS_URL", "redis://localhost:6379/0")

    # Celery — background tasks and Beat scheduler
    CELERY_BROKER_URL: str = _env("CELERY_BROKER_URL") or REDIS_URL
    CELERY_RESULT_BACKEND: str = _env("CELERY_RESULT_BACKEND") or REDIS_URL
    CELERY_TASK_ALWAYS_EAGER: bool = False      # set True in TestingConfig
    CELERY_TIMEZONE: str = "Africa/Nairobi"

    # ------------------------------------------------------------------
    # Rate limiting — Flask-Limiter  (§2 Auth & Security)
    # ------------------------------------------------------------------
    RATELIMIT_STORAGE_URI: str = _env("RATELIMIT_STORAGE_URI") or REDIS_URL
    RATELIMIT_DEFAULT: str = "200 per minute"
    RATELIMIT_HEADERS_ENABLED: bool = True      # expose X-RateLimit-* headers
    RATELIMIT_ENABLED: bool = True
    # Fail OPEN when the rate-limiter's Redis is unreachable. Without this,
    # Flask-Limiter raises on every request it cannot count and the whole API
    # answers 500 — a Redis blip takes the entire product down, which is a far
    # worse outcome than briefly not counting requests. Verified the hard way:
    # a stopped Redis container 500'd every endpoint including the public
    # pricing page. Brute-force protection also has a second, independent layer
    # (services/login_guard.py account lockout), so this is not the only guard.
    RATELIMIT_SWALLOW_ERRORS: bool = True
    RATELIMIT_IN_MEMORY_FALLBACK_ENABLED: bool = True

    # ------------------------------------------------------------------
    # CORS — frontend origins allowed on /api/* endpoints
    # ------------------------------------------------------------------
    CORS_ORIGINS: list[str] = _split_origins(
        _env(
            "CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000,"
            "http://127.0.0.1:5173,http://127.0.0.1:3000",
        )
    )

    # First CORS origin doubles as the base URL for links embedded in
    # transactional emails (verification, password reset, team activation).
    FRONTEND_URL: str = _env("FRONTEND_URL", CORS_ORIGINS[0] if CORS_ORIGINS else "http://localhost:5173")

    # ------------------------------------------------------------------
    # Cloudinary — property images, maintenance photos
    # ------------------------------------------------------------------
    CLOUDINARY_URL: str | None = _env("CLOUDINARY_URL")          # OR use the 3 below
    CLOUDINARY_CLOUD_NAME: str | None = _env("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY: str | None = _env("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET: str | None = _env("CLOUDINARY_API_SECRET")

    # ------------------------------------------------------------------
    # S3-compatible storage — generated PDFs (leases, receipts, statements)
    # ------------------------------------------------------------------
    S3_BUCKET: str | None = _env("S3_BUCKET")
    S3_ENDPOINT_URL: str | None = _env("S3_ENDPOINT_URL")    # None = AWS default
    S3_REGION: str = _env("S3_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID: str | None = _env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str | None = _env("AWS_SECRET_ACCESS_KEY")
    S3_PUBLIC_BASE_URL: str | None = _env("S3_PUBLIC_BASE_URL")  # CDN prefix

    # ------------------------------------------------------------------
    # FluxSMS — SMS delivery  (Kenyan delivery; §2 Third-Party Integrations)
    # ------------------------------------------------------------------
    FLUXSMS_BASE_URL: str = _env("FLUXSMS_BASE_URL", "https://api.fluxsms.co.ke")
    FLUXSMS_API_KEY: str | None = _env("FLUXSMS_API_KEY")
    FLUXSMS_SENDER_ID: str = _env("FLUXSMS_SENDER_ID", "SAHILPAY")

    # ------------------------------------------------------------------
    # Email — SendGrid  (transactional; §2 Third-Party Integrations)
    # ------------------------------------------------------------------
    SENDGRID_API_KEY: str | None = _env("SENDGRID_API_KEY")
    MAIL_DEFAULT_SENDER: str = _env("MAIL_DEFAULT_SENDER", "noreply@sahilpay.co.ke")
    MAIL_DEFAULT_SENDER_NAME: str = _env("MAIL_DEFAULT_SENDER_NAME", "Sahil Pay")

    # When True (default until real SMS/email/WhatsApp providers are wired),
    # message dispatch is SIMULATED: no external API is called, and a message is
    # marked "delivered" when the recipient has a usable destination (phone for
    # SMS/WhatsApp, email for email) or "failed" when it doesn't. This lets the
    # whole communications flow — send, log, and the sent/delivered/failed
    # counters — work end to end. Set COMMS_SIMULATION_MODE=false (and add the
    # provider keys) to switch to real sending with nothing else to change.
    COMMS_SIMULATION_MODE: bool = _env("COMMS_SIMULATION_MODE", "true").lower() in ("1", "true", "yes", "on")

    # When True, landlords/PMs must verify their email before they can log in.
    # Defaults on; DevelopmentConfig flips it off so local testing isn't blocked
    # before SendGrid is wired. Override per-environment with ENFORCE_EMAIL_VERIFICATION.
    ENFORCE_EMAIL_VERIFICATION: bool = _env("ENFORCE_EMAIL_VERIFICATION", "true").lower() in ("1", "true", "yes", "on")

    # ------------------------------------------------------------------
    # M-Pesa / Daraja — platform paybill (MPESA_INTEGRATION_SPEC.md)
    # ------------------------------------------------------------------
    # Platform-billing STK/C2B/B2C — landlord → Sahil's OWN paybill (subscriptions,
    # SMS credits) and Sahil → affiliate's phone (B2C payouts). Distinct from any
    # landlord's own paybill/till used to collect rent — rent never touches this
    # shortcode (MPESA_INTEGRATION_SPEC.md D1).
    DARAJA_BASE_URL: str = _env("DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke")
    PLATFORM_DARAJA_SHORTCODE: str | None = _env("PLATFORM_DARAJA_SHORTCODE")
    PLATFORM_DARAJA_PASSKEY: str | None = _env("PLATFORM_DARAJA_PASSKEY")
    PLATFORM_DARAJA_CONSUMER_KEY: str | None = _env("PLATFORM_DARAJA_CONSUMER_KEY")
    PLATFORM_DARAJA_CONSUMER_SECRET: str | None = _env("PLATFORM_DARAJA_CONSUMER_SECRET")
    PLATFORM_DARAJA_STK_CALLBACK_URL: str | None = _env("PLATFORM_DARAJA_STK_CALLBACK_URL")

    # B2C (affiliate payouts) — created in the M-Pesa Organization portal.
    PLATFORM_DARAJA_INITIATOR_NAME: str | None = _env("PLATFORM_DARAJA_INITIATOR_NAME")
    PLATFORM_DARAJA_SECURITY_CREDENTIAL: str | None = _env("PLATFORM_DARAJA_SECURITY_CREDENTIAL")
    PLATFORM_DARAJA_B2C_RESULT_URL: str | None = _env("PLATFORM_DARAJA_B2C_RESULT_URL")
    PLATFORM_DARAJA_B2C_TIMEOUT_URL: str | None = _env("PLATFORM_DARAJA_B2C_TIMEOUT_URL")

    # Comma-separated CIDR ranges allowed to hit /api/webhooks/daraja/*. Empty =
    # allow all (local dev / testing). Production sets Safaricom's published
    # callback IP ranges. See MPESA_INTEGRATION_SPEC.md §10.
    DARAJA_ALLOWED_IPS: str = _env("DARAJA_ALLOWED_IPS", "")
    TRUST_PROXY: bool = _env("TRUST_PROXY", "false").lower() in ("1", "true", "yes", "on")

    # When True (default until the paybill/initiator credentials above are fully
    # wired), STK push, C2B, and B2C are all SIMULATED: no external Daraja call is
    # made, the transaction is verified synchronously as if Safaricom had just
    # called back with success, and — because commission accrual
    # (services/affiliate_service.py) only ever fires off a VERIFIED
    # BillingTransaction — the whole affiliate pipeline is exercisable in dev/test
    # without a live paybill. Set MPESA_SIMULATION_MODE=false to switch to real
    # calls; nothing else changes. Mirrors COMMS_SIMULATION_MODE's contract exactly.
    MPESA_SIMULATION_MODE: bool = _env("MPESA_SIMULATION_MODE", "true").lower() in ("1", "true", "yes", "on")

    # ------------------------------------------------------------------
    # eTIMS / KRA compliance layer
    # ------------------------------------------------------------------
    # Platform kill switch for the whole manual-first eTIMS layer
    # (SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §2.3). ON by default because the
    # feature is already opt-in per property and invisible until a landlord
    # enables it — this switch exists so a bad deploy can be shut off without
    # database access. It WINS over platform_settings.etims_features_enabled.
    #
    # This layer never calls KRA. Landlords issue invoices through KRA's own
    # free channels and type the resulting numbers back in; nothing here
    # generates, validates against, or transmits to eTIMS.
    ETIMS_FEATURES_ENABLED: bool = _env("ETIMS_FEATURES_ENABLED", "true").lower() in ("1", "true", "yes", "on")

    # ------------------------------------------------------------------
    # Swagger — flasgger UI  (§2 API Docs)
    # ------------------------------------------------------------------
    SWAGGER: dict = {
        "title": "SahilPay API",
        "uiversion": 3,
        "specs_route": "/api/docs/",
        "version": "1.0.0",
        "description": (
            "SahilPay Property Management & Rent Collection Platform — "
            "Admin / Landlord-PM / Team Member / Tenant portals."
        ),
        "termsOfService": "",
        "contact": {"email": "hello@sahilpay.co.ke"},
    }

    # ------------------------------------------------------------------
    # Business defaults — mirror models.py §2 enum vocabularies exactly
    # ------------------------------------------------------------------

    # Tax: default 7.50 % — property and unit inherit this if not overridden.
    DEFAULT_TAX_RATE: Decimal = Decimal("7.50")

    # Trial: how many free days a new landlord gets (admin can override per account).
    DEFAULT_TRIAL_DAYS: int = int(_env("DEFAULT_TRIAL_DAYS", "30"))

    # Locale/finance defaults for new landlord accounts.
    DEFAULT_CURRENCY: str = "KES"
    DEFAULT_TIMEZONE: str = "Africa/Nairobi"

    # SMS purchase minimum (100 credits).
    MIN_SMS_PURCHASE: int = 100

    # Alert threshold: warn landlord when SMS balance drops below this.
    LOW_SMS_THRESHOLD_DEFAULT: int = 50

    # Pagination defaults; MAX_PAGE_SIZE caps per_page on list endpoints.
    DEFAULT_PAGE_SIZE: int = 25
    MAX_PAGE_SIZE: int = 100

    # Subscription billing discounts per plan length (spec §4.21).
    #   monthly  →  0 %   (no discount)
    #   quarterly → 10 %  off
    #   annual    → 15 %  off
    DISCOUNTS: dict[str, Decimal] = {
        "monthly": Decimal("0.00"),
        "quarterly": Decimal("0.10"),
        "annual": Decimal("0.15"),
    }


# ---------------------------------------------------------------------------
# Development configuration
# ---------------------------------------------------------------------------

class DevelopmentConfig(BaseConfig):
    """
    Local development.  DEBUG is on; the dev secret-key fallback is accepted;
    all third-party services can be mocked or pointed at sandboxes.
    """
    APP_ENV: str = "development"
    DEBUG: bool = True

    # Don't lock developers out before SendGrid is configured. Set
    # ENFORCE_EMAIL_VERIFICATION=true in the environment to test the gated flow locally.
    ENFORCE_EMAIL_VERIFICATION: bool = _env("ENFORCE_EMAIL_VERIFICATION", "false").lower() in ("1", "true", "yes", "on")

    # In dev, Vite frequently lands on a different port than 5173 (e.g. 5174,
    # 5175) when an earlier dev server is still holding 5173 — and it may be
    # reached via either `localhost` or `127.0.0.1`. Rather than maintain an
    # exact allowlist that breaks on every port bump, accept ANY localhost /
    # 127.0.0.1 port in development only. These are regex patterns (Flask-CORS
    # matches origins with re.match). Production keeps BaseConfig's strict,
    # env-driven exact-origin list.
    CORS_ORIGINS: list[str] = [
        r"http://localhost:\d+$",
        r"http://127\.0\.0\.1:\d+$",
    ]

    # Slightly longer token expiry for developer convenience.
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(hours=2)

    # Run Celery tasks (.delay()) inline, synchronously, in-process — so OTP/
    # invoice-generation/export tasks work without a separate `celery worker`
    # process during local testing. Mirrors TestingConfig's setting.
    CELERY_TASK_ALWAYS_EAGER: bool = True


# ---------------------------------------------------------------------------
# Testing configuration
# ---------------------------------------------------------------------------

class TestingConfig(BaseConfig):
    """
    Automated test suite.  Uses a separate test database, disables rate limiting,
    runs Celery tasks synchronously (ALWAYS_EAGER), and uses short token expiry
    to test expiry paths cheaply.
    """
    APP_ENV: str = "testing"
    DEBUG: bool = False
    TESTING: bool = True

    # Isolated test DB (must be created manually or by fixtures).
    SQLALCHEMY_DATABASE_URI: str = _normalize_db_url(
        _env("TEST_DATABASE_URL", "postgresql+psycopg2://sahilpay:sahilpay@localhost:5432/sahilpay_test")
    )

    # Run Celery tasks in-process without a broker — essential for unit tests.
    CELERY_TASK_ALWAYS_EAGER: bool = True

    # Disable rate limiting so tests are not throttled.
    RATELIMIT_ENABLED: bool = False

    # NEVER let the test suite reach the real image CDN. The developer .env
    # carries live Cloudinary credentials, and the account is on a metered free
    # tier — a full test run uploading maintenance photos and logos would spend
    # the month's credits silently, and leave orphaned assets behind. Blanked
    # here rather than relied upon in each test, so a new test that uploads an
    # image cannot reintroduce the leak. Uploads fall back to local disk, which
    # is what the storage tests assert against anyway.
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    CLOUDINARY_URL: str = ""

    # Short token windows to test expiry in a single test run.
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(seconds=10)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(minutes=5)

    # Use a throwaway secret key so test token payloads are deterministic.
    SECRET_KEY: str = "testing-secret-key-not-for-production"
    JWT_SECRET_KEY: str = "testing-secret-key-not-for-production"

    # SQLite in-memory is NOT used — we stay on PostgreSQL so Numeric types and
    # constraints behave identically to production.


# ---------------------------------------------------------------------------
# Production configuration
# ---------------------------------------------------------------------------

class ProductionConfig(BaseConfig):
    """
    Production / staging.  Secrets MUST be present in the environment or the
    app refuses to start.  DEBUG is always False.  Error details are never
    leaked in HTTP responses.
    """
    APP_ENV: str = "production"
    DEBUG: bool = False
    IS_PRODUCTION: bool = True
    PROPAGATE_EXCEPTIONS: bool = False  # let error handlers render clean JSON

    def __init_subclass__(cls, **kwargs):  # pragma: no cover
        super().__init_subclass__(**kwargs)

    @classmethod
    def _validate(cls):  # pragma: no cover
        """Raise if mandatory production secrets are absent.  Called by get_config()."""
        _require("SECRET_KEY", "production Flask secret key")
        _require("DATABASE_URL", "production PostgreSQL connection string")
        _require("JWT_SECRET_KEY", "production JWT signing key")
        _require("REDIS_URL", "production Redis URL for Celery / rate-limiter")
        _require("SENDGRID_API_KEY", "transactional email")
        _require("FIELD_ENCRYPTION_KEY", "encryption key for two-factor secrets at rest")
        # Cloud file/image storage is OPTIONAL for v1. When Cloudinary / AWS S3
        # credentials are absent, services/storage_service.py transparently falls
        # back to local-disk storage under server/uploads/ (served by app.py's
        # /uploads route), and the unused Cloudinary image helper is never called.
        # Set these later to move file storage off the VPS with no code change.
        if not _env("CLOUDINARY_CLOUD_NAME"):
            logger.warning("CLOUDINARY_CLOUD_NAME not set — property/maintenance images "
                           "would use local disk if that feature is wired up.")
        if not _env("AWS_ACCESS_KEY_ID"):
            logger.warning("AWS_ACCESS_KEY_ID not set — uploaded documents/receipts are "
                           "stored on local disk (server/uploads/). Ensure it's backed up.")
        _require("PLATFORM_DARAJA_CONSUMER_KEY", "M-Pesa Daraja integration")
        if not _env("MPESA_SIMULATION_MODE", "true").lower() in ("1", "true", "yes", "on"):
            _require("PLATFORM_DARAJA_PASSKEY", "M-Pesa STK Push (simulation mode is off)")

    # Override database URI from validated env
    SQLALCHEMY_DATABASE_URI: str = _normalize_db_url(
        _env("DATABASE_URL", "")
    )
    SECRET_KEY: str = _env("SECRET_KEY", "")
    JWT_SECRET_KEY: str = _env("JWT_SECRET_KEY") or _env("SECRET_KEY", "")


# ---------------------------------------------------------------------------
# Registry + factory
# ---------------------------------------------------------------------------

config_by_name: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None) -> type[BaseConfig]:
    """
    Return the config class for *name*.

    Resolution order:
        1. Explicit argument (if not None).
        2. APP_ENV environment variable.
        3. FLASK_ENV environment variable (legacy Flask convention).
        4. Falls back to "development".

    For production configs, also calls _validate() to fail fast on missing
    required environment variables.
    """
    if name is None:
        name = _env("APP_ENV") or _env("FLASK_ENV") or "development"

    name = name.lower().strip()
    cfg = config_by_name.get(name, DevelopmentConfig)

    if cfg is ProductionConfig:
        ProductionConfig._validate()  # pragma: no cover

    return cfg