"""
routes/tutorial_routes.py — Help & Tutorials, reader side
Blueprint: tutorial_bp  |  Prefix: /api/tutorials

Read-only, available to every signed-in role. Publication state and role
visibility are both enforced server-side (services/tutorial_service.py), so an
unpublished draft or an article aimed at landlords is not merely hidden from a
tenant's navigation — it is not in the response at all.

Bodies arrive as finished, sanitised HTML. The client never parses markdown.
"""

from flask import Blueprint
from flask_jwt_extended import jwt_required, get_jwt

from services import tutorial_service as tutorials
from utils import success

tutorial_bp = Blueprint("tutorials", __name__, url_prefix="/api/tutorials")


def _role() -> str | None:
    """
    The reader's role, from the token claims.

    Caretakers are team members with a `caretaker` preset rather than a distinct
    user role, so an article aimed at caretakers is authored for `team_member`
    and the preset only narrows what they see elsewhere in the product.
    """
    return (get_jwt() or {}).get("role")


@tutorial_bp.route("", methods=["GET"])
@jwt_required()
def list_tutorials():
    """Published categories with their articles, filtered to the caller's role."""
    return success({"categories": tutorials.published_categories(_role())})


@tutorial_bp.route("/<slug>", methods=["GET"])
@jwt_required()
def get_article(slug: str):
    """One published article, rendered to sanitised HTML."""
    return success(tutorials.published_article(slug, _role()))
