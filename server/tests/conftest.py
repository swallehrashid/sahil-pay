"""
Pytest fixtures for the SahilPay backend.

Each test gets a fresh app context — and therefore a fresh
db.session (Flask-SQLAlchemy scopes the session to the app context, see
extensions.py) — and NEVER commits, only flushes (mirroring the
services/*_service.py contract: flush, let the caller commit). Rolling back
+ removing that session at teardown discards everything the test wrote, so
sahilpay_test stays clean across runs without needing a savepoint dance.

IMPORTANT: models.py builds on a plain declarative Base, and extensions.py
wires `Base.query = db.session.query_property()` ONCE at import time. That
binds Model.query to the scoped_session object that exists at that moment —
reassigning db.session later (the classic Flask-SQLAlchemy test recipe of
swapping in a connection-bound session) would leave Model.query pointed at
the wrong session and silently return empty results. So don't do that here;
rely on the app-context scoping instead.

Requires the sahilpay_test database to exist and be migrated:
    createdb -O sahilpay sahilpay_test
    APP_ENV=testing venv/bin/flask db upgrade

TROUBLESHOOTING — a wave of unrelated failures with
`UniqueViolation: duplicate key value violates unique constraint "users_email_key"`
(or similar) means sahilpay_test has COMMITTED leftovers in it. The fixture
below only rolls back, so anything a test (or a stray seed.py run pointed at
this database) committed will survive and collide on the next run. It is not a
code defect. Recreate the database and the suite goes green again:

    psql -d postgres -c "DROP DATABASE IF EXISTS sahilpay_test;"
    psql -d postgres -c "CREATE DATABASE sahilpay_test OWNER sahilpay;"
    APP_ENV=testing venv/bin/flask db upgrade

Never run seed.py without DATABASE_URL explicitly set — it defaults to the DEV
database, and a mistyped override can land it on sahilpay_test.
"""

import os

os.environ["APP_ENV"] = "testing"

import pytest

from app import create_app
from extensions import db as _db


@pytest.fixture(scope="session")
def app():
    application = create_app()
    return application


@pytest.fixture()
def db_session(app):
    with app.app_context():
        yield _db.session
        _db.session.rollback()
        _db.session.remove()
