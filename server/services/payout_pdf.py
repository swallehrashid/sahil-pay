"""
services/payout_pdf.py — the landlord payout statement (spec §4.10).

Closes the loop for an owner: what was collected on their behalf, what the
managing agent deducted and why, and what was actually remitted. Uses the same
letterhead as every other report so it reads as an official document.

The tax line is the one that needs care. MRI is DISPLAY-ONLY unless the account
has withholding switched on, so the statement must say which of the two it is —
an owner reading "Tax 7,500" needs to know whether that money is coming to them
or has already been held back.
"""

from __future__ import annotations

from decimal import Decimal
from html import escape


def _money(value, currency="KES") -> str:
    try:
        return f"{currency} {float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return f"{currency} 0.00"


def render_payout_statement_pdf(payout) -> bytes:
    from extensions import db
    from models import Landlord
    from services.etims_pdf import statement_footer_pins_html
    from services.report_builder import (
        build_meta, _letterhead_html, _platform_credit_html, _signature_html,
        _REPORT_STYLE,
    )
    from utils import render_pdf

    landlord = db.session.get(Landlord, payout.landlord_id)
    owner_name = (payout.owner.full_name if payout.owner
                  else (payout.property.name if payout.property else "Owner"))
    period = (f"{payout.period_start} to {payout.period_end}"
              if payout.period_start and payout.period_end
              else (payout.period or ""))

    meta = build_meta(landlord, report_title="Owner Payout Statement",
                      subject=owner_name, period=period)

    lines = "".join(
        "<tr>"
        f"<td>{escape(line.unit.name if line.unit else '—')}</td>"
        f"<td>{escape((f'{line.tenant.first_name} {line.tenant.last_name}').strip() if line.tenant else '—')}</td>"
        f"<td style='text-align:right'>{_money(line.rent_collected)}</td>"
        f"<td style='text-align:right'>{_money(line.deposits_collected)}</td>"
        f"<td style='text-align:right'>{_money(line.other_collected)}</td>"
        f"<td style='text-align:right'>{_money(line.commission_amount)}</td>"
        "</tr>"
        for line in (payout.lines or [])
    )

    breakdown = [
        ("Total collected", payout.total_collected, False),
        ("Rent collected (commission &amp; tax base)", payout.rent_collected_base, False),
        ("Less: management commission", payout.commission_amount, True),
    ]
    if payout.other_deductions and float(payout.other_deductions) > 0:
        breakdown.append(("Less: other deductions", payout.other_deductions, True))

    rows = "".join(
        "<tr>"
        f"<td>{label}</td>"
        f"<td style='text-align:right'>{'−' if negative else ''}{_money(value)}</td>"
        "</tr>"
        for label, value, negative in breakdown
    )

    # The tax line states plainly whether it was withheld or is for information.
    if payout.tax_amount is not None:
        if payout.tax_withheld:
            rows += ("<tr><td>Less: Monthly Rental Income tax withheld (7.5%)</td>"
                     f"<td style='text-align:right'>−{_money(payout.tax_amount)}</td></tr>")
        else:
            rows += ("<tr><td class='muted'>Monthly Rental Income tax (7.5%) — for your "
                     "own filing, not deducted</td>"
                     f"<td style='text-align:right' class='muted'>{_money(payout.tax_amount)}</td></tr>")

    rows += ("<tr class='total-row'><td>Net paid to owner</td>"
             f"<td style='text-align:right'>{_money(payout.net_payable or payout.amount)}</td></tr>")

    settlement = ""
    if (payout.status or "") == "paid":
        settlement = (
            "<div style='margin-top:16px;padding:10px;background:#f4f4f8;border-radius:4px;'>"
            f"<strong>Paid</strong> on {escape(str(payout.payout_date or ''))}"
            f"{' via ' + escape(payout.method) if payout.method else ''}"
            f"{' · ref ' + escape(payout.reference) if payout.reference else ''}"
            "</div>"
        )

    # Footer PINs, for accounts that opted into the KRA layer. Silent otherwise.
    pins = ""
    prop = payout.property
    if prop is not None and prop.etims_shows("statements"):
        pins = statement_footer_pins_html(
            ("Owner KRA PIN", prop.effective_kra_pin),
            ("Managing agent KRA PIN",
             landlord.user.kra_pin if landlord and landlord.user else None),
        )
    etims_line = ""
    if payout.etims_invoice_number and prop is not None and prop.etims_shows("statements"):
        etims_line = ("<div class='muted' style='margin-top:6px;'>Commission eTIMS invoice no.: "
                      f"{escape(payout.etims_invoice_number)}</div>")

    body = (
        _letterhead_html(meta)
        + (f"<h2>Collections by unit</h2><table>"
           "<thead><tr><th>Unit</th><th>Tenant</th>"
           "<th style='text-align:right'>Rent</th>"
           "<th style='text-align:right'>Deposits</th>"
           "<th style='text-align:right'>Other</th>"
           "<th style='text-align:right'>Commission</th></tr></thead>"
           f"<tbody>{lines}</tbody></table>" if lines else "")
        + f"<h2>Settlement</h2><table><tbody>{rows}</tbody></table>"
        + "<p class='muted' style='margin-top:8px;font-size:10px;'>"
          "Deposits are the tenant's refundable money: they pass through in full "
          "and carry neither commission nor tax.</p>"
        + settlement + etims_line + pins
        + _signature_html(meta) + _platform_credit_html()
    )

    html = (f"<!doctype html><html><head><meta charset='utf-8'>{_REPORT_STYLE}"
            f"</head><body>{body}</body></html>")
    return render_pdf(html)
