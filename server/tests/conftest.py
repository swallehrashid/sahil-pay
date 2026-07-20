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
