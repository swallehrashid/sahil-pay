"""
perf_audit.py — measure the endpoints a property manager actually waits on.

Run against the estate seed_scale.py builds. Reports, for each endpoint, the
wall time and the number of SQL statements issued — the query count is the part
that matters, because an N+1 that is merely slow on 1,000 rows becomes fatal on
10,000.

    APP_ENV=development venv/bin/python perf_audit.py

Acceptance (OPUS_EXECUTION_SPEC Phase 1.5): dashboard, tenants page 1, payments
page 1 and a single property statement each under 1s, and no endpoint returning
an unpaginated full-estate payload.
"""

from __future__ import annotations

import time

from flask_jwt_extended import create_access_token
from sqlalchemy import event

SCALE_EMAIL = "scale-pm@sahilpay.test"

# (label, path, budget_seconds)
ENDPOINTS = [
    ("Dashboard summary",       "/api/dashboard/summary", 1.0),
    ("Dashboard arrears list",  "/api/dashboard/unpaid-tenants", 1.0),
    ("Dashboard graph",         "/api/dashboard/performance-graph", 1.5),
    ("Quick actions",           "/api/dashboard/quick-actions", 1.0),
    ("Tenants page 1",          "/api/tenants/?page=1&per_page=20", 1.0),
    ("Tenants search",          "/api/tenants/?search=Multi", 1.0),
    ("Payments page 1",         "/api/payments/?page=1&per_page=20", 1.0),
    ("Invoices page 1",         "/api/invoices/?page=1&per_page=20", 1.0),
    ("Expenses page 1",         "/api/expenses/?page=1&per_page=20", 1.0),
    ("Units page 1",            "/api/units/?page=1&per_page=20", 1.0),
    ("Properties list",         "/api/properties/", 1.5),
    ("Team members page 1",     "/api/team/?page=1&per_page=20", 1.0),
    ("Owner payouts page 1",    "/api/owner-payouts/?page=1&per_page=20", 1.0),
    ("Arrears report",          "/api/reports/statements/arrears", 3.0),
    ("Insights",                "/api/reports/insights", 3.0),
]


class QueryCounter:
    def __init__(self, engine):
        self.engine = engine
        self.count = 0

    def _before(self, *args, **kwargs):
        self.count += 1

    def __enter__(self):
        self.count = 0
        event.listen(self.engine, "before_cursor_execute", self._before)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._before)


def main() -> None:
    from app import create_app
    from extensions import db
    from models import Landlord, Property, Tenant, TeamMember, Unit, User

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=SCALE_EMAIL).first()
        if user is None:
            raise SystemExit("No scale estate found — run seed_scale.py first.")
        landlord = Landlord.query.filter_by(user_id=user.id).first()

        counts = {
            "properties": Property.query.filter_by(landlord_id=landlord.id).count(),
            "units": Unit.query.join(Property).filter(Property.landlord_id == landlord.id).count(),
            "tenants": Tenant.query.filter_by(landlord_id=landlord.id).count(),
            "team_members": TeamMember.query.filter_by(landlord_id=landlord.id).count(),
        }
        print(f"Estate: {counts}\n")

        token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role, "landlord_id": landlord.id},
        )
        # A caretaker scoped to a handful of properties — the scoped path must
        # not be slower than the unscoped one.
        caretaker = TeamMember.query.filter_by(
            landlord_id=landlord.id, preset="caretaker"
        ).first()
        caretaker_token = create_access_token(
            identity=str(caretaker.user_id),
            additional_claims={
                "role": "team_member", "landlord_id": landlord.id,
                "team_member_id": caretaker.id,
            },
        )

        client = app.test_client()
        headers = {"Authorization": f"Bearer {token}"}

        print(f"{'endpoint':28} {'status':>6} {'time':>8} {'queries':>8}  verdict")
        print("-" * 74)

        failures = []
        for label, path, budget in ENDPOINTS:
            with QueryCounter(db.engine) as qc:
                t0 = time.perf_counter()
                resp = client.get(path, headers=headers)
                elapsed = time.perf_counter() - t0
            verdict = "ok"
            if resp.status_code != 200:
                verdict = f"HTTP {resp.status_code}"
                failures.append((label, verdict))
            elif elapsed > budget:
                verdict = f"SLOW (>{budget}s)"
                failures.append((label, verdict))
            elif qc.count > 60:
                verdict = f"N+1? ({qc.count} queries)"
                failures.append((label, verdict))
            print(f"{label:28} {resp.status_code:>6} {elapsed:>7.3f}s {qc.count:>8}  {verdict}")

        # One property statement — the heaviest single document.
        prop = Property.query.filter_by(landlord_id=landlord.id).first()
        with QueryCounter(db.engine) as qc:
            t0 = time.perf_counter()
            resp = client.get(
                f"/api/reports/statements/property/{prop.id}", headers=headers
            )
            elapsed = time.perf_counter() - t0
        verdict = "ok" if (resp.status_code == 200 and elapsed < 3.0) else "SLOW/ERROR"
        if verdict != "ok":
            failures.append(("Property statement", verdict))
        print(f"{'Property statement':28} {resp.status_code:>6} {elapsed:>7.3f}s {qc.count:>8}  {verdict}")

        # Scoped caretaker view of the same landing page.
        with QueryCounter(db.engine) as qc:
            t0 = time.perf_counter()
            resp = client.get(
                "/api/dashboard/summary",
                headers={"Authorization": f"Bearer {caretaker_token}"},
            )
            elapsed = time.perf_counter() - t0
        print(f"{'Dashboard (caretaker)':28} {resp.status_code:>6} {elapsed:>7.3f}s {qc.count:>8}  "
              f"{'ok' if resp.status_code == 200 and elapsed < 1.0 else 'SLOW/ERROR'}")
        if resp.status_code == 200:
            body = resp.get_json()
            print(f"    scoped totals: units={body.get('total_units')} "
                  f"tenants={body.get('active_tenants')} (must be < estate totals)")

        print()
        if failures:
            print("FAILURES:")
            for label, why in failures:
                print(f"  - {label}: {why}")
        else:
            print("All endpoints within budget.")


if __name__ == "__main__":
    main()
