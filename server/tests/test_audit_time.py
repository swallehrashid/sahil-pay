"""Audit trail times are UTC on the wire and filtered by Nairobi calendar days."""

from datetime import datetime

import pytest

from models import AuditLog
from tests.test_access_control import _auth, _make_landlord, _token


@pytest.fixture()
def client(app):
    return app.test_client()


def test_timestamps_carry_the_utc_marker_and_nairobi_days_filter_correctly(app, client, db_session):
    landlord, user = _make_landlord(db_session, "au")
    # 00:30 in Nairobi on 27 Sep is 21:30 UTC on 26 Sep.
    early = AuditLog(landlord_id=landlord.id, actor_user_id=user.id, action="x",
                     entity_type="t", description="just after midnight Nairobi",
                     created_at=datetime(2026, 9, 26, 21, 30))
    # 23:30 in Nairobi on 26 Sep is 20:30 UTC on 26 Sep — belongs to the 26th.
    late_prev = AuditLog(landlord_id=landlord.id, actor_user_id=user.id, action="x",
                         entity_type="t", description="late on the 26th",
                         created_at=datetime(2026, 9, 26, 20, 30))
    db_session.add_all([early, late_prev])
    db_session.flush()
    h = _auth(_token(app, user, landlord_id=landlord.id))

    rows = client.get("/api/audit/?start_date=2026-09-27&end_date=2026-09-27", headers=h).get_json()
    items = rows.get("logs") or rows.get("items") or rows.get("audit_logs")
    descs = [r["description"] for r in items]
    assert descs == ["just after midnight Nairobi"]
    assert items[0]["created_at"] == "2026-09-26T21:30:00Z"

    bad = client.get("/api/audit/?start_date=27-09-2026", headers=h)
    assert bad.status_code == 400
