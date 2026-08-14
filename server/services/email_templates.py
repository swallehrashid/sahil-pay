"""
SahilPay — services/email_templates.py
=======================================
Branded, email-client-safe HTML for every transactional email.

Email clients (Gmail, Outlook, Apple Mail) strip <style> blocks, ignore flex/
grid and modern CSS, and render inconsistently — so everything here is built
with nested tables and INLINE styles only, the way marketing/transactional
emails have to be. The palette mirrors the SahilPay web UI:

    primary  #0f0246   (deep indigo)      primary-950 #08011f
    secondary#b95f7b   (rose — CTAs)
    third    #200497   (indigo accent)

Public API:
    render_email(heading, intro, blocks=[...], preheader=..., footer_note=...)
    paragraph(html)            -> a body paragraph block
    button(label, url)         -> a rose CTA button block
    credentials(rows)          -> a boxed key/value panel (login details)
    code_box(code, caption)    -> a large monospaced code panel (OTP)
    note(html)                 -> a muted helper/disclaimer line
    steps(items)               -> a numbered instruction list
"""

from __future__ import annotations

from html import escape

from services import branding

# ── Palette ──────────────────────────────────────────────────────────────────
BG        = "#08011f"   # page background (primary-950)
CARD_TOP  = "#160653"   # card gradient top (primary-700)
CARD_BOT  = "#0f0246"   # card gradient bottom (primary-900)
PANEL     = "#11024f"   # inset panel (third-900-ish)
BORDER    = "#2a1b6b"   # hairline border (primary-500)
TEXT      = "#e8e6f0"   # primary text (primary-50)
MUTED     = "#a59cc7"   # muted text (primary-200)
ROSE      = "#b95f7b"   # secondary (CTA)
ROSE_DK   = "#a34f69"   # secondary-600 (CTA border/shadow)
ACCENT    = "#c57693"   # secondary-400 (links / highlights)
FONT      = "'Inter','Segoe UI',Helvetica,Arial,sans-serif"


# ── Content block builders ───────────────────────────────────────────────────
def paragraph(html: str) -> str:
    return (
        f'<p style="margin:0 0 16px;font-family:{FONT};font-size:15px;'
        f'line-height:1.65;color:{TEXT};">{html}</p>'
    )


def note(html: str) -> str:
    return (
        f'<p style="margin:0 0 14px;font-family:{FONT};font-size:13px;'
        f'line-height:1.6;color:{MUTED};">{html}</p>'
    )


def button(label: str, url: str) -> str:
    # Bulletproof-ish button: a padded, rounded anchor styled as a block.
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:8px 0 22px;"><tr><td align="center" '
        f'style="border-radius:12px;background:{ROSE};box-shadow:0 6px 18px -6px {ROSE_DK};">'
        f'<a href="{escape(url, quote=True)}" target="_blank" '
        f'style="display:inline-block;padding:13px 30px;font-family:{FONT};font-size:15px;'
        f'font-weight:600;color:#ffffff;text-decoration:none;border-radius:12px;'
        f'border:1px solid {ROSE_DK};">{escape(label)}</a>'
        '</td></tr></table>'
    )


def credentials(rows: list[tuple[str, str]]) -> str:
    """A dark inset panel listing label/value pairs (e.g. login credentials,
    a reminder breakdown, payment details).

    Mobile-first: label and value stack VERTICALLY (label above value) in each
    row, each on its own full-width line. A side-by-side two-column layout on a
    narrow phone forces a fixed-width label column that squeezes long values
    (M-Pesa numbers, emails, amounts) off-screen — the exact reason reminder
    emails read badly on phones. Stacked rows never overflow, and read fine on
    desktop too."""
    cells = ""
    for label, value in rows:
        cells += (
            f'<tr><td style="padding:10px 0 4px;font-family:{FONT};font-size:11px;'
            f'letter-spacing:.05em;text-transform:uppercase;color:{MUTED};">'
            f'{escape(label)}</td></tr>'
            f'<tr><td style="padding:0 0 12px;font-family:\'SFMono-Regular\',Consolas,monospace;'
            f'font-size:15px;line-height:1.4;color:#ffffff;font-weight:600;'
            f'word-break:break-word;overflow-wrap:anywhere;border-bottom:1px solid {BORDER};">'
            f'{escape(value)}</td></tr>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:4px 0 20px;background:{PANEL};border:1px solid {BORDER};'
        f'border-radius:14px;"><tr><td style="padding:6px 18px 8px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'{cells}</table></td></tr></table>'
    )


def breakdown(rows: list[tuple[str, str]], total: tuple[str, str] | None = None) -> str:
    """A compact, layered charge list — the block for money on a phone.

    Each charge is TWO stacked lines: the label, then its amount directly
    beneath it. Never two columns side by side: on a 360px screen a
    label/amount pair sharing a row leaves each side ~150px, so "Rent balance
    brought forward" wraps to three lines while its amount hangs alone in the
    right column — which is what made invoice emails read so badly.

    It is deliberately tighter than credentials(): 4px between the label and its
    amount, 10px between charges, one hairline rule per charge, and no uppercase
    label styling. credentials() spaces rows for a handful of login details; an
    invoice has six or more charges and needs the vertical room.

    The total gets a heavier rule above it and a larger figure, so the one
    number the tenant is looking for is findable without reading the list.
    """
    cells = ""
    for label, value in rows:
        cells += (
            f'<tr><td style="padding:10px 0 0;font-family:{FONT};font-size:12px;'
            f'line-height:1.35;color:{MUTED};">{escape(label)}</td></tr>'
            f'<tr><td style="padding:2px 0 10px;font-family:{FONT};font-size:16px;'
            f'line-height:1.3;color:#ffffff;font-weight:600;word-break:break-word;'
            f'border-bottom:1px solid {BORDER};">{escape(value)}</td></tr>'
        )

    if total is not None:
        label, value = total
        cells += (
            f'<tr><td style="padding:14px 0 0;font-family:{FONT};font-size:12px;'
            f'letter-spacing:.04em;text-transform:uppercase;color:{ACCENT};'
            f'font-weight:600;">{escape(label)}</td></tr>'
            f'<tr><td style="padding:2px 0 4px;font-family:{FONT};font-size:20px;'
            f'line-height:1.25;color:#ffffff;font-weight:700;word-break:break-word;">'
            f'{escape(value)}</td></tr>'
        )

    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:4px 0 18px;background:{PANEL};border:1px solid {BORDER};'
        f'border-radius:14px;"><tr><td style="padding:4px 16px 14px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'{cells}</table></td></tr></table>'
    )


