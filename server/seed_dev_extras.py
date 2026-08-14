"""
seed_dev_extras.py — switch on the opt-in features so they can be seen locally.

seed.py builds a realistic estate but deliberately leaves two of the newer
features in their shipped default state, which is "off":

  * seed_tutorials.py writes every help article UNPUBLISHED, because in
    production the admin publishes each page when it is ready;
  * eTIMS is opt-in per account AND per property, so a freshly seeded landlord
    has no compliance surfaces at all — which is correct, but means the eTIMS
    Register, the KRA report and the nav links they hang off cannot be
    exercised or walked through.

This script flips both ON for development so the browser walkthrough has
something to drive. It is NOT part of the production seed and must never be
pointed at production.

    APP_ENV=development venv/bin/python seed_dev_extras.py
"""

from __future__ import annotations

import sys

from app import create_app
from extensions import db


def main() -> int:
    app = create_app()
    with app.app_context():
        import models as m

        if app.config.get("ENV_NAME") == "production":
            print("Refusing to run against production.", file=sys.stderr)
            return 1

        # --- Publish the seeded help library ---------------------------------
        categories = db.session.query(m.TutorialCategory).all()
        articles = db.session.query(m.TutorialArticle).all()
        for category in categories:
            category.is_published = True
        for article in articles:
            article.is_published = True

        # --- Switch eTIMS on for the primary demo landlord -------------------
        # One account only: leaving the others off keeps the "opted-out accounts
        # see nothing" path represented in the same database.
        landlord = (
            db.session.query(m.Landlord)
            .join(m.User, m.Landlord.user_id == m.User.id)
            .filter(m.User.email == "landlord@sahilpay.test")
            .first()
        )
        properties_enabled = 0
        if landlord is not None:
            settings = (
                db.session.query(m.LandlordSettings)
                .filter_by(landlord_id=landlord.id)
                .first()
            )
            if settings is not None:
                settings.etims_enabled = True
            for prop in db.session.query(m.Property).filter_by(landlord_id=landlord.id):
                prop.etims_enabled = True
                properties_enabled += 1

        db.session.commit()

        print(f"[seed_dev_extras] published {len(categories)} categories, "
              f"{len(articles)} articles")
        print(f"[seed_dev_extras] eTIMS enabled on {properties_enabled} properties "
              f"for landlord@sahilpay.test")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
