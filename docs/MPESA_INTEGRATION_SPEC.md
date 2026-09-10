# M-PESA PRODUCTION INTEGRATION SPEC — SahilPay

**Status:** Approved for implementation. Execute every section, then run the full
verification plan in §13. Written 2026-07-15.

**Audience:** This document is the single source of truth for wiring SahilPay's
platform M-Pesa flows to the production Daraja app, hardening them, and verifying
every portal end-to-end. Read the whole document before writing code.

**Prerequisite reading in this repo:** `AFFILIATE_PROGRAM_SPEC.md` (verified-payment
pipeline §3, withdrawals §5), `server/routes/webhook_routes.py`,
`server/routes/billing_routes.py`, `server/services/billing_service.py`,
`server/services/affiliate_service.py`, `server/routes/mpesa_routes.py`.

---

## 0. What is ALREADY DONE (do not redo)

1. **Production credentials verified.** The Daraja app *Prod-SAHIL RENT PAY-1784126177641*
   (paybill **4326127**) OAuth token generation was tested successfully against
   `https://api.safaricom.co.ke` on 2026-07-15.
2. **C2B URLs are REGISTERED on production** (via `/mpesa/c2b/v2/registerurl`,
   ResponseCode `00000000`):
   - ValidationURL: `https://sahilpay.co.ke/api/webhooks/daraja/c2b/validation`
   - ConfirmationURL: `https://sahilpay.co.ke/api/webhooks/daraja/c2b/confirmation`
   - ResponseType: `Completed` (payment completes if the validation URL is unreachable)

   ⚠️ These exact paths are now fixed on Safaricom's side. Changing them requires a
   Safaricom support ticket. **The backend routes you build in §4 MUST live at these
   exact paths.**
3. **Daraja URL keyword rule discovered the hard way:** Safaricom **rejects any
   callback URL containing the word "mpesa"** (also "safaricom", "exe", "exec").
   The v1 register endpoint returned `401.003.01 Invalid Access Token` (misleading —
   use **v2**); v2 returned the real error. Consequence: every URL we ever send to
   Daraja (C2B register, STK `CallBackURL`, B2C `ResultURL`/`QueueTimeOutURL`) must
   use the `/api/webhooks/daraja/...` prefix, **never** `/api/webhooks/mpesa/...`.
4. **Credentials are in `server/.env`** (git-ignored) under `PLATFORM_DARAJA_*`.
   Two values are **PENDING** and block specific features (see §14 go-live):
   - `PLATFORM_DARAJA_PASSKEY` — blocks real STK Push (portal shows "undefined";
     Safaricom issues it on M-Pesa Express go-live).
   - `PLATFORM_DARAJA_INITIATOR_NAME` / `PLATFORM_DARAJA_SECURITY_CREDENTIAL` —
     blocks real B2C payouts.

   Until those arrive, everything must work in `MPESA_SIMULATION_MODE=true` — that
   is also how you will verify the flows locally.

## 0.1 Decisions locked with the owner (do not re-litigate)

| # | Decision |
|---|----------|
| D1 | Paybill **4326127 carries platform revenue ONLY** (subscription payments, SMS credit purchases) **+ outbound B2C affiliate payouts**. Tenant rent NEVER flows through it. Rent stays on each landlord's own paybill/till via Co-Pilot SMS forwarding, tenant self-reporting, and manual matching. Rent STK Push (`POST /api/mpesa/stk-push`) must be **feature-gated OFF in production** (see §6.4) until a per-landlord-credentials phase happens. |
| D2 | Affiliate payouts: **B2C automation with manual fallback.** Admin approval remains the trigger — no payout ever fires without an explicit admin action. |
| D3 | **Verified-only payments in production.** The legacy self-reported endpoints (`POST /api/billing/pay-subscription`, `POST /api/billing/buy-sms`) must stop granting service instantly; they create PENDING transactions an admin must verify. Frontend switches to the STK flow. |
| D4 | Deployment shape: **one domain**, `sahilpay.co.ke`, nginx serves the React build and proxies `/api` → Flask. The registered URLs assume this. |

---

## 1. Money-flow map (target state)

