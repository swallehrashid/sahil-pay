"""
seed_tutorials.py — the "Tax Compliance (KRA & eTIMS)" help category and its
seven article stubs (SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §7).

Everything is seeded as an UNPUBLISHED DRAFT, on purpose. These are skeletons —
headings plus `<!-- IMAGE: … -->` markers showing where screenshots belong.
Swalleh writes the real bodies, drops the screenshots in through the CMS, and
publishes when each page is ready. Until he does, nothing here is visible to a
single user.

Idempotent: re-running updates the stub bodies of articles that are STILL
drafts and leaves anything already published completely alone, so a redeploy
can never overwrite finished work.

    APP_ENV=development venv/bin/python seed_tutorials.py
"""

from __future__ import annotations

import sys

from app import app
from extensions import db
from models import TutorialArticle, TutorialCategory
from services.tutorial_service import slugify

CATEGORY = {
    "name": "Tax Compliance (KRA & eTIMS)",
    "slug": "tax-compliance-kra-etims",
    "icon": "landmark",
    "description": ("How rental tax works in Kenya, how to issue eTIMS invoices "
                    "through KRA's free channels, and how to record them here."),
    # Visible to every role once published — each ARTICLE narrows its own audience.
    "visible_to_roles": None,
    "sort_order": 0,
}

ALL_STAFF = ["landlord", "property_manager", "team_member"]

ARTICLES = [
    {
        "title": "How rental taxes work in Kenya — the basics",
        "roles": None,
        "summary": "MRI, what eTIMS invoices are, and who is responsible for what.",
        "body": """
## What Monthly Rental Income (MRI) tax is

<!-- IMAGE: KRA MRI summary / rate card -->

- Charged at **7.5% of GROSS rent received**. No deductions are allowed under MRI.

## Taxed when RECEIVED, not when due

- If a tenant clears three months of arrears in March, all of it is March income.
- Rent invoiced but unpaid is not taxed until it actually arrives.

## One return per landlord per month

- Due by the **20th of the following month**.
- Collected nothing? You still file — a **NIL return**.

## What eTIMS invoices are

- Free to issue. An eTIMS invoice is **not a tax** — it is the paper trail.

<!-- IMAGE: example eTIMS invoice -->

## Residential rent is VAT-exempt

- This layer never computes VAT, because residential rent does not attract it.

## Who does what

<!-- IMAGE: simple tenant / landlord / PM / SahilPay responsibility diagram -->

> Automated eTIMS from inside SahilPay is in development — meanwhile these
> guides use KRA's free official channels.
""",
    },
    {
        "title": "For Tenants: your receipt and your KRA PIN",
        "roles": ["tenant"],
        "summary": "When your PIN matters, how to add it, and how to read your receipt.",
        "body": """
## When your KRA PIN matters

- Mainly if you are a **business tenant** claiming rent as an expense.
- If you are renting a home personally, you can leave it blank.

## Adding your PIN

<!-- IMAGE: tenant portal profile, KRA PIN field -->

## Reading the eTIMS number and QR on a receipt

<!-- IMAGE: receipt with the eTIMS block highlighted -->
""",
    },
    {
        "title": "For Landlords: issue eTIMS invoices for rent (step by step)",
        "roles": ALL_STAFF,
        "summary": "One-time eTIMS Lite activation, then the routine for each payment.",
        "body": """
## One-time activation (eTIMS Lite)

<!-- IMAGE: eCitizen sign-in -->
<!-- IMAGE: *222# USSD menu -->
<!-- IMAGE: eTIMS Non-VAT app home screen -->

## Adding your tenants as customers

<!-- IMAGE: add customer screen, PIN validation -->

## Issuing an invoice after a payment

- Describe it plainly: `Rent — Unit A1 — Month YYYY`.

<!-- IMAGE: single invoice entry -->
<!-- IMAGE: bulk invoice entry -->

## Recording the number back in SahilPay

<!-- IMAGE: the eTIMS Register with numbers being typed in -->

## Rhythm

- Issue within a few days, and **always inside the same calendar month**.
""",
    },
    {
        "title": "For Landlords: filing your 7.5% MRI by the 20th",
        "roles": ALL_STAFF,
        "summary": "Pull the report, read the consolidated figure, file and pay.",
        "body": """
## Pull your KRA Monthly Report

<!-- IMAGE: Reports → KRA Monthly Report -->

## The consolidated figure is what you file

- Per-property numbers are operational. The **consolidated per-landlord** total
  is the filing figure.

## Filing on iTax / eRITS

<!-- IMAGE: iTax MRI return -->
<!-- IMAGE: eRITS submission -->

## Paying

- M-Pesa **Paybill 572572**.

<!-- IMAGE: M-Pesa payment confirmation -->

## NIL months

- Collected nothing? File a NIL return anyway.

## Worked example — January, February, March

<!-- IMAGE: three-month worked example including an arrears payment -->
""",
    },
    {
        "title": "For Property Managers: rent, commissions, and payouts",
        "roles": ["property_manager", "team_member"],
        "summary": "Whose PIN goes on what, and how commission invoices work.",
        "body": """
## Rent invoices go under EACH LANDLORD's PIN

- Even though the money passes through your paybill, the **owner** is the seller.
- SahilPay holds a per-property owner PIN for exactly this reason.

<!-- IMAGE: property settings showing the owner's KRA PIN -->

## Your commission is your own sale

- On payout you issue an eTIMS invoice under **YOUR** PIN, to the landlord, for
  the commission amount.
- Base is **rent collected only** — deposits are excluded.

<!-- IMAGE: payout statement with the commission eTIMS number -->

## Delegating to team members

<!-- IMAGE: team member edit screen, per-property tax compliance checklist -->

## A batch routine that works

- Daily or twice-weekly, straight from the Register.

## Optional: KRA tax-agent appointment

- Some managers get appointed as tax agents to file MRI centrally. Talk to KRA —
  SahilPay does not handle this.
""",
    },
    {
        "title": "Your SahilPay subscription and eTIMS",
        "roles": ["landlord", "property_manager"],
        "summary": "Where to find the eTIMS number on your SahilPay receipt.",
        "body": """
## SahilPay issues you an eTIMS invoice

<!-- IMAGE: billing section, subscription receipt with eTIMS number -->

## Why it matters

- It is your expense record.
- Deductible if you are on the **normal** tax regime — **not** under MRI, which
  allows no deductions.
""",
    },
    {
        "title": "Deadlines cheat-sheet",
        "roles": None,
        "summary": "The whole calendar in one paragraph.",
        "body": """
## The calendar

- **Tenants:** pay per your lease.
- **Landlords:** issue the eTIMS invoice when the payment lands — same calendar
  month at the latest.
- **File and pay 7.5%** on last month's collections by the **20th**.
- **Collected nothing?** File NIL.

<!-- IMAGE: simple month timeline — rent in, invoice issued, file by the 20th -->
""",
    },
]


