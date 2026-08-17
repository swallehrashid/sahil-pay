"""
routes/team_routes.py — Team Member Management (Landlord Side)
Blueprint: team_bp  |  Prefix: /api/team

This is the ADMIN side of team members — the landlord creating and
managing sub-accounts.  Team members' own session routes (profile,
permissions lookup) live in teammember_routes.py.

Create flow:
  1. Create User row (role=team_member) with a system-generated TEMPORARY password,
     is_active=True, is_verified=True, must_change_password=True.
  2. Create TeamMember row (is_active=True).
  3. Email the member their credentials (email, username, temp password) + how to log
     in and change the password. They log in normally; the frontend forces a password
     change on first login, which clears must_change_password.

Permission matrix: one TeamMemberPermission row per (team_member, module).
If can_edit=True → can_view is forced True at the app level.

Property access: TeamMemberPropertyAccess rows when property_access_all=False.
"""

import secrets

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    TeamMember, TeamMemberPermission, TeamMemberPropertyAccess,
    User, Property, UserRole, Landlord, PermissionModule,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service   import record_audit
from services import report_access
from services.email_service   import send_team_credentials_email
from services.team_preset_service import (
    PRESETS, apply_preset_permissions, normalise_preset, to_public_list,
)

team_bp = Blueprint("team", __name__, url_prefix="/api/team")

# Characters for temporary passwords — unambiguous (no O/0, I/l/1) so they're
# easy to type from an email, with at least one symbol to satisfy strength checks.
_TEMP_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def _generate_temp_password(length: int = 12) -> str:
    """A random, reasonably strong temporary password (always includes a symbol)."""
    core = "".join(secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length - 2))
    # Guarantee a digit and a symbol so it passes any min-strength rule.
    return core + secrets.choice("23456789") + secrets.choice("@#%&*?")


