"""
SahilPay — extensions.py
========================
All Flask extension singletons are defined *unbound* here (no app passed).
`app.py`'s `create_app()` binds them with `ext.init_app(app)`.

WHY UNBOUND?
  Avoids the circular-import cycle:
    config.py → (no Flask imports)
    extensions.py → imports config-independent extension classes only
    models.py → imports Base from SQLAlchemy only
    app.py → imports all three, wires them together

CRITICAL — reconciling plain declarative Base with Flask-SQLAlchemy:
  `models.py` defines its schema on `Base = declarative_base()`, not `db.Model`.
  We share Base.metadata with Flask-SQLAlchemy so Flask-Migrate / Alembic can
  see every table without rebasing the models:

      db = SQLAlchemy(
          metadata=Base.metadata,
          session_options={"query_cls": SoftDeleteQuery},
      )

  Consequence: ALL queries must use `db.session.query(Model)` — never
  `Model.query` (that shortcut requires db.Model inheritance).
  To include soft-deleted rows:
      db.session.query(Tenant).execution_options(include_deleted=True)

CELERY NOTE:
  The Celery instance is NOT created here because it requires app config
  (broker URL, result backend).  It lives in `app.py::make_celery(app)`.
  The worker entrypoint (`celery_app.py`, created later) calls make_celery
  and exposes the bound instance for `celery -A celery_app worker ...`.
"""

from flask_cors import CORS                     # CORS — cross-origin requests (§2 Frontend)
from flask_jwt_extended import JWTManager       # JWT — stateless auth (§2 Auth & Security)
from flask_limiter import Limiter               # Rate limiting (§2 Auth & Security)
from flask_limiter.util import get_remote_address
from flask_marshmallow import Marshmallow       # Marshmallow integration (§2 Validation)
from flask_migrate import Migrate               # Alembic migrations (§2 ORM & Migrations)
from flask_sqlalchemy import SQLAlchemy         # PostgreSQL ORM (§2 Database)
from flasgger import Swagger                    # OpenAPI / Swagger UI (§2 API Docs)

# Import Base and SoftDeleteQuery from models — the ONLY models import in
# this file.  Everything else is wired in app.py after the app is created.
from models import Base, SoftDeleteQuery


# ---------------------------------------------------------------------------
# Database — PostgreSQL, ACID-compliant financial ledger
# ---------------------------------------------------------------------------
# metadata=Base.metadata → every table declared on Base is visible to
#     db.create_all(), Flask-Migrate, and Alembic autogenerate without
#     any model rebasing.
# query_cls=SoftDeleteQuery → activates automatic soft-delete filtering
#     on all session queries for models that carry is_deleted.
# ---------------------------------------------------------------------------
db = SQLAlchemy(
    metadata=Base.metadata,
    session_options={"query_cls": SoftDeleteQuery},
)

# Every route file uses the Flask-SQLAlchemy `Model.query` shortcut (e.g.
# Property.query.filter_by(...)), but models.py builds on a plain declarative
# Base, not db.Model, so that attribute doesn't exist by default. This wires
# it up — query_property() is backed by db.session, so it picks up the same
# SoftDeleteQuery query_cls configured above.
Base.query = db.session.query_property()

# ---------------------------------------------------------------------------
# Flask-Migrate — Alembic wrapper (flask db migrate / flask db upgrade)
# ---------------------------------------------------------------------------
# Initialized with both app AND db inside create_app():
#   migrate.init_app(app, db)
# ---------------------------------------------------------------------------
migrate = Migrate()

# ---------------------------------------------------------------------------
# JWT — Flask-JWT-Extended  (stateless; §2 Auth & Security)
# ---------------------------------------------------------------------------
# Callbacks (user_identity_loader, token_in_blocklist_loader, etc.)
# are registered in app.py, NOT here, to avoid circular imports.
# ---------------------------------------------------------------------------
jwt = JWTManager()

# ---------------------------------------------------------------------------
# Rate limiter — Flask-Limiter  (§2 Auth & Security)
# ---------------------------------------------------------------------------
# key_func=get_remote_address keys limits by client IP.
# Storage URI (Redis) is set from app.config["RATELIMIT_STORAGE_URI"]
# during init_app().
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Marshmallow — request validation and serialization  (§2 Validation)
# ---------------------------------------------------------------------------
# Every money / financial write goes through a Marshmallow schema BEFORE
# the DB is touched.  No unvalidated writes to financial tables.
# ---------------------------------------------------------------------------
ma = Marshmallow()

# ---------------------------------------------------------------------------
# Swagger — flasgger OpenAPI 3 UI  (§2 API Docs)
# ---------------------------------------------------------------------------
# Template / config is supplied in app.py via app.config["SWAGGER"] so that
# the title/version/specs_route are driven by config, not hard-coded here.
# ---------------------------------------------------------------------------
swagger = Swagger()

# ---------------------------------------------------------------------------
# CORS — Flask-CORS  (§2 Frontend)
# ---------------------------------------------------------------------------
# Restricts cross-origin requests to origins listed in
# app.config["CORS_ORIGINS"].  Applied only to /api/* in create_app().
# ---------------------------------------------------------------------------
cors = CORS()