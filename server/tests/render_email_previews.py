"""
render_email_previews.py — render every transactional email to a file.

Emails cannot be judged by reading their builder: what matters is how the
finished HTML lays out on a 320px phone. This writes one .html per template so
they can be opened at phone width (and screenshotted by Playwright) and
inspected the way a tenant will actually see them.

    APP_ENV=development venv/bin/python tests/render_email_previews.py [outdir]

Writes to ./scratch/emails by default. Nothing here sends anything.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import email_templates as T   # noqa: E402


def _money(v) -> str:
    return f"KES {float(v):,.2f}"


def previews() -> dict[str, str]:
    """name -> full HTML. Realistic content: a long invoice is the hard case."""
    out: dict[str, str] = {}

    # --- The one that reads worst on a phone: a full monthly invoice ---------
    charges = [
        ("Rent — August 2026", _money(25000)),
        ("Rent balance brought forward from July 2026", _money(12500)),
        ("Water (meter 00942 → 00981, 39 units)", _money(4680)),
        ("Electricity (meter 0655 → 0712, 57 units)", _money(1710)),
        ("Garbage collection", _money(300)),
        ("Security — common area", _money(500)),
        ("Late payment penalty", _money(1000)),
    ]
    out["invoice_reminder"] = T.render_email(
        heading="Invoice — Riverside Apartments Ltd",
        intro="Dear Amina,",
        blocks=[
            T.note("Unit B-14 · Riverside Apartments"),
            T.breakdown(charges, total=("Total due", _money(45690))),
            T.note("<strong>How to pay</strong>"),
            T.breakdown([
                ("M-Pesa Paybill", "247247"),
                ("Account number", "RIVERSIDE-B14-2026"),
                ("Due date", "5 September 2026"),
            ]),
            T.breakdown([
                ("From", "Riverside Apartments Ltd"),
                ("Location", "Argwings Kodhek Road, Kilimani, Nairobi"),
                ("Phone", "+254 700 123 456"),
                ("Email", "accounts@riversideapartments.co.ke"),
            ]),
        ],
        preheader="Invoice: KES 45,690.00 outstanding.",
        footer_note="Sent by Riverside Apartments Ltd via Sahil Pay.",
    )

    out["balance_reminder"] = T.render_email(
        heading="Payment reminder — Riverside Apartments Ltd",
        intro="Hi Brian,",
        blocks=[
            T.note("Unit A-03 · Riverside Apartments"),
            T.breakdown(
                [("Rent balance — July 2026", _money(12500)),
                 ("Water", _money(2340))],
                total=("Total due", _money(14840)),
            ),
            T.note("<strong>How to pay</strong>"),
            T.breakdown([("M-Pesa Paybill", "247247"), ("Account number", "RIVERSIDE-A03")]),
        ],
        preheader="Payment reminder: KES 14,840.00 outstanding.",
    )

    out["welcome"] = T.render_email(
        heading="Welcome to Riverside Apartments Ltd",
        intro=(
            "Karibu Cynthia! Welcome home to Unit C-07 at Riverside Apartments. "
            "We're glad to have you with us."
        ),
        blocks=[
            T.breakdown([
                ("Your unit", "C-07 · Riverside Apartments"),
                ("M-Pesa Paybill", "247247"),
                ("Your account number", "RIVERSIDE-C07"),
                ("Any questions, call", "+254 700 123 456"),
            ]),
            T.note("Wishing you a wonderful stay."),
        ],
        preheader="Welcome to your new home.",
    )

    out["otp"] = T.render_email(
        heading="Your login code",
        intro="Hi Daniel, use this code to sign in to your Sahil Pay tenant portal.",
        blocks=[T.code_box("482913", "One-time code"),
                T.note("This code expires in 10 minutes.")],
        preheader="Your Sahil Pay login code.",
    )

    out["team_credentials"] = T.render_email(
        heading="Your Sahil Pay login",
        intro="Hi Esther, an account has been created for you at Riverside Apartments Ltd.",
        blocks=[
            T.credentials([
                ("Email", "esther.njeri@riversideapartments.co.ke"),
                ("Username", "esther.njeri"),
                ("Temporary password", "Kx7#mQp2Rt9v"),
            ]),
            T.button("Sign in", "https://sahilpay.co.ke/login"),
            T.note("You'll be asked to choose your own password on first sign-in."),
        ],
        preheader="Your Sahil Pay account is ready.",
    )

    out["receipt"] = T.render_email(
        heading="Payment received — thank you",
        intro="Hi Felix, we've received your payment. Your receipt is attached as a PDF.",
        blocks=[
            T.breakdown([
                ("Receipt number", "RCP-2026-004182"),
                ("Paid on", "3 August 2026"),
                ("Method", "M-Pesa"),
            ], total=("Amount received", _money(25000))),
        ],
        preheader="Payment received — receipt attached.",
    )

    out["owner_statement"] = T.render_email(
        heading="Riverside Apartments — July 2026",
        intro=(
            "Hi James, here is the statement for <strong>Riverside Apartments</strong> "
            "covering July 2026. The full breakdown is attached as a PDF."
        ),
        blocks=[T.note("You can also sign in to Sahil Pay to see live figures.")],
        preheader="Riverside Apartments statement for July 2026 is attached.",
        footer_note="Sent by Raa Property Management via Sahil Pay.",
    )

    return out


def main() -> None:
    outdir = sys.argv[1] if len(sys.argv) > 1 else "scratch/emails"
    os.makedirs(outdir, exist_ok=True)

    rendered = previews()
    for name, html in rendered.items():
        path = os.path.join(outdir, f"{name}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"wrote {path}")

    index = "".join(
        f'<li><a href="{name}.html">{name}</a></li>' for name in sorted(rendered)
    )
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(
            "<!doctype html><meta charset=utf-8>"
            "<title>Sahil Pay email previews</title>"
            "<body style='font-family:system-ui;padding:24px'>"
            f"<h1>Email previews</h1><ul>{index}</ul></body>"
        )
    print(f"wrote {os.path.join(outdir, 'index.html')}")


if __name__ == "__main__":
    main()