| Flow | Direction | Rail | Entry points | Verification |
|------|-----------|------|--------------|--------------|
| Landlord subscription | Landlord → Sahil (4326127) | STK Push **or** direct paybill (account `SUB-{landlord_id}`) | `POST /api/billing/pay-subscription/stk`; C2B confirmation webhook | `finalize_subscription_payment()` — only path to `is_verified=True`, subscription activation, and affiliate accrual |
| SMS credit purchase | Landlord → Sahil (4326127) | STK Push **or** direct paybill (account `SMS-{landlord_id}`) | new `POST /api/billing/buy-sms/stk`; C2B confirmation webhook | new `finalize_sms_purchase()` — credits `sms_balance` only on verified payment |
| Affiliate payout | Sahil (4326127) → affiliate's phone | B2C `BusinessPayment` | admin `POST /api/admin/affiliates/withdrawals/<id>/pay-b2c` | B2C ResultURL webhook marks `paid` with the real `TransactionReceipt` |
| Tenant rent | Tenant → **landlord's own** paybill/till | Outside platform rails | Co-Pilot ingest, tenant self-report + proof, manual match | Landlord confirms; unchanged by this spec |

The affiliate chain the owner cares about, end to end: landlord pays subscription
(STK or paybill) → Daraja callback verifies → `finalize_subscription_payment` →
`accrue_for_transaction` pays the referral's affiliate at the **admin-set
per-affiliate `commission_rate_override`, else `AffiliateProgramConfig.default_commission_rate`
(40% × 4 months)** — this logic already exists and must not be duplicated —
→ affiliate requests withdrawal → admin approves → **B2C sends net amount to the
affiliate's `mpesa_number`** → result webhook records the receipt → affiliate is
notified. Every step must be observable in the UI and covered in §13.

---

## 2. Configuration

### 2.1 Environment variables (server/.env — already present locally)

```
PLATFORM_DARAJA_CONSUMER_KEY / _CONSUMER_SECRET   # set (production values)
PLATFORM_DARAJA_SHORTCODE=4326127                 # set
PLATFORM_DARAJA_PASSKEY=                          # PENDING (go-live §14)
PLATFORM_DARAJA_STK_CALLBACK_URL=https://sahilpay.co.ke/api/webhooks/daraja/billing-callback
PLATFORM_DARAJA_INITIATOR_NAME=                   # PENDING (B2C)
PLATFORM_DARAJA_SECURITY_CREDENTIAL=              # PENDING (B2C)
PLATFORM_DARAJA_B2C_RESULT_URL=https://sahilpay.co.ke/api/webhooks/daraja/b2c/result
PLATFORM_DARAJA_B2C_TIMEOUT_URL=https://sahilpay.co.ke/api/webhooks/daraja/b2c/timeout
MPESA_SIMULATION_MODE=true                        # false in production only
DARAJA_BASE_URL=https://sandbox.safaricom.co.ke   # https://api.safaricom.co.ke in prod
```

Tasks:
- Add all of the above (placeholders only, no real values) to `server/.env.example`
  with the same comments.
- `config.py`: add the new `PLATFORM_DARAJA_INITIATOR_NAME`, `_SECURITY_CREDENTIAL`,
  `_B2C_RESULT_URL`, `_B2C_TIMEOUT_URL` settings next to the existing
  `PLATFORM_DARAJA_*` block. The pre-existing `MPESA_*` config block (lines ~215-220)
  is dead — routes read `DARAJA_*`/`PLATFORM_DARAJA_*` via `os.getenv`. Remove the
  dead `MPESA_*` settings **and** change `_validate()`'s
  `_require("MPESA_CONSUMER_KEY", ...)` to require `PLATFORM_DARAJA_CONSUMER_KEY`
  instead, plus `PLATFORM_DARAJA_PASSKEY` when `MPESA_SIMULATION_MODE` is false.

### 2.2 Secret hygiene (do these, they are cheap)

- Confirm `server/.env` remains git-ignored and that **no Daraja value is ever
  committed** — including in this spec, test fixtures, or migration comments.
- The consumer key/secret were pasted in a chat conversation; recommend the owner
  **regenerates the consumer secret on the Daraja portal after go-live testing**
  (§14 step 8) and updates `.env`. Nothing in code may hard-code them.
- Never log the passkey, security credential, or full Authorization headers.

---

## 3. New module: `server/services/daraja_service.py`

Daraja plumbing currently lives duplicated in `mpesa_routes.py` and
`billing_routes.py` (`_daraja_access_token`, `_daraja_stk_password`, phone
normalisation). Centralise it — one module, used by every caller:

```python
# services/daraja_service.py — the ONLY place that talks HTTP to Daraja.
get_access_token(scope="platform") -> str      # platform creds; raises DarajaError
stk_push(phone, amount, account_ref, description, callback_url) -> dict
stk_query(checkout_request_id) -> dict         # /mpesa/stkpushquery/v1/query
b2c_payment(phone, amount, remarks, occasion, originator_id) -> dict  # /mpesa/b2c/v3/paymentrequest
normalize_msisdn(raw) -> str | None            # returns 2547XXXXXXXX / 2541XXXXXXXX or None
```

