"""
routes/preference_routes.py — per-user UI stickiness
Blueprint: preference_bp  |  Prefix: /api/preferences

A tiny JSON scratchpad per user, for things the interface should REMEMBER but
that carry no business meaning: whether "Include eTIMS invoice numbers" was
ticked last time, which one-time nudge cards have been dismissed.

Deliberately not a settings endpoint. Nothing stored here may change what a
document contains, what a figure computes to, or who can see what — so it needs
no permission model beyond "you may only touch your own row", and an unknown
key simply reads back as whatever default the caller supplies.
"""

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from extensions import db
from models import UserPreference
from utils import ApiError, get_jwt_user, success

preference_bp = Blueprint("preferences", __name__, url_prefix="/api/preferences")

# Bounded so a bug in the client can't turn this into unbounded user-writable
# storage on the money database.
MAX_KEYS = 100
MAX_VALUE_CHARS = 2000


def _row_for_current_user() -> UserPreference:
    user = get_jwt_user()
    row = UserPreference.query.filter_by(user_id=user.id).first()
    if row is None:
        row = UserPreference(user_id=user.id, preferences={})
        db.session.add(row)
        db.session.flush()
    return row


@preference_bp.route("", methods=["GET"])
@jwt_required()
def get_preferences():
    return success(_row_for_current_user().preferences or {})


@preference_bp.route("", methods=["PATCH"])
@jwt_required()
def update_preferences():
    """
    Shallow-merge the posted keys. Sending null for a key removes it, which is
    how a dismissed nudge gets un-dismissed in support scenarios.
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ApiError("Preferences must be an object.", status=422)

    row = _row_for_current_user()
    # Re-assigned rather than mutated: SQLAlchemy does not track in-place edits
    # of a plain JSON column, so mutating would silently fail to persist.
    merged = dict(row.preferences or {})

    for key, value in data.items():
        if value is None:
            merged.pop(key, None)
            continue
        if len(str(value)) > MAX_VALUE_CHARS:
            raise ApiError(f"Preference '{key}' is too large.", status=422)
        merged[key] = value

    if len(merged) > MAX_KEYS:
        raise ApiError("Too many stored preferences.", status=422)

    row.preferences = merged
    db.session.commit()
    return success(row.preferences, message="Saved.")
