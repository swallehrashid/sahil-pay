"""
HTTP-level portal & access-control checks against the running API (localhost:5000).

Covers scenario-catalogue sections B (team), C (tenant), D (admin incl. renamed
Client Support), E (affiliate), F (cross-cutting auth & isolation). Read-only /
consent-based — does not mutate seed money data.

Run with the Flask server up:  venv/bin/python sim_http_checks.py
"""
import sys
import requests

BASE = "http://localhost:5000/api"
FAILS = []
N = 0


def check(cond, label, detail=""):
    global N
    N += 1
    if cond:
        print(f"   ✓ {label}")
    else:
        print(f"   ✗ FAIL: {label}  {detail}")
        FAILS.append(label)


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        return None, r
    return r.json().get("access_token"), r


def H(token):
    return {"Authorization": f"Bearer {token}"}


def unwrap(data):
    """Return the list payload from either a bare list or a paginated dict
    (the API uses various keys: items/properties/landlords/results/data)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "properties", "landlords", "results", "data", "tenants", "referrals"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def latest_otp_code(identifier):
    """Read the freshest un-used OTP code for an identifier straight from the DB.
    Codes are stored HASHED, so we brute-force the 6-digit space against the hash
    (fine for a test harness) — or better, pull from the app log. Simplest: query
    the app to re-generate is not possible, so we scan the flask log."""
    import re
    import hashlib
    from datetime import datetime, timezone
    # Pull the newest code from the flask log line we emit in simulation mode.
    log = "/tmp/claude-1000/-home-swalleh-projects-sahil-pay/c1709bcf-7acf-4a0b-b679-a08319eb0924/scratchpad/flask.log"
    try:
        lines = [l for l in open(log) if "login code is" in l and identifier in l]
        if lines:
            mo = re.search(r"login code is (\d{6})", lines[-1])
            if mo:
                return mo.group(1)
    except FileNotFoundError:
        pass
    return None


print("=== F1/F6: auth + role login ===")
admin_t, _ = login("admin@sahilpay.test", "Admin@123")
land_t, _ = login("landlord@sahilpay.test", "Landlord@123")
sunrise_t, _ = login("sunrise@sahilpay.test", "Sunrise@123")
editor_t, _ = login("caretaker@sahilpay.test", "Caretaker@123")
viewer_t, _ = login("viewer.acme@sahilpay.test", "Viewer@123")
check(admin_t is not None, "admin login")
check(land_t is not None, "landlord (Acme) login")
check(sunrise_t is not None, "landlord (Sunrise) login")
check(editor_t is not None, "team member editor login")
check(viewer_t is not None, "team member viewer login")

print("\n=== F1: bad credentials rejected ===")
_, r = login("landlord@sahilpay.test", "wrongpassword")
check(r.status_code in (400, 401), "wrong password rejected", f"got {r.status_code}")
r = requests.get(f"{BASE}/properties/", headers=H("garbage.token.here"))
check(r.status_code in (401, 422), "invalid JWT rejected", f"got {r.status_code}")
r = requests.get(f"{BASE}/properties/")
check(r.status_code in (401, 422), "missing JWT rejected", f"got {r.status_code}")

print("\n=== F6: cross-landlord isolation ===")
# Acme landlord lists their properties; grab one id. Sunrise must not see it.
r = requests.get(f"{BASE}/properties/", headers=H(land_t))
acme_prop_list = unwrap(r.json()) if r.status_code == 200 else []
check(r.status_code == 200 and len(acme_prop_list) > 0, "Acme sees own properties", f"{r.status_code}")
if acme_prop_list:
    pid = acme_prop_list[0]["id"]
    r2 = requests.get(f"{BASE}/properties/{pid}", headers=H(sunrise_t))
    check(r2.status_code in (403, 404), "Sunrise cannot read Acme's property", f"got {r2.status_code}")

print("\n=== B2: team-member viewer is read-only ===")
# Viewer tries to create a property -> should be 403.
r = requests.post(f"{BASE}/properties/", headers=H(viewer_t),
                  json={"name": "Hack Court", "city": "Nairobi", "number_of_units": 1})
check(r.status_code == 403, "viewer blocked from creating property", f"got {r.status_code}")

print("\n=== C1/C2: tenant OTP login end-to-end ===")
ident = "+254711000001"
r = requests.post(f"{BASE}/otp/request", json={"identifier": ident})
check(r.status_code == 200, "OTP request accepted", f"{r.status_code}")
code = latest_otp_code(ident)
check(code is not None, "OTP code retrievable (simulation log)", "no code found")
if code:
    r = requests.post(f"{BASE}/otp/verify", json={"identifier": ident, "code": code})
    check(r.status_code == 200 and r.json().get("access_token"), "OTP verify issues token", f"{r.status_code} {r.text[:120]}")
    tenant_t = r.json().get("access_token") if r.status_code == 200 else None
    # Wrong code rejected
    r = requests.post(f"{BASE}/otp/verify", json={"identifier": ident, "code": "000000"})
    check(r.status_code in (400, 401, 429), "wrong OTP rejected", f"{r.status_code}")

    print("\n=== C3/C7: tenant sees only own data ===")
    if tenant_t:
        r = requests.get(f"{BASE}/portal/dashboard", headers=H(tenant_t))
        check(r.status_code == 200, "tenant dashboard loads", f"{r.status_code}")
        r = requests.get(f"{BASE}/portal/statement", headers=H(tenant_t))
        check(r.status_code == 200, "tenant statement loads", f"{r.status_code}")
        # A tenant token must NOT access admin endpoints
        r = requests.get(f"{BASE}/admin/dashboard", headers=H(tenant_t))
        check(r.status_code in (401, 403), "tenant blocked from admin", f"{r.status_code}")

print("\n=== D1/D2: admin dashboard + landlord drill-down ===")
r = requests.get(f"{BASE}/admin/dashboard", headers=H(admin_t))
check(r.status_code == 200, "admin dashboard loads", f"{r.status_code}")
r = requests.get(f"{BASE}/admin/landlords", headers=H(admin_t))
check(r.status_code == 200, "admin landlords list loads", f"{r.status_code}")
# A landlord token must NOT access admin endpoints
r = requests.get(f"{BASE}/admin/dashboard", headers=H(land_t))
check(r.status_code in (401, 403), "landlord blocked from admin", f"{r.status_code}")

print("\n=== D3: Client Support (renamed impersonation) request flow ===")
# admin lists client-support requests (endpoint path unchanged: /admin/impersonation)
r = requests.get(f"{BASE}/admin/impersonation/requests", headers=H(admin_t))
check(r.status_code == 200, "client-support requests list loads", f"{r.status_code}")
# request access to Acme landlord (need landlord_id). Pull from admin landlords list.
lls = requests.get(f"{BASE}/admin/landlords", headers=H(admin_t)).json()
ll_items = unwrap(lls)
acme = next((l for l in ll_items if "Acme" in (l.get("company_name") or "")), None)
if acme:
    r = requests.post(f"{BASE}/admin/impersonation/request", headers=H(admin_t),
                      json={"landlord_id": acme["id"], "reason": "Diagnostic test — verify support flow"})
    check(r.status_code in (200, 201), "client-support request created",
          f"{r.status_code} {r.text[:160]}")
    # Verify the response message no longer contains 'Impersonation'
    if r.status_code in (200, 201):
        body = r.text
        check("Impersonation" not in body, "response text uses 'Support' not 'Impersonation'", body[:120])

print("\n=== D10: master audit log filter ===")
r = requests.get(f"{BASE}/admin/audit?impersonated=true", headers=H(admin_t))
check(r.status_code == 200, "audit 'client support only' filter works", f"{r.status_code}")

print("\n=== E1/E7: affiliate portal ===")
aff_t, _ = login("affiliate.wanjiru@sahilpay.test", "Affiliate@123")
check(aff_t is not None, "affiliate login")
if aff_t:
    r = requests.get(f"{BASE}/affiliate/dashboard", headers=H(aff_t))
    check(r.status_code in (200, 404), "affiliate dashboard endpoint responds", f"{r.status_code}")
    # affiliate token blocked from admin
    r = requests.get(f"{BASE}/admin/affiliates", headers=H(aff_t))
    check(r.status_code in (401, 403), "affiliate blocked from admin affiliate mgmt", f"{r.status_code}")

print(f"\n=== HTTP CHECKS COMPLETE: {N} checks, {len(FAILS)} failures ===")
for f in FAILS:
    print(f"   FAILED: {f}")
sys.exit(1 if FAILS else 0)
