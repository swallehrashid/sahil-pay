"""
SahilPay — utils.py
====================
The shared toolbelt imported by every route, service, and Celery task.

Routes must stay thin:  validate → call a service → audit → return.
ALL cross-cutting concerns live here:

  §4.1  Response envelopes         success() / error() / ApiError
  §4.2  JSON serialization         to_json_safe()
  §4.3  Pagination                 paginate()
  §4.4  Passwords & tokens         hash_password / verify_password /
                                   generate_token / generate_otp / hash_otp
  §4.5  Current-user resolution    get_jwt_user() / current_landlord_id()
  §4.6  Guards / decorators        @require_role / @require_permission /
                                   @scope_to_accessible_properties
  §4.7  Audit — single chokepoint  audit() / model_snapshot()
  §4.8  Impersonation context      active_impersonation()
  §4.9  PDF + storage              render_pdf / render_template_pdf /
                                   upload_pdf / upload_image
  §4.10 Misc helpers               parse_date / month_str / gen_reference /
                                   enum_values / validate_enum /
                                   decrement_sms_balance

IMPORTANT: Permission-matrix logic and audit logic live HERE and nowhere else.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import string
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from functools import wraps
from io import BytesIO
from typing import Any

import boto3
import cloudinary
import cloudinary.uploader
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app, g, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)


# ===========================================================================
# §4.1 — Response envelopes
# ===========================================================================

class ApiError(Exception):
    """
    Raise anywhere in a route or service to short-circuit with a clean JSON error.
    Registered as an error handler in app.py so it surfaces as an HTTP response.

    Usage:
        raise ApiError("Tenant not found", status=404)
        raise ApiError("Validation failed", status=422, errors={"phone": "required"})
    """

    def __init__(
        self,
        message: str,
        status: int = 400,
        errors: dict | list | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.errors = errors
        self.code = code


def success(
    data: Any = None,
    message: str | None = None,
    meta: dict | None = None,
    status: int = 200,
) -> tuple:
    """
    Standard success envelope.

    Returns:
        ({success: True, data: ..., message: ..., meta: ...}, status_code)
    """
    payload: dict[str, Any] = {"success": True}
    if data is not None:
        payload["data"] = to_json_safe(data)
    if message is not None:
        payload["message"] = message
    if meta is not None:
        payload["meta"] = meta
    return jsonify(payload), status


def error(
    message: str,
    status: int = 400,
    errors: dict | list | None = None,
    code: str | None = None,
) -> tuple:
    """
    Standard error envelope.

    Returns:
        ({success: False, message: ..., errors: ..., code: ...}, status_code)
    """
    payload: dict[str, Any] = {"success": False, "message": message}
    if errors is not None:
        payload["errors"] = errors
    if code is not None:
        payload["code"] = code
    return jsonify(payload), status


# ===========================================================================
# §4.2 — JSON serialization
# ===========================================================================

def to_json_safe(obj: Any) -> Any:
    """
    Recursively convert an object so it is JSON-serializable.

    Rules (mirrors models._serialise):
      Decimal   → str   (money is ALWAYS a string, never a float)
      date      → ISO-8601 string  "YYYY-MM-DD"
      datetime  → ISO-8601 string  "YYYY-MM-DDTHH:MM:SS"
      Enum      → .value
      dict      → recurse values
      list/tuple → recurse elements
      everything else → passthrough (must be natively JSON-serializable)
    """
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    return obj


# ===========================================================================
# §4.3 — Pagination
# ===========================================================================

def paginate(query, page: int | None = None, per_page: int | None = None) -> tuple:
    """
    Apply limit/offset pagination to a SQLAlchemy query.

    When page / per_page are not passed they are read from request.args.
    per_page is clamped to current_app.config["MAX_PAGE_SIZE"].

    Returns:
        (items, meta_dict)
        meta = {page, per_page, total, total_pages, has_next, has_prev}
    """
    cfg_default = current_app.config.get("DEFAULT_PAGE_SIZE", 25)
    cfg_max = current_app.config.get("MAX_PAGE_SIZE", 100)

    if page is None:
        try:
            page = int(request.args.get("page", 1))
        except (TypeError, ValueError):
            page = 1

    if per_page is None:
        try:
            per_page = int(request.args.get("per_page", cfg_default))
        except (TypeError, ValueError):
            per_page = cfg_default

    # Clamp
    page = max(1, page)
    per_page = max(1, min(per_page, cfg_max))

    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    meta = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
    return items, meta


# ===========================================================================
# §4.4 — Passwords & tokens
# ===========================================================================

# Implementation note: werkzeug.security is used (ships with Flask) — no
# additional dependency.  Uses PBKDF2-HMAC-SHA256 with a random salt.

def hash_password(raw: str) -> str:
    """Return a bcrypt/pbkdf2 hash of *raw* suitable for storage."""
    return generate_password_hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """Return True if *raw* matches the stored *hashed* value."""
    return check_password_hash(hashed, raw)


def generate_token(nbytes: int = 32) -> str:
    """
    Generate a cryptographically secure, URL-safe random token.
    Used for email-verification, activation, and password-reset links.
    """
    return secrets.token_urlsafe(nbytes)


def generate_otp(length: int = 6) -> str:
    """
    Generate a numeric OTP of *length* digits.
    The plaintext is sent to the tenant via SMS / email; only the hash is stored.
    """
    return "".join(secrets.choice(string.digits) for _ in range(length))


def hash_otp(code: str) -> str:
    """
    One-way hash of an OTP code for safe storage in otp_tokens.code_hash.
    SHA-256 is sufficient here (short-lived, high-entropy token universe).
    """
    return hashlib.sha256(code.encode()).hexdigest()


# ===========================================================================
# §4.5 — Current-user resolution
# ===========================================================================

def get_jwt_user():
    """
    Resolve the current authenticated User from the JWT identity.

    - Reads `get_jwt_identity()` (stored as users.id int).
    - Loads the User with its role-specific profile.
    - Caches the result on flask.g for the duration of the request.
    - Raises ApiError(401) if the user is missing or inactive.

    Always use this inside a route that has @jwt_required().
    """
    # Cache on g so a single request makes at most one DB round-trip.
    if hasattr(g, "_jwt_user") and g._jwt_user is not None:
        return g._jwt_user

    from extensions import db
    from models import User

    user_id = get_jwt_identity()
    if not user_id:
        raise ApiError("Authentication required.", status=401, code="missing_identity")

    user = db.session.query(User).filter(
        User.id == user_id,
        User.is_active.is_(True),
    ).first()

    if user is None:
        raise ApiError("User account not found or deactivated.", status=401, code="inactive_user")

    g._jwt_user = user
    return user


def current_landlord_id() -> int | None:
    """
    Resolve the effective landlord_id scope for the current request.

    This is THE single function every landlord-scoped DB query uses
    to filter rows.  Never derive landlord_id from request body.

    Resolution order:
        1. System admin impersonating a landlord → impersonated landlord's id.
        2. Landlord / PM caller → their own landlords.id.
        3. Team member caller  → their team_member.landlord_id.
        4. Tenant / admin (non-impersonating) → None (no landlord scope).

    Callers that REQUIRE a landlord scope (almost all landlord routes)
    should raise ApiError(403) when None is returned.
    """
    # Check impersonation first (admin acting as a landlord). Demo mode is
    # never applied on this path — an admin impersonating a landlord always
    # sees that landlord's real account, regardless of any X-Demo-Mode header.
    imp = active_impersonation()
    if imp is not None:
        return imp.landlord_id

    user = get_jwt_user()
    role = user.role

    if role in ("landlord", "property_manager"):
        if user.landlord_profile is None:
            raise ApiError("Landlord profile not found.", status=500)
        return _demo_scope_or(user.landlord_profile.id)

    if role == "team_member":
        if user.team_member_profile is None:
            raise ApiError("Team member profile not found.", status=500)
        # Demo mode is landlord/PM-only (v1) — a team member's X-Demo-Mode
        # header (if ever sent) is ignored; they always see the real account.
        return user.team_member_profile.landlord_id

    # system_admin (non-impersonating) or tenant — no landlord scope
    return None


def _demo_scope_or(real_landlord_id: int) -> int:
    """
    See DEMO_MODE_SPEC.md §3.1. If the caller sent X-Demo-Mode: 1 and a demo
    shadow landlord exists for real_landlord_id, scope every query to the
    shadow instead. Cached on g per request (same pattern as
    active_impersonation()) since this is checked on every landlord-scoped
    query in a request.

    A header with no matching shadow silently falls back to the real
    landlord — this is only a stale-localStorage safety net (the frontend
    always calls POST /api/demo/enter, which creates the shadow, before ever
    setting the header), never a hard error.
    """
    if request.headers.get("X-Demo-Mode") != "1":
        return real_landlord_id

    cache_attr = "_demo_shadow_id"
    if hasattr(g, cache_attr):
        cached = getattr(g, cache_attr)
        return cached if cached is not None else real_landlord_id

    from models import Landlord

    shadow = Landlord.query.filter_by(demo_owner_landlord_id=real_landlord_id).first()
    setattr(g, cache_attr, shadow.id if shadow else None)
    return shadow.id if shadow else real_landlord_id


def is_demo_scope() -> bool:
    """
    True when the current request resolved to a demo shadow landlord (i.e.
    X-Demo-Mode was sent AND a shadow exists). Used to prefix audit
    descriptions with "[DEMO] " as defense-in-depth (the shadow's own
    landlord_id already isolates the row from the real account either way).
    """
    return getattr(g, "_demo_shadow_id", None) is not None


# ===========================================================================
# §4.6 — Guards / decorators  (THE security boundary — not the UI)
# ===========================================================================

def require_role(*roles: str):
    """
    Decorator: ensure the JWT caller's role is one of *roles*.

    Must be applied AFTER @jwt_required():

        @bp.route("/...")
        @jwt_required()
        @require_role("landlord", "team_member")
        def my_view(): ...

    Raises ApiError(403) on role mismatch.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_jwt_user()
            if user.role not in roles:
                raise ApiError(
                    f"Access denied. Required role(s): {', '.join(roles)}.",
                    status=403,
                    code="forbidden_role",
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_permission(module: str, action: str):
    """
    Decorator: enforce the team-member permission matrix.

    module  — one of models.PermissionModule values
              (payments, invoices, utilities, unit_utilities, tenants,
               units, properties, messages)
    action  — "view" or "edit"
              (can_edit=True implies can_view=True per spec §5)

    - landlord / property_manager / system_admin → pass-through (full access).
    - team_member → check team_member_permissions row for the module;
      raise ApiError(403) if the required flag is not set.

    This must be applied AFTER @jwt_required():

        @bp.route("/invoices", methods=["POST"])
        @jwt_required()
        @require_role("landlord", "property_manager", "team_member")
        @require_permission("invoices", "edit")
        def create_invoice(): ...
    """
    if action not in ("view", "edit"):
        raise ValueError(f"require_permission: action must be 'view' or 'edit', got '{action}'.")

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from extensions import db
            from models import TeamMember, TeamMemberPermission

            user = get_jwt_user()

            # Full-access roles: no permission check needed.
            if user.role in ("landlord", "property_manager", "system_admin"):
                return fn(*args, **kwargs)

            if user.role != "team_member":
                raise ApiError("Access denied.", status=403, code="forbidden_role")

            tm: TeamMember | None = user.team_member_profile
            if tm is None:
                raise ApiError("Team member profile not found.", status=403)

            perm: TeamMemberPermission | None = (
                db.session.query(TeamMemberPermission)
                .filter(
                    TeamMemberPermission.team_member_id == tm.id,
                    TeamMemberPermission.module == module,
                )
                .first()
            )

            if perm is None:
                raise ApiError(
                    f"You do not have access to the '{module}' module.",
                    status=403,
                    code="no_module_permission",
                )

            if action == "edit" and not perm.can_edit:
                raise ApiError(
                    f"You do not have edit permission for '{module}'.",
                    status=403,
                    code="no_edit_permission",
                )

            if action == "view" and not (perm.can_view or perm.can_edit):
                raise ApiError(
                    f"You do not have view permission for '{module}'.",
                    status=403,
                    code="no_view_permission",
                )

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def scope_to_accessible_properties(fn):
    """
    Decorator: when the caller is a team_member WITHOUT property_access_all,
    load their allowed property_ids from team_member_property_access and
    store them on flask.g as `g.accessible_property_ids` (a set of ints).

    List endpoints filter:
        if g.get('accessible_property_ids') is not None:
            query = query.filter(Property.id.in_(g.accessible_property_ids))

    For landlords, admins, or team_members with property_access_all=True,
    g.accessible_property_ids is set to None (no restriction).

    Apply AFTER @jwt_required():

        @bp.route("/properties")
        @jwt_required()
        @require_role("landlord", "team_member")
        @scope_to_accessible_properties
        def list_properties(): ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from extensions import db
        from models import TeamMember, TeamMemberPropertyAccess

        user = get_jwt_user()

        if user.role != "team_member":
            g.accessible_property_ids = None  # no restriction
            return fn(*args, **kwargs)

        tm: TeamMember | None = user.team_member_profile
        if tm is None or tm.property_access_all:
            g.accessible_property_ids = None
            return fn(*args, **kwargs)

        rows = (
            db.session.query(TeamMemberPropertyAccess)
            .filter(TeamMemberPropertyAccess.team_member_id == tm.id)
            .all()
        )
        g.accessible_property_ids = {row.property_id for row in rows}
        return fn(*args, **kwargs)
    return wrapper


# ===========================================================================
# §4.7 — Audit — single chokepoint
# ===========================================================================

def model_snapshot(instance) -> dict:
    """
    Capture a clean before/after dict from any model instance.
    Uses the model's own to_dict() method so the snapshot matches
    the API shape exactly.
    """
    if instance is None:
        return {}
    if hasattr(instance, "to_dict"):
        return instance.to_dict()
    return {}


def audit(
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    before: dict | None = None,
    after: dict | None = None,
    description: str | None = None,
    affected_properties: list | None = None,
    file_url: str | None = None,
) -> None:
    """
    Write one immutable audit_logs row.  EVERY create/update/delete route
    calls this — no exceptions, including admin and impersonation actions.

    Parameters
    ----------
    action          : short verb, e.g. "create_payment", "delete_tenant"
    entity_type     : must be a value in models.AuditEntityType
    entity_id       : PK of the affected row (nullable for bulk/platform acts)
    before          : dict snapshot before the change  (use model_snapshot())
    after           : dict snapshot after the change
    description     : human-readable summary
    affected_properties : list of property_ids affected (for cross-property acts)
    file_url        : if a file was uploaded as part of this action

    When an admin is impersonating a landlord:
    - actor_user_id stays as the admin's user.id
    - description includes "impersonating landlord <id>"
    - landlord_id is the impersonated landlord's id
    """
    from extensions import db
    from models import AuditEntityType, AuditLog

    # Validate entity_type is a known enum value.
    valid_types = {e.value for e in AuditEntityType}
    if entity_type not in valid_types:
        logger.warning("audit(): unknown entity_type '%s' — proceeding anyway.", entity_type)

    # Resolve actor — during request context.
    try:
        user = get_jwt_user()
        actor_user_id = user.id
        actor_username = getattr(user, "email", None) or str(user.id)
        # Build full name from whichever profile is present.
        full_name_parts = []
        for profile_attr in ("landlord_profile", "team_member_profile", "admin_profile"):
            profile = getattr(user, profile_attr, None)
            if profile:
                fn = getattr(profile, "first_name", None) or ""
                ln = getattr(profile, "last_name", None) or ""
                if fn or ln:
                    full_name_parts = [fn, ln]
                    break
        actor_full_name = " ".join(p for p in full_name_parts if p).strip() or None
    except Exception:
        # Outside request context (e.g. Celery task) — use a system actor sentinel.
        actor_user_id = None
        actor_username = "system"
        actor_full_name = "Automated System"

    # Resolve landlord scope (nullable for pure admin/platform acts).
    try:
        landlord_id = current_landlord_id()
    except Exception:
        landlord_id = None

    # Enrich description when impersonating.
    imp = active_impersonation()
    if imp is not None and description is not None:
        description = f"[Client support session — landlord #{imp.landlord_id}] {description}"
    elif imp is not None:
        description = f"[Client support session — landlord #{imp.landlord_id}]"

    # Defense-in-depth: mark demo-scope writes even though the shadow
    # landlord's own landlord_id already isolates the row (DEMO_MODE_SPEC §3.5).
    if is_demo_scope():
        description = f"[DEMO] {description}" if description else "[DEMO]"

    ip_address = None
    try:
        ip_address = request.remote_addr
    except RuntimeError:
        pass  # outside request context

    log = AuditLog(
        landlord_id=landlord_id,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        actor_full_name=actor_full_name,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        before_data=to_json_safe(before) if before else None,
        after_data=to_json_safe(after) if after else None,
        affected_properties=affected_properties,
        file_url=file_url,
        ip_address=ip_address,
    )
    db.session.add(log)
    # Note: caller is responsible for db.session.commit() — audit() is
    # called inside the same transaction as the mutating operation so both
    # succeed or both roll back together.


# ===========================================================================
# §4.8 — Impersonation context
# ===========================================================================

def active_impersonation():
    """
    For an admin caller, return the currently active (granted, non-expired)
    ImpersonationRequest if the admin is acting on behalf of a landlord.

    The impersonated landlord id may be conveyed via:
      - JWT claim  "impersonate_landlord_id"  (set on a special impersonation token)
      - Request header  X-Impersonate-Landlord  (for session-based impersonation)

    Returns None if:
      - caller is not system_admin
      - no impersonation header/claim present
      - no matching granted, non-expired row exists in impersonation_requests

    NEVER a silent backdoor — only an explicitly granted row is honored.
    Every action under impersonation is audit-logged with the admin as actor.
    """
    # Cache on g per request.
    if hasattr(g, "_active_impersonation"):
        return g._active_impersonation

    g._active_impersonation = None

    try:
        user = get_jwt_user()
    except Exception:
        return None

    if user.role != "system_admin":
        return None

    # Resolve impersonated landlord id from JWT claims or header.
    target_landlord_id: int | None = None
    try:
        claims = get_jwt()
        target_landlord_id = claims.get("impersonate_landlord_id")
    except Exception:
        pass

    if target_landlord_id is None:
        raw = request.headers.get("X-Impersonate-Landlord")
        if raw:
            try:
                target_landlord_id = int(raw)
            except (TypeError, ValueError):
                pass

    if target_landlord_id is None:
        return None

    from extensions import db
    from models import ImpersonationRequest, ImpersonationStatus

    now = datetime.utcnow()
    imp = (
        db.session.query(ImpersonationRequest)
        .filter(
            ImpersonationRequest.admin_user_id == user.id,
            ImpersonationRequest.landlord_id == target_landlord_id,
            ImpersonationRequest.status == ImpersonationStatus.granted.value,
            ImpersonationRequest.expires_at > now,
        )
        .first()
    )

    g._active_impersonation = imp
    return imp


# ===========================================================================
# §4.9 — PDF generation (WeasyPrint) + storage
# ===========================================================================

def _local_uploads_url_fetcher(url: str):
    """
    WeasyPrint URL fetcher that resolves the landlord's own uploaded assets
    (logo / signature / stamps) to files on local disk.

    When AWS/Cloudinary is not configured, storage_service returns a
    root-relative URL like "/uploads/logos/1/ab12_logo.png". WeasyPrint runs
    server-side with no HTTP origin, so such a URL would fail to fetch and the
    landlord's logo/signature would silently vanish from every PDF report and
    receipt. This maps any "/uploads/..." path (bare, or embedded in a full
    http(s)://host/uploads/... URL the frontend may have produced) to the real
    file under <app_root>/uploads/, and delegates everything else — data: URIs,
    genuine remote S3/Cloudinary URLs — to WeasyPrint's default fetcher.
    """
    from weasyprint import default_url_fetcher
    from urllib.parse import urlparse

    path = url
    if url.startswith(("http://", "https://")):
        path = urlparse(url).path  # keep only the path component

    marker = "/uploads/"
    if marker in path:
        rel = path.split(marker, 1)[1]
        disk_path = os.path.join(current_app.root_path, "uploads", rel)
        if os.path.isfile(disk_path):
            return default_url_fetcher("file://" + disk_path)

    return default_url_fetcher(url)


def render_pdf(html: str, base_url: str | None = None) -> bytes:
    """
    Render an HTML string to PDF bytes using WeasyPrint.

    Parameters
    ----------
    html      : Full HTML document string (with embedded CSS).
    base_url  : Optional base URL for resolving relative CSS/image URLs.
                Use current_app.root_path for template-based rendering.

    Returns
    -------
    bytes : Raw PDF data ready for upload or HTTP response.

    Every PDF goes through _local_uploads_url_fetcher so the landlord's own
    logo/signature (stored on local disk when S3 isn't configured) always
    render — see that function. base_url still defaults to the app root so any
    other relative asset resolves against the server, not the filesystem root.
    """
    if base_url is None:
        try:
            base_url = current_app.root_path + "/"
        except Exception:
            base_url = None
    h = HTML(string=html, base_url=base_url, url_fetcher=_local_uploads_url_fetcher)
    return h.write_pdf()


def render_template_pdf(template_name: str, context: dict) -> bytes:
    """
    Render a Jinja2 template to HTML then convert to PDF bytes.

    Templates live in  <app_root>/templates/pdf/<template_name>.

    Parameters
    ----------
    template_name : e.g. "receipt.html", "tenant_statement.html"
    context       : dict of variables passed to the template

    Returns
    -------
    bytes : Raw PDF data.
    """
    templates_dir = os.path.join(current_app.root_path, "templates", "pdf")
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template(template_name)
    html = template.render(**context)
    return render_pdf(html, base_url=templates_dir + "/")


def upload_pdf(pdf_bytes: bytes, key: str) -> str:
    """
    Upload PDF bytes to the S3-compatible bucket and return the public URL.

    All receipts, statements, leases, and tax invoices go through this
    single function.  Never implement per-endpoint PDF storage.

    Parameters
    ----------
    pdf_bytes : Raw PDF bytes from render_pdf() / render_template_pdf().
    key       : S3 object key, e.g. "receipts/PMT-2026-XYZ.pdf"

    Returns
    -------
    str : Public URL (CDN prefix + key, or presigned URL).
    """
    bucket = current_app.config.get("S3_BUCKET")
    endpoint_url = current_app.config.get("S3_ENDPOINT_URL")
    region = current_app.config.get("S3_REGION", "us-east-1")
    public_base = current_app.config.get("S3_PUBLIC_BASE_URL", "")
    aws_key = current_app.config.get("AWS_ACCESS_KEY_ID")
    aws_secret = current_app.config.get("AWS_SECRET_ACCESS_KEY")

    if not bucket:
        raise ApiError("S3_BUCKET is not configured.", status=500, code="storage_misconfigured")

    try:
        kwargs: dict = dict(region_name=region)
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if aws_key and aws_secret:
            kwargs["aws_access_key_id"] = aws_key
            kwargs["aws_secret_access_key"] = aws_secret

        s3 = boto3.client("s3", **kwargs)
        s3.upload_fileobj(
            BytesIO(pdf_bytes),
            bucket,
            key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error("upload_pdf failed for key '%s': %s", key, exc)
        raise ApiError("Failed to upload document. Please try again.", status=500, code="upload_error")

    if public_base:
        return f"{public_base.rstrip('/')}/{key}"
    # Return the standard AWS S3 URL if no CDN base is set.
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def upload_image(file_storage) -> str:
    """
    Upload a Werkzeug FileStorage object to Cloudinary and return the secure URL.
    Used for property images and maintenance request photos.

    Parameters
    ----------
    file_storage : werkzeug.datastructures.FileStorage (from request.files)

    Returns
    -------
    str : Cloudinary secure_url
    """
    cloud_name = current_app.config.get("CLOUDINARY_CLOUD_NAME")
    api_key = current_app.config.get("CLOUDINARY_API_KEY")
    api_secret = current_app.config.get("CLOUDINARY_API_SECRET")
    cloudinary_url = current_app.config.get("CLOUDINARY_URL")

    if cloudinary_url:
        cloudinary.config(cloudinary_url=cloudinary_url)
    elif cloud_name and api_key and api_secret:
        cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret)
    else:
        raise ApiError("Cloudinary is not configured.", status=500, code="storage_misconfigured")

    try:
        result = cloudinary.uploader.upload(
            file_storage.stream,
            folder="sahilpay",
            resource_type="image",
        )
        return result["secure_url"]
    except Exception as exc:
        logger.error("upload_image failed: %s", exc)
        raise ApiError("Failed to upload image. Please try again.", status=500, code="upload_error")


# ===========================================================================
# §4.10 — Misc helpers
# ===========================================================================

def parse_date(s: str | None) -> date | None:
    """
    Parse a date string (YYYY-MM-DD) to a Python date.
    Returns None if *s* is falsy or cannot be parsed.
    """
    if not s:
        return None
    try:
        return date.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def month_str(d: date | datetime | None = None) -> str:
    """
    Return 'YYYY-MM' for the given date/datetime, defaulting to today.
    Used for utility_readings.reading_month.
    """
    if d is None:
        d = date.today()
    return d.strftime("%Y-%m")


def gen_reference(prefix: str) -> str:
    """
    Generate a collision-resistant reference string.
    Format: <PREFIX>-<YYYYMMDD>-<8 uppercase alphanum chars>

    Examples:
        gen_reference("INV") → "INV-20260623-A3BF92CD"
        gen_reference("PMT") → "PMT-20260623-7E1DA0B2"

    Used for invoice_number and payment_ref.
    """
    today = date.today().strftime("%Y%m%d")
    suffix = "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8)
    )
    return f"{prefix.upper()}-{today}-{suffix}"


def enum_values(enum_cls) -> list[str]:
    """Return the list of string values for a str-Enum class."""
    return [e.value for e in enum_cls]


def validate_enum(value: str, enum_cls) -> str:
    """
    Validate that *value* is a member of *enum_cls*.
    Returns *value* if valid, raises ApiError(400) otherwise.
    """
    valid = enum_values(enum_cls)
    if value not in valid:
        raise ApiError(
            f"Invalid value '{value}'. Must be one of: {', '.join(valid)}.",
            status=400,
            code="invalid_enum_value",
        )
    return value


def decrement_sms_balance(landlord, n: int = 1) -> None:
    """
    Decrement the landlord's SMS balance by *n*.

    Called by communication services/tasks after successfully dispatching
    an outbound SMS via FluxSMS.  The actual send lives in
    services/ or tasks/ — this helper only updates the balance.

    Low-balance detection:
        When balance drops at or below landlord's configured threshold
        (LandlordSettings.low_sms_balance_threshold), a warning is logged.
        The Celery Beat "low-sms-balance-alerts" job checks this daily and
        fires the alert notification.
    """
    from extensions import db

    if landlord.sms_balance is None:
        landlord.sms_balance = 0

    before = landlord.sms_balance
    landlord.sms_balance = max(0, landlord.sms_balance - n)
    db.session.add(landlord)

    # Warn if balance is low (threshold from settings or config default).
    threshold = current_app.config.get("LOW_SMS_THRESHOLD_DEFAULT", 50)
    settings = getattr(landlord, "landlord_settings", None)
    if settings:
        threshold = getattr(settings, "low_sms_balance_threshold", threshold)

    if landlord.sms_balance <= threshold:
        logger.warning(
            "Landlord #%s SMS balance is low: %d remaining (threshold: %d).",
            landlord.id,
            landlord.sms_balance,
            threshold,
        )
        # Fire the "low_sms" alert once, on the crossing (respects Settings →
        # Alerts). Realtime here; the Celery Beat digest handles non-realtime.
        if before > threshold:
            try:
                from services.alert_service import dispatch_alert

                dispatch_alert(
                    landlord.id,
                    "low_sms",
                    title="Low SMS balance",
                    body=f"Your SMS balance is down to {landlord.sms_balance} credits. Top up to keep sending reminders.",
                    link="/landlord/settings/billing",
                )
            except Exception as exc:  # never let an alert break an SMS send
                logger.error("low_sms alert dispatch failed: %s", exc)