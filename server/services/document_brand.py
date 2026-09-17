"""
services/document_brand.py — one landlord identity for every document and email.

WHAT A LANDLORD'S PAPERWORK CARRIES
-----------------------------------
Four things, on every receipt, report, lease and email sent from their account:

  1. theme colours   — Settings → Receipts (services/receipt_theme.py)
  2. logo            — Settings → General (landlords.logo_url)
  3. letterhead      — company name + address, or an uploaded letterhead banner
  4. contact details — phone, email, website shown to TENANTS

Nothing set? Each falls back to a clean default (Sahil Pay colours, the company
name as text, no contact line) so an account that never opened Settings still
produces tidy paperwork.

WHY ONE MODULE
--------------
The PDF letterhead, the receipt header and the email shell each used to read
the landlord separately, which is how a report came out with a phone number and
the email about it did not. Everything that draws a landlord now asks here.
"""

from __future__ import annotations

from services import receipt_theme


def contact_for(landlord) -> dict:
    """
    Contact details for tenants, falling back to the account's own login
    email/phone when the landlord has not filled the dedicated fields in.
    """
    user = getattr(landlord, "user", None)
    return {
        "phone": (getattr(landlord, "contact_phone", None)
                  or (getattr(user, "phone", None) if user else None) or ""),
        "email": (getattr(landlord, "contact_email", None)
                  or (getattr(user, "email", None) if user else None) or ""),
        "website": getattr(landlord, "website", None) or "",
    }


def for_landlord(landlord) -> dict:
    """Everything a document or email needs to wear this landlord's identity."""
    theme = receipt_theme.for_landlord(landlord) if landlord is not None \
        else receipt_theme.resolve(None)
    contact = contact_for(landlord) if landlord is not None \
        else {"phone": "", "email": "", "website": ""}
    return {
        "company_name":     getattr(landlord, "company_name", None) or "",
        "abbreviated_name": getattr(landlord, "abbreviated_name", None) or "",
        "address":          getattr(landlord, "company_address", None) or "",
        "logo_url":         getattr(landlord, "logo_url", None) or "",
        "letterhead_url":   getattr(landlord, "letterhead_url", None) or "",
        "signature_url":    getattr(landlord, "signature_url", None) or "",
        "primary":          theme["primary"],
        "secondary":        theme["secondary"],
        "phone":            contact["phone"],
        "email":            contact["email"],
        "website":          contact["website"],
    }


def contact_line(brand: dict, sep: str = " · ") -> str:
    """'0712 345 678 · rent@acme.co.ke · acme.co.ke' — only what is set."""
    website = (brand.get("website") or "").replace("https://", "").replace("http://", "").rstrip("/")
    return sep.join(p for p in (brand.get("phone"), brand.get("email"), website) if p)


def email_brand(landlord) -> dict | None:
    """
    The brand for an email sent FROM this landlord's account, with asset URLs
    made absolute (a mail client has no base URL to resolve "/uploads/..."
    against). None when there is no landlord — platform email stays Sahil Pay.
    """
    if landlord is None:
        return None
    from services.email_service import _absolute_url

    brand = for_landlord(landlord)
    for key in ("logo_url", "letterhead_url"):
        if brand[key]:
            brand[key] = _absolute_url(brand[key])
    return brand
