"""
routes/tenant_import_routes.py — Bulk tenant import
Blueprint: tenant_import_bp  |  Prefix: /api/tenants/import

Three endpoints, matching the three steps of the wizard:

    GET  /template   download the .xlsx to fill in
    POST /validate   upload it and see exactly what would happen — writes nothing
    POST /commit     do it

Validation is deliberately repeated inside /commit rather than trusting what the
browser sends back. A half-finished import — some tenants in, some silently
missing — is far worse than one that was rejected outright.
"""

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity

from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service import record_audit
from services import tenant_import_service as importer

tenant_import_bp = Blueprint("tenant_import", __name__, url_prefix="/api/tenants/import")

# Bigger than an ordinary document because a spreadsheet with 2,000 rows is a
# legitimate upload here.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = (".xlsx", ".xlsm", ".csv")


def _read_upload():
    """The uploaded file, or (None, error_response)."""
    file = request.files.get("file")
    if file is None or not file.filename:
        return None, (jsonify({"error": "Attach a file to upload."}), 400)

    name = file.filename.lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        return None, (jsonify({
            "error": "Upload an Excel (.xlsx) or CSV file — "
                     "download the template if you're not sure.",
        }), 400)

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return None, (jsonify({
            "error": f"That file is {size / 1024 / 1024:.1f} MB — the limit is "
                     f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB.",
        }), 400)

    return file, None


# ---------------------------------------------------------------------------
# GET /api/tenants/import/template
# ---------------------------------------------------------------------------
@tenant_import_bp.route("/template", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def download_template():
    """
    The .xlsx to fill in — headers, two example rows, and a Notes sheet
    explaining every column.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Excel template.}
    """
    return Response(
        importer.build_template_workbook(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=sahilpay-tenant-import-template.xlsx"
        },
    )


# ---------------------------------------------------------------------------
# POST /api/tenants/import/validate
# ---------------------------------------------------------------------------
@tenant_import_bp.route("/validate", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def validate():
    """
    Check an uploaded file and report, row by row, what would happen.
    WRITES NOTHING.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Per-row errors, warnings and planned actions.}
      400: {description: The file could not be read.}
    """
    file, error = _read_upload()
    if error:
        return error

    rows, fatal = importer.parse_upload(file)
    if fatal:
        return jsonify({"error": fatal[0], "errors": fatal}), 400

    return jsonify(importer.validate_rows(get_current_landlord_id(), rows)), 200


# ---------------------------------------------------------------------------
# POST /api/tenants/import/commit
# ---------------------------------------------------------------------------
@tenant_import_bp.route("/commit", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def commit():
    """
    Import the file for real: create any missing properties and units, the
    tenants, their opening arrears (as a traceable invoice) and any advance
    credit. Rows with errors are skipped and listed back.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: What was created, and what was skipped.}
      400: {description: The file could not be read.}
    """
    from extensions import db
    from models import Landlord

    file, error = _read_upload()
    if error:
        return error

    rows, fatal = importer.parse_upload(file)
    if fatal:
        return jsonify({"error": fatal[0], "errors": fatal}), 400

    landlord_id = get_current_landlord_id()
    landlord = db.session.get(Landlord, landlord_id)
    actor_id = int(get_jwt_identity())

    result = importer.commit_rows(landlord, rows, actor_user_id=actor_id)
    created = result["created"]

    record_audit(
        actor_user_id=actor_id,
        landlord_id=landlord_id,
        action="import_tenants",
        entity_type="tenant",
        entity_id=None,
        description=(
            f"Bulk import: {created['tenants']} tenants, {created['units']} units, "
            f"{created['properties']} properties, {created['opening_invoices']} opening "
            f"balances. {len(result['skipped'])} row(s) skipped."
        ),
        after_data=created,
    )
    db.session.commit()

    return jsonify({
        "message": f"Imported {created['tenants']} tenant(s).",
        **result,
    }), 200