# ---------------------------------------------------------------------------
# GET /api/team/presets
# ---------------------------------------------------------------------------
@team_bp.route("/presets", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def list_presets():
    """
    The role-preset catalogue (owner / caretaker / accountant / secretary /
    custom) with the permission rows each one grants.

    The client renders these as one-click starting points when creating a team
    member; serving them from here keeps the frontend and backend definitions
    from drifting apart.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      200: {description: Preset catalogue.}
    """
    return jsonify({"presets": to_public_list()}), 200


# ---------------------------------------------------------------------------
# GET /api/team/report-catalogue
# ---------------------------------------------------------------------------
@team_bp.route("/report-catalogue", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def report_catalogue():
    """
    The reports that can be granted individually, for the permission matrix.

    Served from the backend for the same reason the presets are: the client
    rendering its own copy of this list is how a report ends up grantable in the
    UI but ungated on the route, or gated on a key the UI never offers.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      200: {description: Grantable report catalogue.}
    """
    return jsonify({"reports": report_access.catalogue()}), 200


# ---------------------------------------------------------------------------
# GET /api/team/
# ---------------------------------------------------------------------------
@team_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def list_team_members():
    """
    List all team members for this landlord.
    Returns each member's role, active status, and brief permission summary.
    Filters: ?is_active=true|false, ?role=, ?preset=, ?search= (username/name/phone)
    Paginated: ?page=, ?per_page= (default 20, max 100).

    A property manager runs one team member per owner plus two per block, so
    this list reaches the high hundreds — it is paginated, and the permission /
    property-access rows are eager-loaded to keep it at a constant few queries
    instead of 2 per member.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      200: {description: Team member list.}
    """
    from sqlalchemy.orm import selectinload

    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page     = min(request.args.get("per_page", 20, type=int), 100)

    query = (
        TeamMember.query
        .options(
            selectinload(TeamMember.permissions),
            selectinload(TeamMember.property_accesses),
        )
        .filter_by(landlord_id=landlord_id)
    )

    if v := request.args.get("is_active"):
        query = query.filter(TeamMember.is_active == (v.lower() == "true"))
    if v := request.args.get("role"):
        query = query.filter(TeamMember.role == v)
    if v := request.args.get("preset"):
        query = query.filter(TeamMember.preset == v)
    if v := (request.args.get("search") or "").strip():
        like = f"%{v}%"
        query = query.filter(db.or_(
            TeamMember.username.ilike(like),
            TeamMember.first_name.ilike(like),
            TeamMember.last_name.ilike(like),
            TeamMember.phone.ilike(like),
        ))

    paginated = query.order_by(TeamMember.username).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for tm in paginated.items:
        d = tm.to_dict()
        d["permissions"] = [p.to_dict() for p in tm.permissions]
        d["property_access"] = (
            "all" if tm.property_access_all
            else [a.property_id for a in tm.property_accesses]
        )
        items.append(d)

    return jsonify({
        "team_members": items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/team/
# ---------------------------------------------------------------------------
@team_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def create_team_member():
    """
    Create a new team member.
    Required: email, username, role.
    Optional: first_name, last_name, phone, property_access_all (default False).

    A welcome email is sent with their login credentials (email, username and a
    temporary password). They log in immediately and are forced to change the
    password on first login.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      201: {description: Team member created. Credentials email sent.}
      400: {description: Email already in use or validation error.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    email    = (data.get("email") or "").strip().lower()
    username = (data.get("username") or "").strip()
    preset   = normalise_preset(data.get("preset"))
    # A preset carries a sensible viewer/editor role; an explicit role still wins.
    role     = data.get("role") or (PRESETS[preset]["role"] if preset else None)

    if not email or not username:
        return jsonify({"error": "email and username are required."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists."}), 400

    # System-issued temporary password the member must change on first login.
    temp_password = _generate_temp_password()

    # The member must confirm the address before the temp password works. The
    # landlord types that address from memory or off a scrap of paper, so a
    # typo would otherwise mail working credentials to a stranger and leave the
    # real colleague locked out with no signal that anything went wrong.
    # One click on the emailed link both verifies and takes them to sign in.
    verification_token = secrets.token_urlsafe(32)

    user = User(
        email                = email,
        phone                = data.get("phone"),
        password_hash        = generate_password_hash(temp_password),
        role                 = UserRole.team_member.value,
        is_verified          = False,
        is_active            = True,
        must_change_password = True,
        verification_token   = verification_token,
    )
    db.session.add(user)
    db.session.flush()

    tm = TeamMember(
        user_id             = user.id,
        landlord_id         = landlord_id,
        username            = username,
        first_name          = data.get("first_name"),
        last_name           = data.get("last_name"),
        phone               = data.get("phone"),
        role                = role,
        preset              = preset,
        property_access_all = data.get("property_access_all", False),
        activation_token    = None,
        is_active           = True,
    )
    db.session.add(tm)
    db.session.flush()

    # A preset bootstraps the permission matrix so creating 100 owner logins or
    # 200 caretakers doesn't mean ticking 12 modules each. Everything it sets
    # stays editable afterwards via PUT /api/team/<id>/permissions.
    if preset:
        apply_preset_permissions(tm, preset)

    db.session.commit()

    # Email the member their credentials + change-password instructions.
    landlord = db.session.get(Landlord, landlord_id)
    company_name = landlord.company_name if landlord else None
    send_team_credentials_email.delay(
        email, username, temp_password,
        first_name=data.get("first_name"),
        company_name=company_name,
        verification_token=verification_token,
    )

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_team_member",
        entity_type="team_member",
        entity_id=tm.id,
        description=f"Team member '{username}' ({email}) created. Credentials email sent.",
        after_data=tm.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message":     "Team member created. A welcome email with login details has been sent.",
        "team_member": tm.to_dict(),
    }), 201


# ---------------------------------------------------------------------------
# GET /api/team/<id>
# ---------------------------------------------------------------------------
@team_bp.route("/<int:member_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def get_team_member(member_id):
    """
    Return full detail for one team member including permission matrix
    and property access list.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      200: {description: Team member detail.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    tm          = _get_or_404(landlord_id, member_id)

    d = tm.to_dict()
    d["email"]       = tm.user.email if tm.user else None
    d["permissions"] = [p.to_dict() for p in tm.permissions]
    d["property_access"] = (
        "all" if tm.property_access_all
        else [a.to_dict() for a in tm.property_accesses]
    )
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/team/<id>
# ---------------------------------------------------------------------------
@team_bp.route("/<int:member_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def update_team_member(member_id):
    """
    Update a team member's editable fields (name, role, phone, access flag).
    Does NOT update permissions or property access — use the dedicated endpoints.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      200: {description: Team member updated.}
    """
    landlord_id = get_current_landlord_id()
    tm          = _get_or_404(landlord_id, member_id)
    data        = request.get_json(silent=True) or {}
    before      = tm.to_dict()

    for field in ["first_name", "last_name", "phone", "role",
                  "username", "property_access_all"]:
        if field in data:
            setattr(tm, field, data[field])

    # Changing the preset re-labels the member. It only rewrites the permission
    # matrix when the caller explicitly asks (apply_preset_permissions: true) —
    # otherwise a rename would silently wipe permissions the landlord hand-tuned.
    if "preset" in data:
        tm.preset = normalise_preset(data["preset"])
        if tm.preset and data.get("apply_preset_permissions"):
            apply_preset_permissions(tm, tm.preset)

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_team_member",
        entity_type="team_member",
        entity_id=tm.id,
        description=f"Team member '{tm.username}' updated.",
        before_data=before,
        after_data=tm.to_dict(),
    )
    db.session.commit()
    return jsonify(tm.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/team/<id>
# ---------------------------------------------------------------------------
@team_bp.route("/<int:member_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def delete_team_member(member_id):
    """
    Remove a team member. Cascades to permissions and property access rows.
    The underlying User record is deactivated (is_active=False) rather than deleted.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      200: {description: Team member removed.}
    """
    landlord_id = get_current_landlord_id()
    tm          = _get_or_404(landlord_id, member_id)
    before      = tm.to_dict()

    # Deactivate user record
    if tm.user:
        tm.user.is_active = False

    # Cascade handled by ORM (cascade="all, delete-orphan" on permissions + property_accesses)
    db.session.delete(tm)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_team_member",
        entity_type="team_member",
        entity_id=member_id,
        description=f"Team member '{before.get('username')}' removed.",
        before_data=before,
    )
    db.session.commit()
    return jsonify({"message": "Team member removed."}), 200


# ---------------------------------------------------------------------------
# PUT /api/team/<id>/permissions
# ---------------------------------------------------------------------------
@team_bp.route("/<int:member_id>/permissions", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def set_permissions(member_id):
    """
    Replace the full permission matrix for a team member.
    Body:
      { permissions: [{ module: str, can_view: bool, can_edit: bool,
                        allowed_reports?: [str] | null }] }

    allowed_reports applies to the `reports` row only and answers "which
    reports", not "whether reports". Omit it (or send null) for every report;
    send a list of keys from services/report_access.REPORT_KEYS to narrow it;
    send [] for none. null and [] are different on purpose.

    Modules — the PermissionModule enum ONLY: payments, invoices, utilities,
    unit_utilities, tenants, units, properties, messages, expenses,
    maintenance, reports, groups. Anything else is rejected with 400.
    ("settings" is deliberately NOT grantable — it is the marker landlord-only
    routes guard themselves with; see the validation below.)

    App rule: if can_edit=True → can_view is forced True.
    Existing rows for modules NOT in the payload are left unchanged.
    Send the full desired matrix to replace everything.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      200: {description: Permissions updated.}
    """
    landlord_id  = get_current_landlord_id()
    tm           = _get_or_404(landlord_id, member_id)
    data         = request.get_json(silent=True) or {}
    perms_data   = data.get("permissions", [])

    # Delete all existing permission rows then re-insert
    TeamMemberPermission.query.filter_by(team_member_id=tm.id).delete()

    valid_modules = {m.value for m in PermissionModule}

    inserted = []
    for p in perms_data:
        module    = p.get("module")
        can_edit  = bool(p.get("can_edit", False))
        can_view  = True if can_edit else bool(p.get("can_view", False))
        if not module:
            continue
        # Only real PermissionModule values may be granted. Without this check a
        # landlord could POST a made-up module — notably "settings", the marker
        # the landlord-only routes (billing, account profile, team management)
        # guard themselves with — and hand a team member the keys to the
        # account's money. Unknown modules are rejected outright rather than
        # silently dropped, so a typo surfaces instead of quietly granting less.
        if module not in valid_modules:
            db.session.rollback()
            return jsonify({
                "error": f"Unknown permission module '{module}'.",
                "valid_modules": sorted(valid_modules),
            }), 400
        row = TeamMemberPermission(
            team_member_id = tm.id,
            module         = module,
            can_view       = can_view,
            can_edit       = can_edit,
            # Only the reports row carries this; storing it elsewhere would be
            # dead data that later reads as a restriction nobody set.
            allowed_reports = (
                report_access.normalise(p.get("allowed_reports"))
                if module == "reports" else None
            ),
        )
        db.session.add(row)
        inserted.append(row)

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_team_member_permissions",
        entity_type="team_member",
        entity_id=tm.id,
        description=f"Permission matrix updated for '{tm.username}'.",
        after_data={"permissions": [r.to_dict() for r in inserted]},
    )
    db.session.commit()
    return jsonify({"permissions": [r.to_dict() for r in inserted]}), 200


# ---------------------------------------------------------------------------
# PUT /api/team/<id>/property-access
# ---------------------------------------------------------------------------
@team_bp.route("/<int:member_id>/property-access", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def set_property_access(member_id):
    """
    Set the property scope for a team member.
    Body:
      { property_access_all: bool,
        property_ids: [int]   -- required when property_access_all=False }

    When property_access_all=True: clears all TeamMemberPropertyAccess rows
    (the @scope_to_accessible_properties decorator skips filtering for all-access members).
    When False: replaces the exact set of allowed properties.
    ---
    tags: [Team]
    security:
      - Bearer: []
    responses:
      200: {description: Property access updated.}
    """
    landlord_id   = get_current_landlord_id()
    tm            = _get_or_404(landlord_id, member_id)
    data          = request.get_json(silent=True) or {}
    access_all    = data.get("property_access_all", False)
    property_ids  = data.get("property_ids", [])

    # Clear existing access rows
    TeamMemberPropertyAccess.query.filter_by(team_member_id=tm.id).delete()

    tm.property_access_all = access_all

    if not access_all and property_ids:
        # Validate all property_ids belong to this landlord
        valid_props = Property.query.filter(
            Property.id.in_(property_ids),
            Property.landlord_id == landlord_id,
            Property.is_deleted.is_(False),
        ).all()
        for prop in valid_props:
            db.session.add(TeamMemberPropertyAccess(
                team_member_id = tm.id,
                property_id    = prop.id,
            ))

    db.session.commit()

    accesses = TeamMemberPropertyAccess.query.filter_by(team_member_id=tm.id).all()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_team_member_property_access",
        entity_type="team_member",
        entity_id=tm.id,
        description=(
            f"Property access updated for '{tm.username}': "
            f"{'all properties' if access_all else f'{len(accesses)} properties'}."
        ),
        after_data={"property_access_all": access_all, "property_ids": property_ids},
    )
    db.session.commit()

    return jsonify({
        "property_access_all": tm.property_access_all,
        "property_accesses":   [a.to_dict() for a in accesses],
    }), 200


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, member_id: int) -> TeamMember:
    tm = TeamMember.query.filter_by(id=member_id, landlord_id=landlord_id).first()
    if not tm:
        abort(404, description="Team member not found.")
    return tm