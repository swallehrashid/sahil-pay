"""
SahilPay — tasks/payment_tasks.py
====================================
§4.3  Parses an uploaded bank statement into bank_statement_transactions
rows for the landlord to review and selectively import as payments.

Real CSV parsing (the common export format for Kenyan bank statements).
PDF statements are accepted at upload time but flagged as failed here —
full PDF layout/OCR extraction is a much larger feature than today's
"get the API layer running" scope.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import urllib.request

from celery_app import celery
from utils import parse_date

logger = logging.getLogger(__name__)

_DATE_KEYS = ("date", "txn_date", "transaction_date", "value_date")
_DESCRIPTION_KEYS = ("description", "narrative", "details", "particulars")
_AMOUNT_KEYS = ("amount", "value", "credit", "debit")
_REFERENCE_KEYS = ("reference", "ref", "transaction_ref", "cheque_no")


def _first_matching(row: dict, keys: tuple[str, ...]) -> str | None:
    lowered = {k.lower().strip(): v for k, v in row.items()}
    for key in keys:
        if key in lowered and lowered[key]:
            return lowered[key]
    return None


def _fetch_file_bytes(file_url: str) -> bytes | None:
    if file_url.startswith("/uploads/"):
        from flask import current_app

        path = os.path.join(current_app.root_path, file_url.lstrip("/"))
        if not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            return fh.read()

    try:
        with urllib.request.urlopen(file_url, timeout=20) as resp:
            return resp.read()
    except Exception:
        logger.error("parse_bank_statement_task: could not download %s", file_url, exc_info=True)
        return None


@celery.task(name="tasks.payment_tasks.parse_bank_statement_task")
def parse_bank_statement_task(upload_id: int) -> None:
    from extensions import db
    from models import BankStatementTransaction, BankStatementUpload

    upload = db.session.get(BankStatementUpload, upload_id)
    if upload is None:
        logger.warning("parse_bank_statement_task: upload #%s not found.", upload_id)
        return

    upload.status = "parsing"
    db.session.commit()

    data = _fetch_file_bytes(upload.file_url)
    if data is None:
        upload.status = "failed"
        db.session.commit()
        return

    is_csv = upload.file_url.lower().endswith(".csv") or _looks_like_csv(data)
    if not is_csv:
        logger.warning("parse_bank_statement_task: upload #%s isn't CSV — PDF/Excel parsing isn't implemented yet.", upload_id)
        upload.status = "failed"
        db.session.commit()
        return

    try:
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        count = 0
        for row in reader:
            amount_raw = _first_matching(row, _AMOUNT_KEYS)
            if amount_raw is None:
                continue
            try:
                amount = float(str(amount_raw).replace(",", ""))
            except ValueError:
                continue

            db.session.add(
                BankStatementTransaction(
                    bank_statement_id=upload.id,
                    txn_date=parse_date(_first_matching(row, _DATE_KEYS)),
                    description=_first_matching(row, _DESCRIPTION_KEYS),
                    amount=amount,
                    reference=_first_matching(row, _REFERENCE_KEYS),
                    is_imported=False,
                )
            )
            count += 1

        upload.status = "parsed"
        db.session.commit()
        logger.info("parse_bank_statement_task: parsed %d transactions for upload #%s", count, upload_id)
    except Exception:
        logger.error("parse_bank_statement_task: failed for upload #%s", upload_id, exc_info=True)
        db.session.rollback()
        upload.status = "failed"
        db.session.commit()


def _looks_like_csv(data: bytes) -> bool:
    try:
        sample = data[:512].decode("utf-8-sig", errors="ignore")
    except Exception:
        return False
    return "," in sample and "\n" in sample


@celery.task(name="tasks.payment_tasks.refresh_all_tenant_scores")
def refresh_all_tenant_scores() -> dict:
    """
    Celery Beat (nightly): recompute every active tenant's payment score.

    Payment-time refreshes (services/allocation_service.apply_allocations) keep
    scores live during the day, but a month rolling over changes a score with no
    payment involved — a tenant who simply never paid last month must start
    counting as unpaid. This is that backstop.

    Demo shadow landlords are skipped (DEMO_MODE_SPEC.md §3.4).
    """
    from models import Landlord
    from services.tenant_score_service import refresh_scores_for_landlord

    totals = {"landlords": 0, "tenants": 0, "errors": 0}
    for landlord in Landlord.query.filter(Landlord.is_demo.is_(False)).all():
        totals["landlords"] += 1
        try:
            totals["tenants"] += refresh_scores_for_landlord(landlord.id)
        except Exception:
            totals["errors"] += 1
            logger.exception("refresh_all_tenant_scores failed for landlord %s", landlord.id)
    logger.info("refresh_all_tenant_scores: %s", totals)
    return totals
