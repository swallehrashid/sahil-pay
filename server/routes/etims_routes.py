"""
routes/etims_routes.py — KRA / eTIMS compliance endpoints
Blueprint: etims_bp  |  Prefix: /api  (full paths declared per route)

SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §8. The prefix is bare /api because the
spec's paths span several resources (/api/properties/:id/etims-settings,
/api/payments/:id/etims, /api/etims/*, /api/reports/kra-monthly) and keeping
them in one module keeps the scoping rules in one place — which matters, since
every one of these routes must enforce per-property tax scope server-side, not
merely hide a button.

Nothing here is reachable unless the platform flag is on AND the account opted
in AND the specific property opted in. `tax_property_ids()` collapses all three
checks plus team-member grants into one set, and every handler intersects with
it before touching a row.
"""

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from extensions import db
from decorators import (
    get_current_landlord_id, require_landlord_or_team, require_permission,
    _check_permission,
)
from models import (
    BillingTransaction, LandlordSettings, OwnerPayout, Payment, Property,
    PropertyOwner, TeamMember, TeamMemberPropertyPermission as TMPP,
)
from services import etims_service as etims
from services.report_access import require_report
from services.audit_service import record_audit
from utils import ApiError, get_jwt_user, success

etims_bp = Blueprint("etims", __name__, url_prefix="/api")


def _actor_user_id() -> int | None:
    try:
        return get_jwt_user().id
    except ApiError:
        return None


def _settings_row(landlord_id: int) -> LandlordSettings:
    row = LandlordSettings.query.filter_by(landlord_id=landlord_id).first()
    if row is None:
        row = LandlordSettings(landlord_id=landlord_id)
        db.session.add(row)
        db.session.flush()
    return row


# ===========================================================================
# Settings (§2.1)
# ===========================================================================

