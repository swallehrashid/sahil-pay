# M-Pesa go-live — platform paybill 4326127

What is ready, what only the account owner can do, and how to switch on.

## 1. Already verified (16 Sep 2026, from `scripts/mpesa_preflight.py`)

| Check | Result |
|---|---|
| Production consumer key/secret → OAuth token | PASS |
| Shortcode + passkey (STK status query accepted) | PASS |
| `https://sahilpay.co.ke/api/webhooks/daraja/billing-callback` reachable | PASS (405 to GET) |
| `https://sahilpay.co.ke/api/webhooks/daraja/c2b/confirmation` reachable | PASS (405 to GET) |
| C2B confirmation/validation URLs registered with Safaricom | Done 15 Jul 2026 |

## 2. How a payment becomes "paid"

Nothing is marked paid because someone pressed a button. Only one of these confirms money:

1. **STK callback** from Safaricom (ResultCode 0), **cross-checked** with our own authenticated
   STK status query before anything is applied. Disagreement → admins notified, nothing applied.
2. **C2B confirmation** — money paid to the paybill with account `SUB-<id>` or `SMS-<id>`.
   Any amount is accepted as an installment.
3. **Reconciliation sweep** (every 5 minutes) — STK status query for prompts whose callback never came.
4. **Admin verify** — after checking the paybill statement, for a landlord's "I paid, here is my code" claim.

A landlord entering an M-Pesa code that Safaricom never reported gets a **pending** record for review;
their balance does not change.

## 3. Security now in place

- Callback IP allowlist resolves the **real** caller behind Cloudflare + nginx (`TRUSTED_PROXY_HOPS=2`).
  It used to read the first `X-Forwarded-For` entry, which anyone can forge.
- With simulation off and no `DARAJA_ALLOWED_IPS`, only Safaricom's published callback IPs are accepted.
- Every callback is logged raw (`daraja_callback_logs`) whether accepted or not.
- STK success is double-checked with Safaricom before money is applied.
- The simulation "confirm" endpoint refuses to run when simulation is off or in production.

## 4. What only you can do — M-Pesa Org portal (org.ke.m-pesa.com)

**Do not share your operator PIN with anyone, including developers or AI assistants.** The web
operator login (`SR` + PIN) controls the whole paybill. The API never uses it.

These steps are optional for accepting payments. They are needed only for **B2C affiliate payouts**
and for looking up a single transaction by code (Transaction Status):

1. Log in as the business administrator → **Operators** → **Add operator**.
2. Create an operator named e.g. `SAHILAPI` with **Operator type: API**.
3. Assign roles: **Transaction Status Query ORG API**, **Account Balance ORG API**, and (for affiliate
   payouts) **ORG B2C API initiator**.
4. Set its password (the SMS/portal flow asks for it). Keep it private.
5. On the server, turn that password into the encrypted `SecurityCredential` **yourself**:
   ```bash
   # Download Safaricom's production certificate from the Daraja portal (Docs → Security Credentials)
   openssl x509 -inform der -in ProductionCertificate.cer -out prod.pem 2>/dev/null || cp ProductionCertificate.cer prod.pem
   printf '%s' 'THE_OPERATOR_PASSWORD' | openssl pkeyutl -encrypt -pubin -inkey <(openssl x509 -in prod.pem -pubkey -noout) -pkeyopt rsa_padding_mode:pkcs1 | base64 -w0
   ```
   Put the output in `PLATFORM_DARAJA_SECURITY_CREDENTIAL` and the operator name in
   `PLATFORM_DARAJA_INITIATOR_NAME` in `server/.env`. The Daraja portal's "Security credential"
   generator does the same thing if you prefer.
6. On the Daraja portal, make sure the production app has **M-Pesa Express** (STK) and **C2B** products enabled.

## 5. Switch on

1. `server/.env`: `MPESA_SIMULATION_MODE=false`, `DARAJA_BASE_URL=https://api.safaricom.co.ke`,
   `TRUST_PROXY=true`, `TRUSTED_PROXY_HOPS=2`.
2. Deploy ([REDEPLOY.md](REDEPLOY.md)), restart `sahilpay`, `sahilpay-celery`, `sahilpay-celerybeat`.
3. Run `cd server && venv/bin/python scripts/mpesa_preflight.py` on the server → `READY`.
4. First real test: Settings → Billing → Pay subscription → **KES 5** to your own number. Enter your PIN.
   Expect: "Waiting for M-Pesa" → "Payment confirmed" within ~10 s, receipt downloads, balance drops by 5.
5. Paybill test: Lipa na M-Pesa → Pay Bill 4326127 → account `SUB-<your landlord id>` → KES 5.
   It appears in Billing as confirmed within a minute.
6. Watch `journalctl -u sahilpay -f | grep -i "billing_callback\|c2b_confirmation\|rejected IP"` during
   the first payments. A "rejected IP" line means Safaricom called from an address not on the list —
   add it to `DARAJA_ALLOWED_IPS` (comma-separated) and restart.
