# FluxSMS (PesaFlux) Integration Spec

**Status:** Approved for implementation — final piece before deployment.
**Executor:** Claude Sonnet. Work on branch `backend-set-up`.
**Verified 2026-07-16:** The platform FluxSMS API key is live — `POST https://api.fluxsms.co.ke/check_sms_balance` returned `{"success":true,"sms_balance":124}`. The operator has also confirmed a real send under sender ID `SAHILPAY` works.

---

## 1. Goal

Replace the Africa's Talking SMS plumbing with **FluxSMS** as the real delivery provider, and finish the reselling model so it is production-ready:

1. **Default path:** every landlord sends via Sahil Pay's platform FluxSMS account under sender ID **`SAHILPAY`**, billed at the admin-set default price (currently 1 KES/SMS, admin-changeable — already works via `SmsPricingConfig`).
2. **Custom path:** a landlord can be connected to **their own FluxSMS sender ID + API key** (self-service in Settings, and admin can do it for them). Delivery then goes out of *their* FluxSMS account, but Sahil Pay still charges them the admin-set custom per-SMS service fee.
3. **Hard balance gate:** no SMS is ever attempted when the landlord's `sms_balance` (credits, funded via the already-connected paybill) can't cover it.
4. **De-brand:** remove every user-facing mention of "Africa's Talking" — say "sender ID" / "SMS provider" instead.
5. Verify end-to-end with real sends before declaring done.

**Naming ban reminder (M-Pesa spec carries over):** never put "mpesa" in any URL path. Not directly relevant here, but do not introduce it while editing routes.

---

## 2. FluxSMS API reference (what the code must call)

Base URL: `https://api.fluxsms.co.ke` — all requests `POST` with `Content-Type: application/json`. Rate limit: **100 requests/minute per API key**.

| Endpoint | Body | Success response |
|---|---|---|
| `/sendsms` | `{api_key, message, phone, sender_id}` | `{"response-code":200,"response-description":"Success","mobile":254...,"messageid":"...","networkid":1}` |
| `/bulksms` | `{api_key, message, phones:[...], sender_id}` | `{"responses":[{...,"messageid":"..."}],"success":true,"sent":N}` |
| `/smsstatus` | `{api_key, message_id}` | `{"response-code":200,"delivery-status":32,"delivery-description":"DeliveredToTerminal",...}` |
| `/check_sms_balance` | `{api_key}` | `{"success":true,"sms_balance":53721}` |

Errors come back as `{"error": "..."}` (e.g. `Invalid API key`, `Insufficient SMS balance`, `Invalid phone number format`, `Invalid or unregistered sender_id '...'`) or `{"response-code": 1009, ...}` for status queries. HTTP codes: 200/400/401/403/429/500.

**Success detection for a single send:** HTTP 200 **and** `response-code == 200` in the JSON. Anything else is a failure (capture the `error` string in logs).

**Phone format:** `07XXXXXXXX` / `01XXXXXXXX` local, or `254XXXXXXXXX` (converted server-side by FluxSMS). Strip all non-digits and a leading `+` before sending. Message: 160 GSM-7 chars per segment (matches existing `sms_billing.count_segments`), max 1000 chars.

**Platform credentials (production values — go in `.env`, NEVER in client code, never hard-code in committed source):**

```
FLUXSMS_API_KEY=undlnxreuqzpzujikijqeoledxlvteeeyratiqyl
FLUXSMS_SENDER_ID=SAHILPAY
```

---

## 3. Current state (analysis findings)

What already exists and works — do not rebuild:

- **Billing model** — `server/services/sms_billing.py`: segment counting, default/custom pricing, platform-cost margin, all read live from the admin-editable `SmsPricingConfig` singleton (`models.py:3194`). Admin can already change prices at `PUT /api/admin/sms/pricing` (`routes/admin_sms_routes.py`), with pool top-ups + history + analytics, and the admin UI (`client/src/features/admin/SmsManagement.jsx`) is done.
- **Single dispatch chokepoint** — `services/communication_service.py::dispatch_message()` prices, decrements `landlord.sms_balance`, decrements the shared pool, and writes a `CommunicationLog` row for every tenant message. Simulation mode (`COMMS_SIMULATION_MODE`) and demo-landlord force-simulation both work.
- **Credit purchase via paybill** — `routes/billing_routes.py`: `POST /buy-sms/stk` (Daraja STK to the platform paybill, verified by webhook) + legacy self-reported flow with admin verification. C2B URLs are already registered on prod.
- **Landlord custom-sender plumbing** — `LandlordSettings.at_api_key / at_username / at_sender_id / at_connected` (`models.py:2949-2952`), self-service endpoints in `routes/settings_routes.py` (`/api/settings/sms-provider` + `/connect` + `/disconnect`), and the settings page `client/src/features/landlord/settings/SmsProviderSettings.jsx`.
- **Low-balance alerting** — `utils.decrement_sms_balance()` warns at the landlord's threshold; a beat task `low_sms_balance_alerts` exists.