@etims_bp.route("/etims/settings", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def get_etims_settings():
    """
    Everything the Tax Compliance settings section needs.

    Safe to call from any account: a landlord who has never heard of eTIMS gets
    `enabled: false` and an empty property list, and the UI renders the opt-in
    card rather than any compliance state.
    """
    landlord_id = get_current_landlord_id()
    settings = _settings_row(landlord_id)
    user = get_jwt_user()

    properties = (
        Property.query
        .filter_by(landlord_id=landlord_id, is_deleted=False)
        .order_by(Property.name.asc())
        .all()
    )
    from utils import accessible_property_ids
    visible = accessible_property_ids()
    if visible is not None:
        properties = [p for p in properties if p.id in visible]

    return success({
        "features_enabled":  etims.features_enabled(),
        "account_enabled":   bool(settings.etims_enabled),
        "account_kra_pin":   user.kra_pin,
        "reminders": {
            "record_invoices": bool(settings.etims_reminder_record_enabled),
            "filing_due":      bool(settings.etims_reminder_filing_enabled),
        },
        "properties": [{
            "id":            p.id,
            "name":          p.name,
            "kra_pin":       p.kra_pin,
            "owner_id":      p.owner_id,
            "owner_name":    p.owner.full_name if p.owner else None,
            "owner_kra_pin": p.owner.kra_pin if p.owner else None,
            "etims_enabled": p.etims_enabled,
            "display": {
                "show_on_receipts":   p.etims_shows("receipts"),
                "show_on_statements": p.etims_shows("statements"),
                "show_on_reports":    p.etims_shows("reports"),
            },
        } for p in properties],
    })


@etims_bp.route("/etims/settings", methods=["PATCH"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "edit")
def update_etims_settings():
    """Account master switch, the two reminder toggles, and the caller's own PIN."""
    landlord_id = get_current_landlord_id()
    data = request.get_json(silent=True) or {}
    settings = _settings_row(landlord_id)

    if "account_enabled" in data:
        settings.etims_enabled = bool(data["account_enabled"])
    reminders = data.get("reminders") or {}
    if "record_invoices" in reminders:
        settings.etims_reminder_record_enabled = bool(reminders["record_invoices"])
    if "filing_due" in reminders:
        settings.etims_reminder_filing_enabled = bool(reminders["filing_due"])

    if "account_kra_pin" in data:
        user = get_jwt_user()
        user.kra_pin = etims.normalise_kra_pin(data["account_kra_pin"], "account_kra_pin")

    db.session.commit()
    record_audit(actor_user_id=_actor_user_id(), landlord_id=landlord_id,
                 action="etims_settings_update", entity_type="settings",
                 entity_id=settings.id,
                 description="Updated KRA/eTIMS account settings.")
    return success(message="Tax compliance settings saved.")


@etims_bp.route("/properties/<int:property_id>/etims-settings", methods=["PATCH"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "edit")
def update_property_etims_settings(property_id: int):
    """
    Per-property opt-in, display surfaces, and the owner's KRA PIN.

    Note this is the ONE tax endpoint not gated on `tax_property_ids()` — it is
    how a property gets INTO that set in the first place, so gating it on
    membership would be circular. It is gated on `properties:edit` instead,
    which team members with tax-only access do not hold.
    """
    landlord_id = get_current_landlord_id()
    prop = Property.query.filter_by(
        id=property_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if prop is None:
        raise ApiError("Property not found.", status=404)

    from utils import accessible_property_ids
    visible = accessible_property_ids()
    if visible is not None and prop.id not in visible:
        raise ApiError("Property not found.", status=404)

    data = request.get_json(silent=True) or {}

    if "etims_enabled" in data:
        prop.etims_enabled = bool(data["etims_enabled"])
    if "kra_pin" in data:
        prop.kra_pin = etims.normalise_kra_pin(data["kra_pin"])
    if "owner_id" in data:
        owner_id = data["owner_id"]
        if owner_id in (None, "", 0):
            prop.owner_id = None
        else:
            owner = PropertyOwner.query.filter_by(
                id=owner_id, landlord_id=landlord_id).first()
            if owner is None:
                raise ApiError("Owner not found.", status=404)
            prop.owner_id = owner.id

    display = data.get("display")
    if isinstance(display, dict):
        # Re-assigned rather than mutated: SQLAlchemy does not track in-place
        # edits of a plain JSON column, so mutating would silently not persist.
        current = dict(prop.etims_display_settings or {})
        for surface in ("receipts", "statements", "reports"):
            key = f"show_on_{surface}"
            if key in display:
                current[key] = bool(display[key])
        prop.etims_display_settings = current

    db.session.commit()
    record_audit(actor_user_id=_actor_user_id(), landlord_id=landlord_id,
                 action="etims_property_settings_update", entity_type="property",
                 entity_id=prop.id,
                 description=f"Updated eTIMS settings for {prop.name}.")
    return success(prop.to_dict(), message="Saved.")


# ===========================================================================
# Property owners (the taxpayer behind each block)
# ===========================================================================

@etims_bp.route("/property-owners", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
def list_property_owners():
    landlord_id = get_current_landlord_id()
    owners = (
        PropertyOwner.query
        .filter_by(landlord_id=landlord_id)
        .order_by(PropertyOwner.full_name.asc())
        .all()
    )
    return success([o.to_dict(include_properties=True) for o in owners])


@etims_bp.route("/property-owners", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "edit")
def create_property_owner():
    landlord_id = get_current_landlord_id()
    data = request.get_json(silent=True) or {}

    name = (data.get("full_name") or "").strip()
    if not name:
        raise ApiError("The owner's name is required.", status=422,
                       errors={"full_name": "required"})

    phone = (data.get("phone") or "").strip() or None
    if phone and PropertyOwner.query.filter_by(
            landlord_id=landlord_id, phone=phone).first():
        raise ApiError("An owner with that phone number already exists.",
                       status=409, errors={"phone": "duplicate"})

    owner = PropertyOwner(
        landlord_id = landlord_id,
        full_name   = name,
        phone       = phone,
        email       = (data.get("email") or "").strip() or None,
        kra_pin     = etims.normalise_kra_pin(data.get("kra_pin")),
        notes       = data.get("notes"),
    )
    db.session.add(owner)
    db.session.commit()
    record_audit(actor_user_id=_actor_user_id(), landlord_id=landlord_id,
                 action="property_owner_create", entity_type="property_owner",
                 entity_id=owner.id, description=f"Added property owner {name}.")
    return success(owner.to_dict(), message="Owner added.", status=201)


@etims_bp.route("/property-owners/<int:owner_id>", methods=["PATCH"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "edit")
def update_property_owner(owner_id: int):
    landlord_id = get_current_landlord_id()
    owner = PropertyOwner.query.filter_by(
        id=owner_id, landlord_id=landlord_id).first()
    if owner is None:
        raise ApiError("Owner not found.", status=404)

    data = request.get_json(silent=True) or {}
    if "full_name" in data:
        name = (data["full_name"] or "").strip()
        if not name:
            raise ApiError("The owner's name is required.", status=422,
                           errors={"full_name": "required"})
        owner.full_name = name
    if "phone" in data:
        phone = (data["phone"] or "").strip() or None
        clash = PropertyOwner.query.filter(
            PropertyOwner.landlord_id == landlord_id,
            PropertyOwner.phone == phone,
            PropertyOwner.id != owner.id,
        ).first() if phone else None
        if clash is not None:
            raise ApiError("An owner with that phone number already exists.",
                           status=409, errors={"phone": "duplicate"})
        owner.phone = phone
    if "email" in data:
        owner.email = (data["email"] or "").strip() or None
    if "kra_pin" in data:
        owner.kra_pin = etims.normalise_kra_pin(data["kra_pin"])
    if "notes" in data:
        owner.notes = data["notes"]
    if "is_active" in data:
        owner.is_active = bool(data["is_active"])

    db.session.commit()
    record_audit(actor_user_id=_actor_user_id(), landlord_id=landlord_id,
                 action="property_owner_update", entity_type="property_owner",
                 entity_id=owner.id, description=f"Updated owner {owner.full_name}.")
    return success(owner.to_dict(include_properties=True), message="Saved.")


# ===========================================================================
# Recording numbers (§4.1, §4.2)
# ===========================================================================

def _load_scoped(kind: str, record_id: int, landlord_id: int):
    """Fetch one record and prove the caller may record eTIMS data on it."""
    if kind == "subscription":
        if not etims.is_system_admin():
            raise ApiError("Only a system administrator can record subscription "
                           "eTIMS numbers.", status=403)
        record = db.session.get(BillingTransaction, record_id)
        if record is None:
            raise ApiError("Transaction not found.", status=404)
        return record

    model = Payment if kind == "payment" else OwnerPayout
    record = db.session.get(model, record_id)
    if record is None or getattr(record, "is_deleted", False):
        raise ApiError("Record not found.", status=404)
    if record.landlord_id != landlord_id and not etims.is_system_admin():
        raise ApiError("Record not found.", status=404)
    if not etims.is_system_admin():
        etims.assert_can_manage(landlord_id, record.property_id)
    return record


@etims_bp.route("/payments/<int:payment_id>/etims", methods=["PATCH"])
@jwt_required()
@require_landlord_or_team()
def set_payment_etims(payment_id: int):
    """Record or edit the eTIMS number on one rent payment."""
    landlord_id = get_current_landlord_id()
    payment = _load_scoped("payment", payment_id, landlord_id)
    data = request.get_json(silent=True) or {}

    etims.record_number(
        payment, "payment",
        invoice_number = data.get("etims_invoice_number"),
        issued_at      = data.get("etims_issued_at"),
        qr_url         = data.get("etims_qr_url"),
        actor_user_id  = _actor_user_id(),
    )
    db.session.commit()
    record_audit(actor_user_id=_actor_user_id(), landlord_id=landlord_id,
                 action="etims_record", entity_type="payment", entity_id=payment.id,
                 description=f"eTIMS invoice recorded on payment {payment.payment_ref}.")
    return success(payment.etims_dict(), message="eTIMS invoice recorded.")


@etims_bp.route("/payments/<int:payment_id>/etims", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
def clear_payment_etims(payment_id: int):
    """Remove the number. The payment reverts to having none — a normal state."""
    landlord_id = get_current_landlord_id()
    payment = _load_scoped("payment", payment_id, landlord_id)
    etims.record_number(payment, "payment", invoice_number=None,
                        actor_user_id=_actor_user_id())
    db.session.commit()
    record_audit(actor_user_id=_actor_user_id(), landlord_id=landlord_id,
                 action="etims_clear", entity_type="payment", entity_id=payment.id,
                 description=f"eTIMS invoice removed from payment {payment.payment_ref}.")
    return success(payment.etims_dict(), message="Removed.")


@etims_bp.route("/owner-payouts/<int:payout_id>/etims", methods=["PATCH"])
@jwt_required()
@require_landlord_or_team()
def set_payout_etims(payout_id: int):
    """
    Record the PM's own eTIMS invoice to the owner for the commission deducted
    from this payout — issued under the PM's PIN, not the owner's.
    """
    landlord_id = get_current_landlord_id()
    payout = _load_scoped("payout", payout_id, landlord_id)
    data = request.get_json(silent=True) or {}

    etims.record_number(
        payout, "payout",
        invoice_number = data.get("etims_invoice_number"),
        issued_at      = data.get("etims_issued_at"),
        qr_url         = data.get("etims_qr_url"),
        actor_user_id  = _actor_user_id(),
    )
    db.session.commit()
    record_audit(actor_user_id=_actor_user_id(), landlord_id=landlord_id,
                 action="etims_record", entity_type="etims", entity_id=payout.id,
                 description=f"eTIMS invoice recorded on owner payout #{payout.id}.")
    return success(payout.etims_dict(), message="eTIMS invoice recorded.")


@etims_bp.route("/etims/bulk", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
def bulk_etims():
    """
    Batch upsert from the Register's "Save all" button.

    Always 200: per-row outcomes live in the body, because a partially
    successful save is the normal case here and must not read as a failure.
    """
    landlord_id = get_current_landlord_id()
    data = request.get_json(silent=True) or {}
    result = etims.bulk_record(landlord_id, data.get("records") or [],
                               actor_user_id=_actor_user_id())
    db.session.commit()

    if result["saved_count"]:
        record_audit(actor_user_id=_actor_user_id(), landlord_id=landlord_id,
                     action="etims_bulk_record", entity_type="etims", entity_id=None,
                     description=f"Recorded {result['saved_count']} eTIMS invoice numbers.")

    message = (f"Saved {result['saved_count']} "
               f"{'entry' if result['saved_count'] == 1 else 'entries'}.")
    return success(result, message=message)


@etims_bp.route("/etims/register", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def etims_register():
    """The Register table (§4.2). Empty list when the caller has no tax scope."""
    landlord_id = get_current_landlord_id()
    scope = (request.args.get("scope") or "payments").strip()
    if scope not in ("payments", "payouts"):
        raise ApiError("scope must be 'payments' or 'payouts'.", status=422)

    raw_ids = request.args.get("property_ids") or ""
    property_ids = [int(p) for p in raw_ids.split(",") if p.strip().isdigit()]

    status = (request.args.get("status") or "all").strip()
    if status not in ("all", "recorded", "not_recorded"):
        status = "all"

    rows = etims.register_rows(
        landlord_id, scope=scope, property_ids=property_ids or None,
        month=request.args.get("month"), status=status,
    )
    return success({"rows": rows, "count": len(rows), "scope": scope})


@etims_bp.route("/etims/scope", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def etims_scope():
    """
    Which properties the caller may do compliance work on.

    The navigation uses this to decide whether the eTIMS Register and KRA
    report appear at all. An empty list means they must not be rendered —
    not rendered disabled, not rendered with an explanation.
    """
    landlord_id = get_current_landlord_id()
    ids = etims.tax_property_ids(landlord_id)
    properties = (
        Property.query.filter(Property.id.in_(ids)).order_by(Property.name.asc()).all()
        if ids else []
    )
    return success({
        "enabled":    bool(ids),
        "properties": [{"id": p.id, "name": p.name} for p in properties],
    })


# ===========================================================================
# KRA Monthly Report (§4.3)
# ===========================================================================

@etims_bp.route("/reports/kra-monthly", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@require_report("kra_monthly")
def kra_monthly():
    landlord_id = get_current_landlord_id()
    consolidated = (request.args.get("consolidated", "true").lower()
                    not in ("0", "false", "no"))
    property_id = request.args.get("property_id")
    owner_id = request.args.get("owner_id")

    report = etims.kra_monthly_report(
        landlord_id,
        month        = request.args.get("month"),
        property_id  = int(property_id) if property_id and property_id.isdigit() else None,
        owner_id     = int(owner_id) if owner_id and owner_id.isdigit() else None,
        consolidated = consolidated,
    )

    fmt = (request.args.get("format") or "json").lower()
    if fmt == "csv":
        from flask import Response
        return Response(
            _report_csv(report), mimetype="text/csv",
            headers={"Content-Disposition":
                     f'attachment; filename="kra-monthly-{report["month"]}.csv"'},
        )
    if fmt == "pdf":
        from flask import Response
        from services.etims_pdf import render_kra_monthly_pdf
        pdf = render_kra_monthly_pdf(landlord_id, report)
        return Response(
            pdf, mimetype="application/pdf",
            headers={"Content-Disposition":
                     f'attachment; filename="kra-monthly-{report["month"]}.pdf"'},
        )
    return success(report)


def _report_csv(report: dict) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Taxpayer", "KRA PIN", "Date", "Tenant", "Unit",
                     "Property", "Rent received", "eTIMS invoice no."])
    for group in report["groups"]:
        for row in group["appendix"]:
            writer.writerow([
                group["name"], group["kra_pin"] or "", row["date"] or "",
                row["tenant"] or "", row["unit"] or "", row["property"] or "",
                row["amount"], row["etims_invoice_number"] or "",
            ])
        writer.writerow([group["name"], group["kra_pin"] or "", "", "", "",
                         "GROSS RENT RECEIVED", group["gross_rent_received"], ""])
        writer.writerow([group["name"], group["kra_pin"] or "", "", "", "",
                         "MRI @ 7.5%", group["mri_due"], ""])
    return buffer.getvalue()


# ===========================================================================
# Team-member tax grants (§5.2)
# ===========================================================================

@etims_bp.route("/team-members/<int:member_id>/tax-permissions", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
def get_tax_permissions(member_id: int):
    landlord_id = get_current_landlord_id()
    member = TeamMember.query.filter_by(id=member_id, landlord_id=landlord_id).first()
    if member is None:
        raise ApiError("Team member not found.", status=404)

    grants = TMPP.query.filter_by(
        team_member_id=member.id, permission=TMPP.PERM_MANAGE_TAX_COMPLIANCE
    ).all()
    return success({
        "team_member_id": member.id,
        "property_ids":   [g.property_id for g in grants],
        "grants":         [g.to_dict() for g in grants],
    })


@etims_bp.route("/team-members/<int:member_id>/tax-permissions", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "edit")
def set_tax_permissions(member_id: int):
    """
    Replace the member's `manage_tax_compliance` grants with *property_ids*.

    Replace-the-whole-set rather than add/remove deltas: the grant UI is a
    checklist, and a checklist that submits deltas drifts out of sync with what
    the person doing the granting believes they saved.
    """
    landlord_id = get_current_landlord_id()
    member = TeamMember.query.filter_by(id=member_id, landlord_id=landlord_id).first()
    if member is None:
        raise ApiError("Team member not found.", status=404)

    data = request.get_json(silent=True) or {}
    requested = {int(p) for p in (data.get("property_ids") or []) if str(p).isdigit()}

    if requested:
        owned = {
            r[0] for r in db.session.query(Property.id).filter(
                Property.id.in_(requested),
                Property.landlord_id == landlord_id,
                Property.is_deleted.is_(False),
            ).all()
        }
        stray = requested - owned
        if stray:
            raise ApiError("Some of those properties don't belong to this account.",
                           status=422, errors={"property_ids": sorted(stray)})

    existing = {
        g.property_id: g for g in TMPP.query.filter_by(
            team_member_id=member.id, permission=TMPP.PERM_MANAGE_TAX_COMPLIANCE
        ).all()
    }
    actor = _actor_user_id()

    for property_id in requested - set(existing):
        db.session.add(TMPP(
            team_member_id     = member.id,
            property_id        = property_id,
            permission         = TMPP.PERM_MANAGE_TAX_COMPLIANCE,
            granted_by_user_id = actor,
        ))
    for property_id in set(existing) - requested:
        db.session.delete(existing[property_id])

    db.session.commit()
    record_audit(actor_user_id=actor, landlord_id=landlord_id,
                 action="tax_permissions_update", entity_type="team_member",
                 entity_id=member.id,
                 description=(f"Tax compliance access set on {len(requested)} "
                              f"propert{'y' if len(requested) == 1 else 'ies'} "
                              f"for {member.username}."))

    grants = TMPP.query.filter_by(
        team_member_id=member.id, permission=TMPP.PERM_MANAGE_TAX_COMPLIANCE
    ).all()
    return success({"property_ids": [g.property_id for g in grants],
                    "grants": [g.to_dict() for g in grants]},
                   message="Tax compliance access saved.")
