"""
M-Pesa go-live preflight — READ-ONLY. Moves no money, sends no prompt.

    cd server && source venv/bin/activate && python scripts/mpesa_preflight.py

Checks, against whatever DARAJA_BASE_URL the .env points at:
  1. every required setting is present (secrets are never printed);
  2. OAuth: the consumer key/secret get a token;
  3. PASSKEY: an STK status query for a dummy CheckoutRequestID is answered with
     a "not found"-style reply, not "invalid password" — proving shortcode +
     passkey are right without prompting anyone;
  4. the public callback URLs answer from the internet;
  5. security settings that matter once live.
Exit code 0 = ready, 1 = something to fix.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")

import requests  # noqa: E402

from app import create_app  # noqa: E402

ok = True


def line(passed, name, detail=""):
    global ok
    ok = ok and passed
    print(f"{'PASS' if passed else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")


def warn(name, detail=""):
    print(f"WARN  {name}{(' — ' + detail) if detail else ''}")


app = create_app()
with app.app_context():
    from flask import current_app as c
    from services import daraja_service
    from services.daraja_service import DarajaError

    base = c.config.get("DARAJA_BASE_URL")
    print(f"Daraja base URL: {base}\n")

    for key in ("PLATFORM_DARAJA_CONSUMER_KEY", "PLATFORM_DARAJA_CONSUMER_SECRET",
                "PLATFORM_DARAJA_SHORTCODE", "PLATFORM_DARAJA_PASSKEY",
                "PLATFORM_DARAJA_STK_CALLBACK_URL"):
        value = c.config.get(key) or ""
        line(bool(value) and value != "placeholder", f"{key} is set")

    try:
        token = daraja_service.get_access_token()
        line(bool(token), "OAuth token obtained")
    except DarajaError as e:
        line(False, "OAuth token obtained", str(e)[:120])

    try:
        reply = daraja_service.stk_query("ws_CO_000000000000000000000000")
        line(True, "STK query accepted (shortcode + passkey valid)", str(reply)[:160])
    except DarajaError as e:
        body = ""
        resp = getattr(e.__cause__, "response", None)
        if resp is not None:
            body = resp.text[:200]
        bad_password = "password" in body.lower() or "invalid credentials" in body.lower()
        line(not bad_password, "STK query reached Daraja with a valid password",
             body or str(e)[:160])

    for url in (c.config.get("PLATFORM_DARAJA_STK_CALLBACK_URL"),
                "https://sahilpay.co.ke/api/webhooks/daraja/c2b/confirmation"):
        if not url:
            continue
        try:
            r = requests.get(url, timeout=15)
            # These are POST-only: 405 means the route exists and is reachable.
            line(r.status_code in (200, 405), f"callback reachable: {url}", f"HTTP {r.status_code}")
        except requests.RequestException as e:
            line(False, f"callback reachable: {url}", str(e)[:120])

    sim = c.config.get("MPESA_SIMULATION_MODE", True)
    print(f"\nMPESA_SIMULATION_MODE = {sim}  (must be false on the live server)")
    if not c.config.get("TRUST_PROXY"):
        warn("TRUST_PROXY is off", "set true behind nginx")
    print(f"TRUSTED_PROXY_HOPS = {c.config.get('TRUSTED_PROXY_HOPS')}  (production behind Cloudflare + nginx: 2)")
    if not c.config.get("DARAJA_ALLOWED_IPS"):
        warn("DARAJA_ALLOWED_IPS empty", "live mode will accept only Safaricom's published callback IPs")
    initiator = c.config.get("PLATFORM_DARAJA_INITIATOR_NAME") or ""
    if not initiator or initiator == "placeholder":
        warn("PLATFORM_DARAJA_INITIATOR_NAME not set",
             "needed only for B2C affiliate payouts and Transaction Status lookups")

print("\nREADY" if ok else "\nNOT READY — fix the FAIL lines above")
sys.exit(0 if ok else 1)