def seed_tutorials() -> dict:
    category = (
        db.session.query(TutorialCategory)
        .filter_by(slug=CATEGORY["slug"]).first()
    )
    if category is None:
        category = TutorialCategory(
            name             = CATEGORY["name"],
            slug             = CATEGORY["slug"],
            icon             = CATEGORY["icon"],
            description      = CATEGORY["description"],
            visible_to_roles = CATEGORY["visible_to_roles"],
            sort_order       = CATEGORY["sort_order"],
            is_published     = False,
        )
        db.session.add(category)
        db.session.flush()
        created_category = True
    else:
        created_category = False

    created = updated = skipped = 0
    for index, spec in enumerate(ARTICLES):
        slug = slugify(spec["title"])
        article = db.session.query(TutorialArticle).filter_by(slug=slug).first()

        if article is None:
            db.session.add(TutorialArticle(
                category_id      = category.id,
                title            = spec["title"],
                slug             = slug,
                summary          = spec["summary"],
                body_markdown    = spec["body"].strip(),
                sort_order       = index,
                visible_to_roles = spec["roles"],
                is_published     = False,
            ))
            created += 1
        elif article.is_published:
            # Already finished and live — never overwrite real content.
            skipped += 1
        else:
            article.title            = spec["title"]
            article.summary          = spec["summary"]
            article.body_markdown    = spec["body"].strip()
            article.sort_order       = index
            article.visible_to_roles = spec["roles"]
            updated += 1

    db.session.commit()
    return {"category_created": created_category, "articles_created": created,
            "articles_updated": updated, "published_left_alone": skipped}


if __name__ == "__main__":
    with app.app_context():
        result = seed_tutorials()
    print(f"[seed_tutorials] {result}")
    print("[seed_tutorials] All content is UNPUBLISHED — publish from the "
          "admin portal when each page is ready.")
    sys.exit(0)