Requirements:
- All URLs built from `DARAJA_BASE_URL`; timeouts ≤ 15 s; `raise_for_status()`;
  wrap errors in a `DarajaError` carrying the Daraja `errorCode`/`errorMessage`.
- `b2c_payment` uses **v3** (`/mpesa/b2c/v3/paymentrequest`) with
  `CommandID=BusinessPayment`, `OriginatorConversationID` = caller-supplied UUID
  (idempotency handle), `PartyA` = shortcode, `PartyB` = msisdn,
  `SecurityCredential` from env. **Amount must be a whole number of shillings** —
  B2C rejects decimals; see §8.3.
- Refactor `mpesa_routes.py` and `billing_routes.py` to call this module (delete the
  local helpers). Behaviour must be byte-identical for the STK payloads
  (assert in tests).
- Keep `MPESA_SIMULATION_MODE` checks **out** of this module — callers decide;
  this module only does real HTTP.

---

## 4. Webhook endpoints (in `routes/webhook_routes.py`)

All new routes: no JWT, always return HTTP 200 with `{"ResultCode": 0, "ResultDesc": "Accepted"}`
(Daraja retry-loops on non-200 — the existing `mpesa_billing_callback` shows the
pattern, including the catch-all `except` + rollback). All must be idempotent.

### 4.1 Raw payload log (new model)

Every webhook body is persisted **before** any processing:

```python
class DarajaCallbackLog(TimestampMixin, Base):
    __tablename__ = "daraja_callback_logs"
    id            = Column(Integer, primary_key=True)
    kind          = Column(String(20), nullable=False)   # 'stk' | 'c2b_validation' | 'c2b_confirmation' | 'b2c_result' | 'b2c_timeout'
    remote_ip     = Column(String(45), nullable=True)
    payload_json  = Column(JSON, nullable=False)
    processed     = Column(Boolean, default=False, nullable=False)
    error         = Column(Text, nullable=True)
```

This is the forensic trail for every shilling. Cap `payload_json` at 32 KB (truncate).

### 4.2 `POST /api/webhooks/daraja/billing-callback` (STK — platform payments)

The existing `/api/webhooks/mpesa/billing-callback` handler is correct — but its
path can never be given to Daraja (keyword rule, §0.3). Register the **same handler
function** on both paths (old path kept for any in-flight references), and extend it:

- After extracting `CheckoutRequestID`, look up the pending `BillingTransaction`
  **regardless of type** — it now also finalises `sms_purchase` transactions (§7):
  dispatch on `txn.type` to `finalize_subscription_payment(txn)` or the new
  `finalize_sms_purchase(txn)`.
- On success, verify `items["Amount"]` equals `txn.amount` to the shilling; if it
  differs, do **not** finalise — mark the `DarajaCallbackLog.error` and flag the
  transaction for admin review (notification to admins, category
  `billing_amount_mismatch`).

### 4.3 `POST /api/webhooks/daraja/c2b/validation`

Called by Safaricom **only if External Validation is enabled** on the paybill
(M-Pesa org portal setting; see §14). Behaviour:
- Log to `DarajaCallbackLog`.
- Parse `BillRefNumber`. If it matches `SUB-{id}` or `SMS-{id}` for an existing,
  non-deleted landlord → `{"ResultCode": 0, "ResultDesc": "Accepted"}`.
- Otherwise still **accept** (`ResultCode: 0`) — we never bounce money; unmatched
  payments go to the admin queue (§5). Rejecting (`C2B00012`) loses the payment and
  frustrates the payer. Do not leak any landlord data in the response.

### 4.4 `POST /api/webhooks/daraja/c2b/confirmation`

The workhorse for direct paybill payments. Payload fields: `TransID` (M-Pesa
receipt, globally unique), `TransAmount`, `BillRefNumber`, `MSISDN` (may arrive
hashed), `TransTime`, `FirstName`.

Processing order:
1. Log raw payload.
2. **Idempotency:** if a `PlatformC2BPayment` with this `TransID` exists → return 200, done.
3. Create a `PlatformC2BPayment` row (new model, §5.1) with everything parsed.
4. Route on `BillRefNumber` (case-insensitive, trimmed):
   - `SUB-{landlord_id}` → subscription payment path (§6.3).
   - `SMS-{landlord_id}` → SMS credit path (§7.3).
   - Anything else, unknown landlord id, or landlord deleted → status `unmatched`,
     notify all admins (category `platform_payment_unmatched`).
