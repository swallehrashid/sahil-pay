"""07… and 254… are the same number everywhere: saving, signing in, and sending."""


import pytest

from models import Tenant
from services import sms_service
from services.phone_service import canonical_phone, phone_key
from tests.test_access_control import (
    _auth, _make_landlord, _make_property, _make_unit, _token,
)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.mark.parametrize("raw", [
    "0712430742", "0712 430 742", "712430742", "254712430742",
    "+254712430742", "+254 712-430-742",
])
def test_every_way_of_typing_one_number_stores_the_same(raw):
    assert canonical_phone(raw) == "254712430742"


@pytest.mark.parametrize("raw", ["0112345678", "254112345678", "112345678"])
def test_01_numbers_are_kenyan_too(raw):
    assert canonical_phone(raw) == "254112345678"


@pytest.mark.parametrize("raw", ["12345", "0812430742", "+447912345678", "", None, "07124307421"])
def test_non_kenyan_or_malformed_numbers_are_rejected(raw):
    assert canonical_phone(raw) is None


@pytest.fixture()
def home(app, db_session):
    landlord, user = _make_landlord(db_session, "ph")
    prop = _make_property(db_session, landlord, "Ph")
    unit = _make_unit(db_session, prop, "A1")
    h = _auth(_token(app, user, landlord_id=landlord.id))
    return landlord, h, unit


def _unique_number():
    import random
    return f"07{random.randint(10000000, 99999999)}"


def test_tenant_saved_with_07_is_stored_as_254(client, home):
    landlord, h, unit = home
    local = _unique_number()
    r = client.post("/api/tenants/", headers=h, json={
        "unit_id": unit.id, "first_name": "Zawadi", "last_name": "Otieno", "phone": local,
    })
    assert r.status_code == 201, r.get_json()
    t =Tenant.query.filter_by(unit_id=unit.id, is_deleted=False).one()
    assert t.phone == "254" + local[1:]


def test_bad_number_is_refused_with_the_format_rule(client, home):
    landlord, h, unit = home
    r = client.post("/api/tenants/", headers=h, json={
        "unit_id": unit.id, "first_name": "Zawadi", "last_name": "Otieno", "phone": "12345",
    })
    assert r.status_code == 400
    assert "0712 345 678" in r.get_json()["error"]


@pytest.mark.parametrize("stored,typed", [
    ("254{n}", "0{n}"),          # saved 254…, signs in with 07…
    ("0{n}", "254{n}"),          # legacy row saved 07…, signs in with 254…
    ("254{n}", "+254 {n}"),
])
def test_tenant_can_request_a_login_code_with_either_format(client, home, db_session, monkeypatch, stored, typed):
    landlord, h, unit = home
    n = _unique_number()[1:]
    t = Tenant(landlord_id=landlord.id, unit_id=unit.id, first_name="Login",
               last_name="Test", phone=stored.format(n=n))
    db_session.add(t)
    db_session.flush()

    sent = []
    from routes import otp_routes
    monkeypatch.setattr(otp_routes.send_otp_sms, "delay", lambda ident, code, name: sent.append((ident, code)))

    r = client.post("/api/otp/request", json={"identifier": typed.format(n=n)})
    assert r.status_code == 200, r.get_json()
    assert sent and sent[0][0] == "254" + n

    code = sent[0][1]
    r = client.post("/api/otp/verify", json={"identifier": typed.format(n=n), "code": code})
    assert r.status_code == 200, r.get_json()


def test_the_sms_provider_is_always_sent_254(app, monkeypatch):
    posted = {}

    def fake_post(path, body):
        posted.update(body)
        return {"response-code": 200, "message_id": "m1"}

    monkeypatch.setattr(sms_service, "_post", fake_post)
    monkeypatch.setitem(app.config, "FLUXSMS_API_KEY", "test-key")
    with app.app_context():
        sms_service.send_sms("0712 430 742", "hello")
    assert posted["phone"] == "254712430742"


def test_tenant_search_by_07_finds_254_number(client, home, db_session):
    landlord, h, unit = home
    n = _unique_number()[1:]
    db_session.add(Tenant(landlord_id=landlord.id, unit_id=unit.id, first_name="Search",
                          last_name="Me", phone="254" + n))
    db_session.flush()
    got = client.get(f"/api/tenants/?search=0{n[:5]}", headers=h).get_json()
    assert [t["phone"] for t in got["tenants"]] == ["254" + n]


def test_phone_key_ignores_the_country_code():
    assert phone_key("0712430742") == phone_key("+254712430742") == "712430742"
