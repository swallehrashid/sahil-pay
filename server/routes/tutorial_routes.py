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


def _role():
    """
    The set of audience labels this reader matches.

    Caretakers are team members carrying a `caretaker` preset rather than a
    distinct user role, so the preset is loaded here and folded into the label
    set — otherwise an article addressed to "Caretakers" in the admin CMS
    reaches nobody at all. A system_admin matches every audience so the reader
    view previews exactly what each role will get.
    """
    claims = get_jwt() or {}
    role = claims.get("role")

    preset = None
    if role == "team_member" and claims.get("team_member_id"):
        from extensions import db
        from models import TeamMember

        preset = (
            db.session.query(TeamMember.preset)
            .filter(TeamMember.id == claims["team_member_id"])
            .scalar()
        )

    return tutorials.effective_roles(role, preset)


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