Gaps this spec closes:

| # | Gap | Where |
|---|---|---|
| G1 | `send_sms()` posts to Africa's Talking, not FluxSMS | `services/sms_service.py` |
| G2 | `dispatch_message()` **charges even when the landlord has 0 credits** — only the *shared pool* blocks a send; landlord balance is clamped to 0 but the SMS still goes out. Custom-sender sends are never balance-gated at all | `services/communication_service.py` |
| G3 | Charge/decrement happens **before** the send attempt; a failed send still burns credits | same |
| G4 | Three send paths bypass billing/logging entirely: payment-ack SMS (`routes/payment_routes.py:725`), document-share SMS (`routes/document_routes.py:321`) | those routes |
| G5 | Custom provider config requires an AT `username` — FluxSMS has no username concept | model, settings routes, settings UI |
| G6 | "Africa's Talking" appears in user-facing UI text (7 client files) and doc-strings | client + server comments |
| G7 | No validation that a saved API key / sender ID actually works before "Connect" | settings routes |
| G8 | Provider `messageid` is discarded, so delivery status can never be reconciled | `CommunicationLog` |
| G9 | Env/config still `AT_*` | `config.py:187-189`, `deploy/server.env.production.example:47-49` |

---

## 4. Design decisions (already made — implement as stated)

- **Rename to provider-neutral names.** We are pre-deployment; do it properly. `LandlordSettings`: `at_api_key → sms_api_key`, `at_sender_id → sms_sender_id`, `at_connected → sms_connected`; **drop `at_username`**. Config: `AT_API_KEY/AT_SENDER_ID → FLUXSMS_API_KEY/FLUXSMS_SENDER_ID`; drop `AT_USERNAME`. One Alembic migration (column renames + drop + the new `communication_logs.provider_message_id` from G8). Grep for every `at_api_key|at_username|at_sender_id|at_connected|AT_API_KEY|AT_USERNAME|AT_SENDER_ID` reference and update all of them (`models.py`, `settings_routes.py`, `billing_routes.py`, `admin_billing_routes.py`, `sms_billing.py`, `sms_service.py`, `communication_service.py`, seed, tests, client apiSlice/components).
- **Sender ID casing:** the registered platform sender is exactly `SAHILPAY`. `sms_billing.DEFAULT_PLATFORM_SENDER` becomes `"SAHILPAY"`; the real value always comes from `FLUXSMS_SENDER_ID`.
- **Billing stays credit-based and admin-controlled.** Both default and custom landlords consume `sms_balance` credits per segment (custom users buy credits at the cheaper custom unit price — `_sms_unit_price()` already handles this). No pricing logic changes.
- **Personalized sends stay per-recipient** (`/sendsms`), because content differs per tenant. Do **not** switch to `/bulksms` for tenant messaging. Respect the rate limit (see item E).
- **Platform-paid sends** (not billed to a landlord, sent from `SAHILPAY` with the platform key): tenant OTP login (`send_otp_sms`), landlord alert SMS (`services/alert_service.py`). Leave these as direct `send_sms()` calls.

---

## 5. Work items

### A. Config + env (G9)

`server/config.py`: replace the AT block with

```python
# FluxSMS — SMS delivery (Kenya)
FLUXSMS_BASE_URL: str = _env("FLUXSMS_BASE_URL", "https://api.fluxsms.co.ke")
FLUXSMS_API_KEY: str | None = _env("FLUXSMS_API_KEY")
FLUXSMS_SENDER_ID: str = _env("FLUXSMS_SENDER_ID", "SAHILPAY")
```

Update `deploy/server.env.production.example` (drop `AT_*`, add the three above) and the local `server/.env` if present. Production `.env` gets the real key from §2.

### B. Rewrite `services/sms_service.py` (G1)

Keep the same public shape so callsites barely change:

