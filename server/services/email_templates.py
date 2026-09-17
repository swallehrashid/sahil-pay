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
def _recolour_for_brand(html: str, brand: dict) -> str:
    """
    Re-ink content blocks for a landlord's light letterhead email.

    Every block builder above draws for the dark Sahil shell with the palette
    constants inline (email clients strip <style>, so inline is the only
    option). Rather than a second copy of every builder, the palette's exact
    hex values are swapped for the landlord's here — they are distinctive
    enough that nothing else in a message carries them. White text is the one
    colour shared with buttons, so button text is protected first.
    """
    from services import receipt_theme

    primary = brand.get("primary") or "#0f0246"
    secondary = brand.get("secondary") or "#200497"
    html = html.replace("color:#ffffff;text-decoration:none", "color:#FFFFFE;text-decoration:none")
    html = html.replace("color:#ffffff", f"color:{primary}")
    html = html.replace("#FFFFFE", "#ffffff")
    for old, new in (
        (TEXT, "#1f2430"),
        (MUTED, "#5b6070"),
        (PANEL, receipt_theme.tint(primary, 0.95)),
        (BORDER, receipt_theme.tint(primary, 0.84)),
        (ROSE_DK, secondary),
        (ROSE, secondary),
        (ACCENT, secondary),
    ):
        html = html.replace(old, new)
    return html


def _branded_shell(*, heading: str, body: str, preheader: str, footer_note: str | None,
                   brand: dict) -> str:
    """
    An email sent FROM a landlord's account, in the landlord's identity: their
    letterhead (uploaded banner, or logo + company name + address), their theme
    colours, and their contact details in the footer. Sahil Pay appears only as
    the small "sent via" credit — the tenant's relationship is with the landlord.
    """
    from services import receipt_theme

    primary = brand.get("primary") or "#0f0246"
    secondary = brand.get("secondary") or "#200497"
    page_bg = receipt_theme.tint(primary, 0.95)
    company = escape(brand.get("company_name") or "")
    address = escape(brand.get("address") or "")

    if brand.get("letterhead_url"):
        head = (f'<img src="{escape(brand["letterhead_url"], quote=True)}" alt="{company}" '
                f'width="560" style="display:block;width:100%;max-width:560px;height:auto;border:0;">')
    else:
        logo = (f'<td style="padding-right:12px;vertical-align:middle;" width="56">'
                f'<img src="{escape(brand["logo_url"], quote=True)}" alt="" width="52" '
                f'style="display:block;width:52px;height:auto;max-height:52px;border:0;"></td>'
                if brand.get("logo_url") else "")
        head = (
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'{logo}<td style="vertical-align:middle;">'
            f'<div style="font-family:{FONT};font-size:19px;font-weight:700;color:{primary};">{company}</div>'
            + (f'<div style="margin-top:2px;font-family:{FONT};font-size:12px;color:#5b6070;">{address}</div>' if address else "")
            + '</td></tr></table>'
        )

    from services.document_brand import contact_line
    contact = escape(contact_line(brand))
    footer = escape(footer_note or f"Sent by {brand.get('company_name') or 'your landlord'} via Sahil Pay.")

    return f"""\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="color-scheme" content="light">
<meta name="format-detection" content="telephone=no">
<title>{escape(heading)}</title>
<style>
  .sp-wrap {{ padding:16px 8px !important; }}
  .sp-card {{ padding:22px 18px !important; }}
  @media only screen and (min-width:480px) {{
    .sp-wrap {{ padding:28px 12px !important; }}
    .sp-card {{ padding:32px 32px !important; }}
  }}
  img {{ max-width:100%; height:auto; }}
</style>
</head>
<body style="margin:0;padding:0;background:{page_bg};width:100%;-webkit-text-size-adjust:100%;">
<span style="display:none;max-height:0;overflow:hidden;opacity:0;color:{page_bg};">{escape(preheader)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="sp-wrap" style="background:{page_bg};padding:20px 10px;">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;background:#ffffff;border-radius:16px;border-top:5px solid {secondary};">
    <tr><td style="padding:20px 22px 14px;border-bottom:1px solid {receipt_theme.tint(primary, 0.88)};">{head}</td></tr>
    <tr><td class="sp-card" style="padding:22px 18px;">
      <h1 style="margin:0 0 16px;font-family:{FONT};font-size:20px;line-height:1.3;font-weight:700;color:{primary};">{escape(heading)}</h1>
      {body}
    </td></tr>
    <tr><td style="padding:16px 22px 20px;background:{receipt_theme.tint(primary, 0.97)};border-radius:0 0 16px 16px;">
      <p style="margin:0 0 4px;font-family:{FONT};font-size:13px;font-weight:600;color:{primary};">{company}</p>
      {f'<p style="margin:0 0 4px;font-family:{FONT};font-size:12px;color:#5b6070;">{address}</p>' if address else ''}
      {f'<p style="margin:0 0 8px;font-family:{FONT};font-size:12px;color:#5b6070;">{contact}</p>' if contact else ''}
      <p style="margin:0;font-family:{FONT};font-size:11px;color:#8a8fa0;">{footer}</p>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


def render_email(
    *,
    heading: str,
    intro: str = "",
    blocks: list[str] | None = None,
    preheader: str = "",
    footer_note: str | None = None,
    brand: dict | None = None,
) -> str:
    """
    Wrap content blocks in an email shell and return full HTML.

    `brand` (services/document_brand.email_brand) makes it the LANDLORD's
    email: their letterhead, logo, colours and contact details. Omitted, it is
    the Sahil Pay shell — used for platform email (sign-in codes, verification,
    billing) that Sahil Pay sends as itself.
    """
    body = ""
    if intro:
        body += paragraph(intro)
    for b in (blocks or []):
        body += b

    if brand:
        return _branded_shell(heading=heading, body=_recolour_for_brand(body, brand),
                              preheader=preheader, footer_note=footer_note, brand=brand)

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
