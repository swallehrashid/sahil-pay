"""
SahilPay — services/branding.py
================================
Single source of truth for Sahil Pay brand identity on the server side.
Every generated document (WeasyPrint PDFs, receipts, reports, exports) and
every outbound email pulls its logo, name, slogan, and contact block from
here — never hard-code "SahilPay" strings or logo markup in a template again.

The logo is inline SVG (WeasyPrint renders it natively), monochrome by
design: pass whatever colour the surface needs. Transparent background
always.
"""

from __future__ import annotations

BRAND_NAME = "Sahil Pay"
BRAND_SLOGAN = "SMART RENT COLLECTION"
BRAND_PHONE = "0114 129 809"
BRAND_EMAIL = "hello@sahilpay.co.ke"
BRAND_WEBSITE = "https://sahilpay.co.ke"
BRAND_LOCATION = "Nairobi, Kenya"

# Brand palette (mirrors client/src/index.css)
BRAND_NAVY = "#0f0246"     # primary ink — logo on light surfaces, headings
BRAND_VIOLET = "#200497"   # accent — rules, table heads, links
BRAND_MUTED = "#6b6b80"    # secondary text
BRAND_WHITE = "#ffffff"    # logo on dark surfaces

_MARK_PATH = "M47 8 L86 50 C80 68 60 73 46 81 C33 88.5 25.5 97 24 112 L18 62 L6 62 Z"
_WINDOW_PANES = ((37, 30), (51, 30), (37, 44), (51, 44))


def logo_mark_svg(color: str = BRAND_NAVY, size: int = 48) -> str:
    """The house mark alone, as an inline SVG string (transparent bg)."""
    panes = "".join(
        f'<rect x="{x}" y="{y}" width="11" height="11" fill="{color}"/>'
        for x, y in _WINDOW_PANES
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" '
        f'width="{size}" height="{size}" fill="none">'
        f'<path d="{_MARK_PATH}" stroke="{color}" stroke-width="4" '
        f'stroke-linejoin="miter" fill="none"/>{panes}</svg>'
    )


def logo_lockup_html(color: str = BRAND_NAVY, mark_size: int = 44) -> str:
    """Mark + wordmark + slogan as an HTML flex block for PDF/email headers."""
    return f"""
    <div style="display:flex;align-items:center;gap:10px;">
      {logo_mark_svg(color=color, size=mark_size)}
      <div style="line-height:1;">
        <div style="font-family:Georgia,'Times New Roman',serif;font-size:{round(mark_size * 0.5)}px;
                    font-weight:500;letter-spacing:.14em;color:{color};">SAHIL&nbsp;PAY</div>
        <div style="font-family:Helvetica,Arial,sans-serif;font-size:{max(round(mark_size * 0.17), 7)}px;
                    letter-spacing:.4em;color:{color};opacity:.75;margin-top:3px;white-space:nowrap;">{BRAND_SLOGAN}</div>
      </div>
    </div>
    """


def pdf_header_html(document_label: str = "", meta_html: str = "") -> str:
    """Standard branded header row for every generated PDF.

    Left: logo lockup (+ optional document label under it).
    Right: caller-supplied meta block (dates, numbers, addressee).
    """
    label = (
        f'<div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;'
        f'color:{BRAND_MUTED};margin-top:6px;">{document_label}</div>'
        if document_label
        else ""
    )
    return f"""
    <div style="display:flex;justify-content:space-between;align-items:flex-start;
                border-bottom:2px solid {BRAND_VIOLET};padding-bottom:12px;margin-bottom:16px;">
      <div>{logo_lockup_html()}{label}</div>
      <div style="text-align:right;font-size:11px;color:{BRAND_MUTED};">{meta_html}</div>
    </div>
    """


def pdf_footer_html() -> str:
    """Standard branded footer for every generated PDF."""
    return f"""
    <div style="border-top:1px solid #e2e2e8;margin-top:24px;padding-top:8px;
                font-size:10px;color:{BRAND_MUTED};display:flex;justify-content:space-between;">
      <span>{BRAND_NAME} · {BRAND_SLOGAN.title()} · {BRAND_LOCATION}</span>
      <span>{BRAND_PHONE} · {BRAND_EMAIL} · sahilpay.co.ke</span>
    </div>
    """