- `send_sms(recipient, content, sender_id=None, api_key=None) -> str | None` — resolves `api_key`/`sender_id` from config when not passed (platform path); custom path passes the landlord's own. Normalizes the phone (strip non-digits/`+`; accept `07…`, `01…`, `2547…`, `2541…`). POSTs JSON to `{FLUXSMS_BASE_URL}/sendsms` (stdlib `urllib` as today, or `requests` since it's already a dependency; 15s timeout). Returns the provider `messageid` string on success, `None` on any failure (never raises). Logs the `error` field on failure. When `FLUXSMS_API_KEY` is missing, keep the current stub-log behaviour.
- The `username` parameter is deleted everywhere.
- Add `check_sms_balance(api_key=None) -> int | None` — calls `/check_sms_balance`; used by settings-connect validation (G7) and the admin pool sync (item F).
- Add `get_delivery_status(message_id, api_key=None) -> dict | None` — thin `/smsstatus` wrapper (used by the optional P2 reconciliation; harmless to have now).
- `send_otp_sms` task unchanged apart from the plumbing.
- Update the module docstring (no Africa's Talking).

### C. Migration + model (G5, G8)

One Alembic revision:

1. Rename `landlord_settings.at_api_key → sms_api_key`, `at_sender_id → sms_sender_id`, `at_connected → sms_connected`.
2. Drop `landlord_settings.at_username`.
3. Add `communication_logs.provider_message_id VARCHAR(40) NULL`.

Update `models.py` (`LandlordSettings.to_dict()` keys become `sms_api_key_set`, `sms_api_key_masked`, `sms_sender_id`, `sms_connected`; `CommunicationLog.to_dict()` gains `provider_message_id`) and `sms_billing.resolve_sender()` / `billing_routes._sms_unit_price()` to the new field names.

### D. `dispatch_message()` — balance gate, charge-on-success, real sends (G2, G3, G8)

In `services/communication_service.py`:

1. **Gate first.** For `channel == "sms"` (custom *and* default senders, skipping demo landlords): if `landlord.sms_balance < sms_segments` → `blocked = "Insufficient SMS balance — top up to keep sending."` The existing shared-pool + master-toggle checks stay for default senders only, as now.
2. **Charge only what was actually sent.** Move the `decrement_sms_balance()` / `cfg.pool_balance` decrement / `sms_charge`/`platform_cost` assignment to **after** the send outcome is known, and apply them only when `status == "delivered"` (simulated deliveries count, preserving today's demo/simulation behaviour). A failed provider call must not burn credits or record platform cost.
3. Custom path passes `api_key=settings.sms_api_key` (username gone).
4. `send_sms()` now returns the provider message id — store it on the log row (`provider_message_id`), for real (non-simulated) sends.
5. Update the resend path in `routes/communication_routes.py` — nothing structural, it re-enters `dispatch_message()`; just confirm the pre-send balance check in `send_message()` (`communication_routes.py:149-156`) still matches (it uses 1 credit/recipient; leave it as a cheap pre-check — the real gate is now inside `dispatch_message`).

### E. Route stray sends through the chokepoint + rate limiting (G4)

1. `routes/payment_routes.py:725` (payment-acknowledgment SMS) and `routes/document_routes.py:321` (document-share SMS): replace direct `send_sms()` with `dispatch_message(...)` so they are billed, balance-gated, and logged like everything else. For `document_routes`, drop the manual `CommunicationLog` construction that follows if it would now duplicate the one `dispatch_message` writes (check the surrounding code; keep exactly one log row per message).
2. **Rate limit:** FluxSMS allows 100 req/min. The Celery bulk path (`tasks/communication_tasks.py`) should sleep ~0.75s between sends (≈80/min) when not in simulation mode. The synchronous loop in `communication_routes.send_message()` is fine for typical batch sizes but add the same throttle there if it's the path that iterates recipients (verify which one actually loops in production config — route both through the same throttled helper if easy).

### F. Settings + admin endpoints (G5, G7 + admin-connect requirement)

`routes/settings_routes.py`:

1. `/api/settings/sms-provider` GET/PUT: new field names; PUT accepts `{sms_api_key?, sms_sender_id?}` only.
2. `/sms-provider/connect`: require `sms_api_key` + `sms_sender_id` saved, then **validate the key live** by calling `check_sms_balance(api_key)` — reject with a clear 400 ("The API key was rejected by the SMS provider.") when it fails. On success set `sms_connected = True`. Audit strings say "Custom SMS sender connected — sender ID 'X'", no provider brand.
3. `/disconnect`: unchanged behaviour, reworded.

**Admin does it for them:** add to `routes/admin_sms_routes.py`:

- `GET /api/admin/sms/landlords/<id>/provider` — the landlord's current provider config (masked key).
- `PUT /api/admin/sms/landlords/<id>/provider` — body `{sms_api_key?, sms_sender_id?, connected?}`; same live key validation when `connected: true` is being set; audited with the admin's user id.
- `POST /api/admin/sms/pool/sync` — calls `check_sms_balance()` with the platform key and sets `SmsPricingConfig.pool_balance` to the provider's real balance (recorded in the `SmsPoolTopUp` ledger with a note `"Synced from provider"` and delta). This keeps the admin pool counter honest against the actual FluxSMS balance (currently 124).

### G. Client changes (G5, G6)

1. **`client/src/features/landlord/settings/SmsProviderSettings.jsx` + `smsProviderApiSlice.js`:** drop the Username input; field names `sms_api_key`/`sms_sender_id`; all copy becomes provider-neutral — e.g. header "Custom sender ID", body "Connect your own registered SMS sender ID and API key to send under your brand." Replace the **hardcoded "1 KES / SMS"** strings (lines 78, 85, 134) with the live `price_per_sms` + `currency` the GET endpoint already returns.
2. **Public pages:** `features/public/Pricing.jsx:169`, `Features.jsx:106`, `content/seoContent.js:80` — replace "Africa's Talking sender ID" with "your own sender ID".
3. **Tutorial:** `features/landlord/tutorials/content/communications.js:26` — reword: register a sender ID with any SMS provider / ask Sahil Pay support to connect one for you; no brand name.
4. **Admin:** `features/admin/SmsManagement.jsx:266` — placeholder "e.g. provider top-up, ref #123". Add the per-landlord provider connect UI (drill-down or a small modal in SMS management, wherever landlord rows already exist) wired to the new admin endpoints, plus a "Sync pool from provider" button beside the top-up form.
5. Sweep `grep -ri "africa" client/ server/` afterwards — comments/doc-strings included — and neutralize the stragglers.

### H. Seed + tests

- `seed.py`: update any `at_*` field usage.
- Fix existing tests referencing renamed fields; add unit tests: phone normalization, `send_sms` success/error parsing (mock HTTP), balance gate blocks at 0 credits, failed send doesn't decrement, custom path uses landlord key/sender, connect endpoint rejects a bad key (mock).

### P2 (optional, only if time allows — do not block deployment)

Celery beat task that polls `/smsstatus` for recent `communication_logs` rows with a `provider_message_id` and updates `status` from the real DLR (`DeliveredToTerminal` → delivered).

---

## 6. Verification plan (must actually run, in order)

1. `pytest` suite green; migration up/down clean on a copy of the dev DB.
2. **Live provider checks (real key, no SMS cost):**
   `curl -X POST https://api.fluxsms.co.ke/check_sms_balance -H "Content-Type: application/json" -d '{"api_key":"<key>"}'` → `success:true` (already confirmed 2026-07-16, balance 124).
3. **Real send test** — with `COMMS_SIMULATION_MODE=false` locally: send one tenant SMS through the communications page to a **real phone number the operator provides** (do NOT use the numbers from the provider docs). Confirm: message arrives from `SAHILPAY`, `communication_logs` row has `status=delivered` + `provider_message_id`, `sms_balance` dropped by segment count, pool dropped, `sms_charge`/`platform_cost` recorded.
4. **Balance gate:** set a test landlord's `sms_balance` to 0 → send blocked with the insufficient-balance error, nothing dispatched, nothing charged.
5. **Custom sender path:** connect a test landlord with the same FluxSMS key + `SAHILPAY` sender via the settings page (valid stand-in for a landlord's own account) → send succeeds, billed at the custom rate, pool untouched. Then disconnect → reverts to default path. Also connect via the new **admin** endpoint once.
6. **Bad key rejection:** attempt connect with a garbage key → 400 from live validation.
7. **Admin price change:** change default price in admin SMS management → landlord settings page and billing page show the new price with no code change.
8. **Pool sync:** admin "Sync from provider" sets `pool_balance` to the live FluxSMS balance and writes a ledger row.
9. **OTP:** tenant OTP login sends via platform key (real send once, then simulation back on).
10. Re-enable `COMMS_SIMULATION_MODE=true` for local dev when done; production `.env` gets `COMMS_SIMULATION_MODE=false` + the FluxSMS vars at deploy time.
11. Final sweep: `grep -ri "africa" client/src server/ --include="*.py" --include="*.js" --include="*.jsx"` returns nothing user-facing.

## 7. Acceptance checklist

- [ ] All sends (manual, bulk, automation reminders, invoice notify, payment ack, document share, resend) go through `dispatch_message` — billed, gated, logged.
- [ ] No SMS attempted when credits < segments; failed sends never burn credits.
- [ ] Default sender `SAHILPAY` from platform key; custom sender per landlord (self-service **and** admin-set), still billed per admin-set rate.
- [ ] Prices shown in UI are live from `SmsPricingConfig`, nowhere hardcoded.
- [ ] Zero "Africa's Talking" strings anywhere user-visible; `at_*`/`AT_*` identifiers gone.
- [ ] Real SMS delivery verified end-to-end per §6.
