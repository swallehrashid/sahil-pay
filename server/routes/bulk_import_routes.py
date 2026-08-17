"""
routes/bulk_import_routes.py — the bulk importer's HTTP surface.
Blueprint: bulk_import_bp  |  Prefix: /api/imports

The wizard's four steps map onto four calls:

    GET  /catalogue           what can be imported, and the fields of each
    POST /inspect             upload a file -> its headers, a preview, and a
                              suggested column mapping
    POST /<entity>/validate   check a mapped file, changing nothing
    POST /<entity>/commit     write the good rows

Plus saved mappings, so the same spreadsheet shape need only be mapped once:

    GET/POST      /mappings
    PUT/DELETE    /mappings/<id>

Everything is gated on the module the import WRITES to, not on a generic
"import" permission — someone who may not create tenants must not be able to
create four hundred of them by uploading a file.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import ImportMapping, Landlord
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
    _check_permission,
)
from services import bulk_import_service as bulk
from utils import ApiError, success

bulk_import_bp = Blueprint("bulk_imports", __name__, url_prefix="/api/imports")

# Which permission module each import writes through. An importer that bypassed
# the module gates would be the widest hole in the permission system.
ENTITY_MODULE = {
    "properties": "properties",
    "units":      "units",
    "tenants":    "tenants",
}


def _guard(entity: str, action: str = "edit") -> None:
    module = ENTITY_MODULE.get(entity)
    if module is None:
        raise ApiError(f"Unknown import type '{entity}'.", status=422,
                       errors={"entity": "unknown"})
    _check_permission(module, action)


def _upload():
    file = request.files.get("file")
    if file is None or not (file.filename or "").strip():
        raise ApiError("Choose a file to upload.", status=422,
                       errors={"file": "required"})
    return file


def _payload_rows():
    """
    The rows the client is asking us to act on.

    The wizard sends back the parsed rows rather than re-uploading the file, so
    the preview it showed and the data we act on are provably the same table.
    """
    data = request.get_json(silent=True) or {}
    rows = data.get("rows") or []
    mapping = data.get("mapping") or {}
    options = data.get("options") or {}
    if not isinstance(rows, list) or not isinstance(mapping, dict):
        raise ApiError("rows must be a list and mapping an object.", status=422)
    if len(rows) > bulk.MAX_ROWS:
        raise ApiError(
            f"{len(rows)} rows — the limit is {bulk.MAX_ROWS} per import.",
            status=422)
    return rows, mapping, options


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@bulk_import_bp.route("/catalogue", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def catalogue():
    """What can be imported, in the order it must be done, with each field."""
    return success({"entities": bulk.catalogue()})


# ---------------------------------------------------------------------------
# Inspect an uploaded file
# ---------------------------------------------------------------------------
@bulk_import_bp.route("/inspect", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
def inspect():
    """
    Read a file and hand back its headers, every row, and a suggested mapping.

    Deliberately does not require a matching header row — which column means
    what is the next step's job, so a manager never has to edit their file to
    reach the preview.

    Form fields: file, entity, sheet?
    """
    entity = (request.form.get("entity") or "").strip()
    _guard(entity)

    parsed = bulk.parse_file(_upload(), sheet=request.form.get("sheet"))
    if parsed["errors"]:
        raise ApiError(parsed["errors"][0], status=422,
                       errors={"file": parsed["errors"]})

    return success({
        "headers":  parsed["headers"],
        "sheets":   parsed["sheets"],
        "rows":     parsed["rows"],
        "row_count": len(parsed["rows"]),
        "suggested_mapping": bulk.suggest_mapping(entity, parsed["headers"]),
    })


# ---------------------------------------------------------------------------
# Validate / commit
# ---------------------------------------------------------------------------
@bulk_import_bp.route("/<entity>/validate", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
def validate_import(entity):
    """Check a mapped file and report per-row errors and warnings. Writes nothing."""
    _guard(entity)
    landlord_id = get_current_landlord_id()
    rows, mapping, options = _payload_rows()
    return success(bulk.validate(landlord_id, entity, rows, mapping, options))


@bulk_import_bp.route("/<entity>/commit", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
def commit_import(entity):
    """
    Write the valid rows.

    Re-validates server-side first: a browser that has been sitting on a preview
    for ten minutes may be proposing account numbers that were taken in the
    meantime, and finding that out AFTER writing half an estate is not
    recoverable by anyone.
    """
    _guard(entity)
    landlord_id = get_current_landlord_id()
    rows, mapping, options = _payload_rows()
    landlord = db.session.get(Landlord, landlord_id)

    result = bulk.commit(landlord, entity, rows, mapping, options,
                         actor_user_id=int(get_jwt_identity()))
    return success(result, message=(
        f"{result['created']} created, {result['skipped']} already present, "
        f"{result['rejected']} rejected."
    ))


# ---------------------------------------------------------------------------
# Saved mappings
# ---------------------------------------------------------------------------
@bulk_import_bp.route("/mappings", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def list_mappings():
    """Saved column mappings, optionally filtered to one entity."""
    landlord_id = get_current_landlord_id()
    query = ImportMapping.query.filter_by(landlord_id=landlord_id)
    if entity := request.args.get("entity"):
        query = query.filter_by(entity=entity)
    rows = query.order_by(ImportMapping.entity, ImportMapping.name).all()
    return success({"mappings": [m.to_dict() for m in rows]})


@bulk_import_bp.route("/mappings", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
def save_mapping():
    """
    Save a mapping by name, replacing one of the same name.

    Overwrite rather than reject: re-saving after correcting one column is the
    common case, and a duplicate-name error there just makes people invent
    "Monthly units 2".
    """
    landlord_id = get_current_landlord_id()
    data = request.get_json(silent=True) or {}

    entity = (data.get("entity") or "").strip()
    _guard(entity)
    name = (data.get("name") or "").strip()
    if not name:
        raise ApiError("Give the mapping a name.", status=422,
                       errors={"name": "required"})

    row = ImportMapping.query.filter_by(
        landlord_id=landlord_id, entity=entity, name=name).first()
    if row is None:
        row = ImportMapping(landlord_id=landlord_id, entity=entity, name=name,
                            created_by_user_id=int(get_jwt_identity()))
        db.session.add(row)

    row.mapping = data.get("mapping") or {}
    row.options = data.get("options") or {}
    db.session.commit()
    return success(row.to_dict(), message="Mapping saved."), 201


@bulk_import_bp.route("/mappings/<int:mapping_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
def delete_mapping(mapping_id):
    landlord_id = get_current_landlord_id()
    row = ImportMapping.query.filter_by(id=mapping_id, landlord_id=landlord_id).first()
    if row is None:
        raise ApiError("Mapping not found.", status=404)
    db.session.delete(row)
    db.session.commit()
    return success(message="Mapping deleted.")