5. Amount handling is **server-side only** — never trust any client figure. For
   `SUB-`: find the landlord's pending unverified subscription `BillingTransaction`
   with `amount == TransAmount` (most recent first). If found → set
   `payment_reference = TransID`, run `finalize_subscription_payment`. If none
   matches → `unmatched` + admin notification (admin can resolve from the queue,
   §5.2). Do not guess: an underpayment must never activate a subscription.
6. Commit once, at the end; on any exception: rollback, stamp
   `DarajaCallbackLog.error`, still return 200.

### 4.5 `POST /api/webhooks/daraja/b2c/result` and `/b2c/timeout`

See §8.4.

---

## 5. Direct-paybill payments (C2B) — models and admin queue

### 5.1 New model `PlatformC2BPayment`

```python
class PlatformC2BPayment(TimestampMixin, Base):
    __tablename__ = "platform_c2b_payments"
    id             = Column(Integer, primary_key=True)
    trans_id       = Column(String(20), nullable=False, unique=True, index=True)  # M-Pesa receipt
    amount         = Column(Numeric(12, 2), nullable=False)
    bill_ref       = Column(String(30), nullable=True)
    msisdn         = Column(String(64), nullable=True)   # may be hashed by Safaricom
    payer_name     = Column(String(120), nullable=True)
    trans_time     = Column(String(20), nullable=True)   # raw Daraja YYYYMMDDHHMMSS
    landlord_id    = Column(Integer, ForeignKey("landlords.id"), nullable=True, index=True)
    billing_transaction_id = Column(Integer, ForeignKey("billing_transactions.id"), nullable=True)
    status         = Column(String(20), nullable=False, default="unmatched")  # matched | unmatched | resolved
    resolved_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolution_note      = Column(Text, nullable=True)
```

### 5.2 Admin endpoints + UI (extend the admin billing area)

- `GET /api/admin/billing/c2b-payments?status=` — paginated list.
- `POST /api/admin/billing/c2b-payments/<id>/resolve` — body
  `{ landlord_id, apply_as: 'subscription'|'sms'|'ignore', note }`. For
  `subscription`: create-or-match a `BillingTransaction` exactly as §4.4 step 5
  would have (compute cycle server-side from the landlord's pending txn or
  `preview_subscription_cost`), then `finalize_subscription_payment`. For `sms`:
  `finalize_sms_purchase` semantics with `sms_count = amount / unit_price` floor.
  Audit-record every resolution (`record_audit`, entity_type `billing`).
- Frontend: new **"Paybill payments"** tab in the admin billing screen listing
  these rows with an unmatched badge count in the admin sidebar, and a resolve
  modal. Follow the existing admin table/modal patterns
  (`client/src/features/admin/AffiliateWithdrawalsQueue.jsx` is the reference).

### 5.3 Landlord-facing paybill instructions

On the landlord Billing settings page, alongside the STK button, show a
"Pay via Paybill" card: *Business number 4326127, Account `SUB-{landlord_id}`*
(and `SMS-{landlord_id}` inside the SMS purchase modal), with copy buttons and the
note that activation is automatic within ~1 minute of payment. The account strings
must come from the API (add them to `GET /api/billing/` summary payload), never
assembled in the frontend.

---

## 6. Subscription payment — verified-only (D3)

### 6.1 Frontend switches to the STK flow

`client/src/features/landlord/settings/billingApiSlice.js` still calls the legacy
`POST /billing/pay-subscription`. Change the Billing settings page (and
`SubscriptionShortcut.jsx` if it links into payment) to:

1. Call `POST /api/billing/pay-subscription/stk` with
   `{ billing_cycle, phone, package_id? }` — phone input pre-filled from the
   landlord profile, validated as Safaricom format client-side too.
2. Handle the two success shapes: `201 simulated: true` (instant — show success and
   refresh billing) and `200` with `transaction.id` (real STK — show a
   "Check your phone" modal and **poll** `GET /api/billing/transactions/<id>/status`
   every 3 s, up to 2 minutes).
3. Terminal states: verified → success + refreshed subscription; `failed` → error
   with retry; poll timeout → "We haven't seen your payment yet — if you completed
   it, it will reflect automatically; otherwise try again." (the reconciliation job
   §9 sweeps up late callbacks).

### 6.2 Legacy endpoint demoted

`POST /api/billing/pay-subscription` (self-reported): **must no longer activate
anything.** It creates the `BillingTransaction` as today but `status=pending`,
`is_verified=False`, and does **not** touch the subscription; response message
changes to "recorded, pending verification by admin". The existing admin
verify endpoint (`admin_billing_routes` → `finalize_subscription_payment`) is the
release valve. Update its docstring and the affiliate spec cross-reference.
**Do not remove the endpoint** — it is the Daraja-outage escape hatch.

