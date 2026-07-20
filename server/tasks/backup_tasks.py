"""
SahilPay — tasks/backup_tasks.py
===================================
§11.5  Generates the actual file for a Backup row, dispatched from
settings_routes.py's "generate backup" action via .delay().
"""

from __future__ import annotations

import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="tasks.backup_tasks.generate_backup_task")
def generate_backup_task(backup_id: int) -> None:
    """
    Build the export for *backup* (by scope_type/scope_id/format), upload
    it, and set backup.file_url. Leaves file_url as None (silently) if the
    scope can't be resolved — the landlord sees an empty download link
    rather than a crashed task.
    """
    from extensions import db
    from models import Backup
    from services import export_service
    from services.storage_service import upload_to_s3

    backup = db.session.get(Backup, backup_id)
    if backup is None:
        logger.warning("generate_backup_task: backup #%s not found.", backup_id)
        return

    fmt = backup.format or "pdf"
    file_bytes = None

    try:
        if backup.scope_type == "property" and backup.scope_id:
            file_bytes = export_service.generate_property_statement(backup.landlord_id, backup.scope_id, fmt, None, None)
        elif backup.scope_type == "grouping" and backup.scope_id:
            file_bytes = export_service.generate_grouping_report(backup.landlord_id, backup.scope_id, fmt, None, None)
        elif backup.scope_type == "tenants":
            file_bytes = _backup_tenants(backup.landlord_id, fmt)
        elif backup.scope_type == "payments":
            file_bytes, _, _ = export_service.generate_payments_report(backup.landlord_id, fmt, None, None, None)
        elif backup.scope_type == "category":
            file_bytes = export_service.generate_expenses_report(backup.landlord_id, fmt, None, None, None)
        else:
            logger.warning("generate_backup_task: unknown scope_type '%s' for backup #%s", backup.scope_type, backup_id)
    except Exception:
        logger.error("generate_backup_task: failed building backup #%s", backup_id, exc_info=True)

    if file_bytes:
        ext = "xlsx" if fmt == "excel" else "pdf"
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "excel" else "application/pdf"
        backup.file_url = upload_to_s3(
            file_bytes,
            folder=f"backups/{backup.landlord_id}",
            filename=f"backup-{backup.id}.{ext}",
            content_type=content_type,
        )
        db.session.commit()


def _backup_tenants(landlord_id: int, fmt: str) -> bytes:
    from models import Tenant
    from services.export_service import _render_table
    from services.pdf_service import _money

    tenants = Tenant.query.filter_by(landlord_id=landlord_id).all()
    rows = [
        [f"{t.first_name} {t.last_name}", t.unit.name if t.unit else "—", t.phone, _money(t.balance)]
        for t in tenants
    ]
    return _render_table("All Tenants Backup", ["Tenant", "Unit", "Phone", "Balance"], rows, fmt)