def code_box(code: str, caption: str = "") -> str:
    """A large, centred, monospaced panel for an OTP / one-time code."""
    cap = (
        f'<div style="margin:0 0 8px;font-family:{FONT};font-size:12px;'
        f'letter-spacing:.06em;text-transform:uppercase;color:{MUTED};">{escape(caption)}</div>'
        if caption else ""
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:6px 0 22px;background:{PANEL};border:1px solid {BORDER};'
        f'border-radius:14px;"><tr><td align="center" style="padding:22px 16px;">{cap}'
        f'<div style="font-family:\'SFMono-Regular\',Consolas,monospace;font-size:34px;'
        f'font-weight:700;letter-spacing:.34em;color:#ffffff;padding-left:.34em;">'
        f'{escape(code)}</div></td></tr></table>'
    )


def steps(items: list[str]) -> str:
    lis = ""
    for i, it in enumerate(items, 1):
        lis += (
            f'<tr><td style="vertical-align:top;padding:0 12px 12px 0;width:26px;">'
            f'<div style="width:24px;height:24px;border-radius:50%;background:{ROSE};color:#fff;'
            f'font-family:{FONT};font-size:13px;font-weight:700;text-align:center;'
            f'line-height:24px;">{i}</div></td>'
            f'<td style="vertical-align:top;padding:0 0 12px;font-family:{FONT};'
            f'font-size:14px;line-height:1.55;color:{TEXT};">{it}</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:2px 0 18px;">{lis}</table>'
    )


# ── Page shell ───────────────────────────────────────────────────────────────
def render_email(
    *,
    heading: str,
    intro: str = "",
    blocks: list[str] | None = None,
    preheader: str = "",
    footer_note: str | None = None,
) -> str:
    """Wrap content blocks in the branded SahilPay shell and return full HTML."""
    body = ""
    if intro:
        body += paragraph(intro)
    for b in (blocks or []):
        body += b

    year_footer = (
        footer_note
        or "You're receiving this because you have a Sahil Pay account."
    )

    return f"""\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="color-scheme" content="dark">
<meta name="format-detection" content="telephone=no">
<title>{escape(heading)}</title>
<style>
  /* Mobile-first: inline styles below already fit a narrow phone; these media
     queries only WIDEN the layout on larger screens (Gmail/Apple Mail honour
     them, everyone else falls back to the roomy-enough inline defaults).
     100% width so the card never overflows a 320px viewport. */
  .sp-wrap {{ padding:20px 10px !important; }}
  .sp-card {{ padding:24px 18px !important; }}
  .sp-h1   {{ font-size:20px !important; }}
  @media only screen and (min-width:480px) {{
    .sp-wrap {{ padding:32px 12px !important; }}
    .sp-card {{ padding:34px 32px !important; }}
    .sp-h1   {{ font-size:22px !important; }}
  }}
  img {{ max-width:100%; height:auto; }}
</style>
</head>
<body style="margin:0;padding:0;background:{BG};width:100%;-webkit-text-size-adjust:100%;">
<span style="display:none;max-height:0;overflow:hidden;opacity:0;color:{BG};">{escape(preheader)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="sp-wrap" style="background:{BG};padding:24px 12px;">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;">
    <!-- Brand header (styled text only — Gmail/Outlook strip embedded SVG) -->
    <tr><td style="padding:4px 6px 18px;">
      <div style="font-family:Georgia,'Times New Roman',serif;font-size:20px;font-weight:700;letter-spacing:.14em;color:#ffffff;">SAHIL&nbsp;PAY</div>
      <div style="margin-top:2px;font-family:{FONT};font-size:9px;font-weight:600;letter-spacing:.35em;color:{MUTED};">SMART&nbsp;RENT&nbsp;COLLECTION</div>
    </td></tr>
    <!-- Card -->
    <tr><td class="sp-card" style="background:{CARD_BOT};background:linear-gradient(160deg,{CARD_TOP} 0%,{CARD_BOT} 100%);border:1px solid {BORDER};border-radius:20px;padding:24px 18px;">
      <h1 class="sp-h1" style="margin:0 0 18px;font-family:{FONT};font-size:20px;line-height:1.3;font-weight:700;color:#ffffff;">{escape(heading)}</h1>
      {body}
    </td></tr>
    <!-- Footer -->
    <tr><td style="padding:22px 8px 4px;">
      <p style="margin:0 0 6px;font-family:{FONT};font-size:12px;line-height:1.6;color:{MUTED};">{escape(year_footer)}</p>
      <p style="margin:0;font-family:{FONT};font-size:12px;color:{BORDER};">{branding.BRAND_NAME} · {branding.BRAND_SLOGAN.title()} · {branding.BRAND_LOCATION} · {branding.BRAND_PHONE} · {branding.BRAND_EMAIL}</p>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""