### 6.3 C2B path

Handled in §4.4/§5. Note the ordering trap: a landlord paying by paybill usually has
**no** pending `BillingTransaction`. In that case create one on the spot **only if**
`TransAmount` exactly equals a valid cycle price for that landlord
(`preview_subscription_cost` for monthly/quarterly/annual at their current package);
stamp `context_json` accordingly and finalise. Any other amount → unmatched queue.

### 6.4 Rent STK gated off (D1)

`POST /api/mpesa/stk-push` currently falls back to platform credentials, which
would route **tenant rent into Sahil's paybill** — commingling platform revenue
with landlords' rent. Gate it: if no *landlord-scoped* Daraja credentials exist
(none do today — the per-landlord fields don't exist yet), return
`409 {"error": "Direct M-Pesa prompts are not available yet. Rent payments go to your own paybill — use Co-Pilot or record the payment manually."}`.
Hide/disable the corresponding button in the landlord payments UI with the same
explanation. Do **not** delete the route or the C2B/status-check tooling — the
transaction table and manual matching stay.

---

## 7. SMS credit purchase — verified-only (D3)

### 7.1 New endpoint `POST /api/billing/buy-sms/stk`

Mirror `pay_subscription_stk` exactly: body `{ sms_count, phone }`; validate
`sms_count >= 100`; compute `amount` server-side from `sms_billing.load_rates()`
(reselling rate logic copied from the current `buy_sms`); create a pending
unverified `BillingTransaction(type=sms_purchase, sms_count=...)`;
`context_json = {"sms_count": sms_count, "unit_price": str(unit_price), "applied": false}`;
simulation mode → finalise instantly (201), else STK push with
`AccountReference=f"SMS-{landlord_id}"` and return 200 + transaction for polling.

### 7.2 New service function `billing_service.finalize_sms_purchase(txn, admin_id=None)`

Idempotent twin of `finalize_subscription_payment`: if `txn.is_verified` return;
read `sms_count` from `context_json` (fallback `txn.sms_count`); increment
`landlord.sms_balance`; set `status=paid`, `is_verified=True`, `verified_at`,
`ctx["applied"]=True`. No affiliate accrual (`accrue_for_transaction` already
ignores non-subscription types — keep it that way, and assert it in tests).

### 7.3 Legacy `POST /api/billing/buy-sms`

Same demotion as §6.2: pending + unverified, **no `sms_balance` increment**,
admin verification path (add `sms_purchase` support to the admin billing verify
endpoint so it dispatches to `finalize_sms_purchase`).

### 7.4 Frontend

The SMS purchase modal switches to the STK endpoint with the same
prompt-and-poll UX as §6.1, plus the `SMS-{landlord_id}` paybill card.

---

## 8. Affiliate payouts — B2C automation (D2)

### 8.1 Model changes (`AffiliateWithdrawal`)

Add columns:
```
b2c_originator_id   String(40), unique, nullable   # UUID we send to Daraja
b2c_conversation_id String(60), nullable           # Daraja's ConversationID
b2c_status          String(20), nullable           # 'sent' | 'result_received' | 'timeout' | 'failed'
b2c_result_code     Integer, nullable
b2c_result_desc     Text, nullable
paid_amount         Numeric(12, 2), nullable       # the whole-shilling amount actually sent
```

### 8.2 New admin endpoint `POST /api/admin/affiliates/withdrawals/<id>/pay-b2c`

Guards, in order:
1. `_require_admin()`; withdrawal exists; status in (`requested`, `processing`).
2. Affiliate `mpesa_number` normalises to a valid Safaricom MSISDN
   (`daraja_service.normalize_msisdn`) — else 400 telling the admin the affiliate
   must fix their payout profile.
3. **Idempotency / double-pay lock:** if `b2c_status == 'sent'` → 409 "payout
   already in flight". Set `b2c_status='sent'` and commit **before** the HTTP call
   (crash-safe: a retry after a crash sees 'sent' and refuses; §9's sweeper decides).
4. Simulation mode → skip HTTP, synthesise a receipt `SIMB2C{id:08d}`, call the
   existing `svc.pay_withdrawal(withdrawal, admin_id, receipt)`, done (this is how
   the flow is verified locally).
5. Real mode → require initiator env vars (else 503 with a clear message), call
   `daraja_service.b2c_payment(phone, paid_amount, remarks=f"SahilPay affiliate payout", occasion=withdrawal receipt-to-be, originator_id=uuid4)`.
   On Daraja acceptance (`ResponseCode == "0"`): store `b2c_conversation_id`, move
   status to `processing` if it was `requested`, notify nothing yet. On rejection:
   reset `b2c_status='failed'`, surface Daraja's error to the admin, leave the
   withdrawal payable manually.

**The existing manual `POST .../pay` endpoint stays untouched** as the fallback
(admin pays from the M-Pesa org portal and records the reference).

### 8.3 Amount rule

B2C amounts are whole shillings. `paid_amount = int(withdrawal.net_amount)` (floor).
Show both figures in the admin modal ("Net KES 1,234.56 → sending KES 1,234; the
KES 0.56 remainder stays in the program ledger"). Never round up.

### 8.4 Result webhooks

`POST /api/webhooks/daraja/b2c/result`:
- Log raw payload. Extract `Result.OriginatorConversationID`, `ResultCode`,
  `ResultParameters` (`TransactionReceipt`, `TransactionAmount`).
- Find the withdrawal by `b2c_originator_id`; unknown → log + 200.
- Idempotent: if already `paid` or `b2c_status='result_received'` → 200.
- `ResultCode == 0` → `svc.pay_withdrawal(withdrawal, admin_id=processed_by_admin_id or system, mpesa_reference=TransactionReceipt)`
  (that function already sets receipt number + notifies the affiliate), plus
  `b2c_status='result_received'`, `b2c_result_code/desc`.
- Non-zero → `b2c_status='failed'`, keep withdrawal in `processing`, notify all
  admins (category `affiliate_payout_failed`) with Daraja's `ResultDesc` so they
  can retry or pay manually. **Do not auto-retry** — money APIs are never retried
  blind.

`POST /api/webhooks/daraja/b2c/timeout`: mark `b2c_status='timeout'`, notify
admins; the withdrawal stays `processing` for manual follow-up (M-Pesa org portal
statement is the truth source).

### 8.5 Frontend

- **Admin** `AffiliateWithdrawalsQueue.jsx`: the Pay modal gets two actions —
  "Send via M-Pesa (B2C)" (primary; shows affiliate name, masked number, net vs
  whole-shilling amount, and a type-to-confirm) and "Record manual payment"
  (existing reference form). Show `b2c_status` chips on rows; a `failed`/`timeout`
  row shows the Daraja error and re-enables both actions.
- **Affiliate portal** `AffiliateWithdrawals.jsx`: statuses already render;
  ensure `processing` shows "Payment on the way" and `paid` shows the M-Pesa
  receipt + receipt number. No affiliate-triggered payout exists — verify none is
  accidentally exposed.

---

## 9. Reconciliation (missed callbacks)

New Celery beat task `tasks/` (follow the existing task layout), every 5 minutes,
skipped entirely when `MPESA_SIMULATION_MODE=true`:

1. **Stale STK:** pending unverified `BillingTransaction`s (subscription or
   sms_purchase) with a `payment_reference` that looks like a CheckoutRequestID
   (`ws_CO_*`), older than 3 minutes and younger than 24 h → `daraja_service.stk_query()`.
   ResultCode 0 → finalise via the §4.2 dispatch (amount check included);
   definitive failure codes (1032 cancelled, 1037 timeout, 1 insufficient funds)
   → `mark_subscription_payment_failed` / mark sms txn failed. Ambiguous → leave.
2. **Expiry:** same set older than 24 h → mark failed.
3. **Stuck B2C:** withdrawals with `b2c_status='sent'` older than 30 minutes →
   notify admins once (flag so it doesn't re-notify every run).

Rate-limit: max ~20 Daraja queries per run.

---

## 10. Security checklist (verify each, then tick in the PR description)

1. **Webhook spoofing is the #1 risk** — Daraja does not sign callbacks. Defenses,
   all required:
   - C2B confirmation trusts nothing client-side: activation requires exact
     server-computed amount match (§4.4/§6.3); anything else → human review.
   - STK callback only acts on a `CheckoutRequestID` **we issued** and that is
     still pending; amount must match (§4.2).
   - B2C result only acts on an `OriginatorConversationID` **we generated**.
   - App-level IP allowlist for `/api/webhooks/daraja/*`: config
     `DARAJA_ALLOWED_IPS` (comma-separated, default empty = allow all so local
     testing works; production doc §14 sets Safaricom's published callback ranges
     `196.201.212.0/24, 196.201.213.0/24, 196.201.214.0/24`). Take the client IP
     from the **leftmost untrusted-stripped** `X-Forwarded-For` only when
     `TRUST_PROXY=true` (nginx sets it); otherwise `remote_addr`. On mismatch:
     log to `DarajaCallbackLog` with error and return 200 **without processing**
     (returning 403 would tell an attacker they found a live endpoint; 200 keeps
     Daraja happy if the allowlist is misconfigured — the log makes it visible).
   - Rate-limit the webhook blueprint (e.g. `60/minute` per IP via Flask-Limiter).
2. **No secrets in code, logs, or git** (§2.2). Grep the diff for the consumer
   key prefix `2rVAcW` and shortcode-with-passkey concatenations before merging.
3. **Payout authorization:** `pay-b2c` reachable only by admin JWT
   (`_require_admin()` — confirm it checks role, not just a valid token, same as the
   other admin affiliate routes); double-pay lock (§8.2.3); withdrawal amount comes
   only from the DB row, **never** the request body.
4. **Self-service holes closed:** after §6.2/§7.3, prove by test that no
   unauthenticated or self-reported path mutates `sms_balance`, `Subscription.status`,
   or creates verified transactions.
5. **Idempotency everywhere:** duplicate C2B confirmation (same `TransID`),
   duplicate STK callback, duplicate B2C result — all must be provable no-ops (tests).
6. **Tenant/landlord isolation regression:** the new admin C2B queue and B2C
   endpoints must not leak cross-landlord data to landlord/team JWTs (403 tests).
7. **Audit trail:** every money mutation records `record_audit` (subscription
   finalise via webhook should audit with actor "system/daraja"; check
   `record_audit` supports a null actor — if not, use the landlord's user id with a
   clear description prefix `[DARAJA]`).
8. **HTTPS only** in production nginx; HTTP→HTTPS redirect; the webhook paths must
   not be cached.

---

## 11. Migrations

One Alembic revision (`alembic revision --autogenerate -m "mpesa production integration"`)
covering: `daraja_callback_logs` (§4.1), `platform_c2b_payments` (§5.1),
`AffiliateWithdrawal` B2C columns (§8.1). Follow the existing migration style
(see `e05d6bf1008d_billing_transaction_verification.py`). Run `alembic upgrade head`
against the dev database and confirm a clean downgrade.

---

## 12. Files expected to change (orientation, not a limit)

- `server/services/daraja_service.py` (new), `billing_service.py`,
  `affiliate_service.py` (only if `pay_withdrawal` needs a system-actor variant)
- `server/routes/webhook_routes.py`, `billing_routes.py`, `mpesa_routes.py`,
  `admin_billing_routes.py`, `admin_affiliate_routes.py`
- `server/models.py`, `config.py`, `.env.example`, one migration
- `server/tasks/` reconciliation task + beat schedule
- `client/src/features/landlord/settings/` billing page + `billingApiSlice.js`
- `client/src/features/admin/` withdrawals queue, billing/c2b queue, api slices
- `client/src/features/affiliate/AffiliateWithdrawals.jsx` (status rendering check)
- Tests: `server/tests/test_daraja_webhooks.py`, `test_billing_verified_flows.py`,
  `test_b2c_payouts.py` (new), extend `test_affiliate_service.py`

---

## 13. Verification plan (execute ALL of it; simulation mode ON unless stated)

### 13.1 Automated (pytest, in `server/`)

Write and run tests covering at minimum:
- C2B confirmation: SUB match → subscription verified + affiliate commission
  accrued at the referral's snapshotted rate; SMS match → balance credited; unknown
  ref → unmatched row + admin notification; duplicate TransID → no-op; wrong
  amount → unmatched, nothing activates.
- STK billing callback: success (both txn types), failure code, duplicate, unknown
  CheckoutRequestID, amount mismatch → flagged not finalised.
- Legacy endpoints: `pay-subscription` and `buy-sms` no longer grant service;
  admin verify path does.
- B2C: pay-b2c simulation → paid + receipt + affiliate notification; double-pay
  lock 409; result webhook success/failure/timeout/duplicate; floor-amount rule.
- Rent STK gate returns 409.
- Full affiliate chain integration test: referral attribution → simulated
  subscription STK payment → commission at custom override rate (set one) →
  withdrawal request → admin pay-b2c (simulated) → balance math per
  `get_balance` (§5 of affiliate spec) still exact.
- The whole existing suite passes: `pytest` green, zero regressions.

### 13.2 Webhook contract tests (curl against local server)

Simulate Safaricom with real production payload shapes (STK callback, C2B
confirmation incl. hashed MSISDN variant, B2C Result/timeout) via curl; verify
DB state after each, and that every response is HTTP 200 JSON. Also verify the IP
allowlist blocks processing (set `DARAJA_ALLOWED_IPS=1.2.3.4`, post from
localhost, confirm logged-but-ignored).

### 13.3 Browser verification — every portal (use the running dev servers)

- **Landlord:** Billing page → pay subscription via STK (simulation: instant
  success), cycle discounts still correct, paybill card shows `SUB-{id}`; buy SMS
  via STK; balance updates; billing transactions list shows verified badges; rent
  STK button absent/disabled with explanation; Payments page + Co-Pilot flows
  unchanged.
- **Admin:** billing → new Paybill payments tab, resolve an unmatched payment end
  to end; affiliate withdrawals queue → B2C pay (simulated) → status chips,
  receipt visible; program settings still save; verify legacy-payment admin
  verification works for both txn types.
- **Affiliate:** dashboard shows the commission from 13.1's chain; request
  withdrawal; see processing → paid with receipt after admin action; notification
  received.
- **Tenant:** portal payment instructions still show the **landlord's** paybill
  (never 4326127); self-report flow unchanged.
- **Team member:** permission-gated billing pages behave (no new leak).

### 13.4 Simulation-mode regression

With `MPESA_SIMULATION_MODE=true` (default), every flow above completes with **zero
outbound HTTP to Safaricom** (assert via a test that patches `requests` and fails
on any call from `daraja_service`).

---

## 14. Go-live runbook (owner actions — the code must be ready before these)

1. Deploy to `sahilpay.co.ke`: nginx serves `client/dist`, proxies `/api` → Flask
   (gunicorn), TLS via Let's Encrypt, `TRUST_PROXY=true`.
2. Daraja portal → complete **M-Pesa Express go-live** for the production app to
   obtain the **passkey** → `PLATFORM_DARAJA_PASSKEY`.
3. M-Pesa Organization portal (org admin): create an **API initiator** (operator
   with B2C API role), note the initiator name + password; generate the
   **SecurityCredential** on the Daraja portal (APIs → B2C → Security Credential
   tool, environment = production, paste initiator password) →
   `PLATFORM_DARAJA_INITIATOR_NAME` / `PLATFORM_DARAJA_SECURITY_CREDENTIAL`.
   Confirm with Safaricom that **B2C disbursement is enabled** on 4326127 and the
   utility/working account is funded.
4. Optionally enable **External Validation** on the paybill (org portal) so
   §4.3 validation fires; not required — confirmation-only works.
5. Production `.env`: `MPESA_SIMULATION_MODE=false`,
   `DARAJA_BASE_URL=https://api.safaricom.co.ke`,
   `DARAJA_ALLOWED_IPS=196.201.212.0/24,196.201.213.0/24,196.201.214.0/24`.
6. **Live 1-shilling tests** (before announcing): (a) STK subscription payment on a
   test landlord with a KES-1 custom package — verify activation + callback log;
   (b) direct paybill payment with account `SUB-{test id}`; (c) one real B2C payout
   of the minimum to a controlled phone number. Reverse/clean the test data after.
7. Watch `daraja_callback_logs` and the unmatched queue daily for the first week.
8. **Rotate the Daraja consumer secret** (it was shared in plaintext during setup)
   and update the server `.env`.

---

## 15. Resolved decisions & remaining open questions

Answered by the owner on 2026-07-15: D1–D4 in §0.1.

Remaining questions — proceed with the recommendation unless the owner objects:

| # | Question | Recommendation (build this) |
|---|----------|------------------------------|
| Q1 | Should unmatched paybill money ever be auto-refunded? | No — admin resolves manually via the §5.2 queue; refunds via the org portal. The Reversal API needs extra approval and is rarely worth it at this scale. |
| Q2 | Should landlords get email/SMS receipts for verified subscription payments? | Yes, cheap win: reuse the existing tax-invoice/receipt machinery to email a receipt on `finalize_subscription_payment`. Include it if time allows; otherwise ticket it. |
| Q3 | Per-landlord Daraja credentials for rent STK (Phase 2)? | Defer. Revisit after ≥3 landlords ask; requires encrypted credential storage and per-landlord URL registration. |
| Q4 | Should the B2C payout be triggerable by a second admin only (maker-checker)? | Current single-admin approval is acceptable at this volume; the type-to-confirm modal (§8.5) plus audit trail suffices. Revisit when payouts exceed ~KES 100k/month. |
| Q5 | What happens to the sub-shilling remainder on payouts (§8.3)? | Track implicitly (net vs paid_amount both stored); no ledger entry needed now. |
