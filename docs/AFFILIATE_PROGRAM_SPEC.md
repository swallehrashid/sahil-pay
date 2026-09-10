# Sahil Affiliate Program — Implementation Spec

> **Audience:** Claude Code (Sonnet) implementing this feature end-to-end on branch `backend-set-up` (or a feature branch off it).
> **Status:** APPROVED by owner. All design decisions below are final — do not re-litigate them. Where this spec says "exactly", the number or behaviour was verified by a ledger backtest (§12) and is an acceptance criterion.
> **Reference peer:** `CATEGORY_RESTRUCTURE_SPEC.md` — follow the same conventions this codebase already uses (route/service/audit patterns, RTK Query apiSlices, lazy routes in `client/src/routes/AppRoutes.jsx`).

---

## 1. What this feature is

A single-tier affiliate/referral program:

1. Anyone can register as an **affiliate** from a link on the public site (footer). Signup creates a `pending` affiliate; a **system admin approves** them, which activates their unique **referral code** (e.g. `SAH-7K3F`) and share link (`/register?ref=SAH-7K3F`).
2. When a landlord registers with that code (typed or via `?ref=` link), the landlord is **attributed** to the affiliate — silently, no commission talk in the landlord UI beyond an optional "Referral code" field.
3. Every **verified** subscription payment the landlord makes earns the affiliate a commission: default **40% of the monthly-equivalent amount for the landlord's first 4 paid billing months**. Both the rate and month count are admin-overridable globally, per-affiliate, and per-referral.
4. Commission accumulates in the affiliate's **balance** (a derived ledger figure, not a stored mutable number). The affiliate can request a **withdrawal**; the admin processes it (manual M-Pesa payout in phase 1), and both sides get a downloadable **KRA-compliant PDF receipt** breaking down gross / withholding tax / Sahil platform fee / net.
5. The **admin portal** gets: affiliate approval queue, per-affiliate drill-down with rate/duration controls, withdrawal-processing queue, a program-settings page, a dashboard overview (all affiliates → their landlords → active/inactive → earnings), and a **reports & analytics page** with downloadable per-affiliate payout / platform-fee / WHT reports (PDF/CSV/Excel).
6. **Everything is audited** through the existing `record_audit` service.

---

## 2. Final decisions (locked)

| # | Decision |
|---|----------|
| D1 | Commission accrues **only on verified subscription payments** (STK-push to Sahil's paybill confirmed by Daraja callback, or explicit admin confirmation). Never on self-reported payment references. SMS purchases are **excluded**. Custom-package landlords are **included** at their negotiated price. |
| D2 | Entitlement = **N billing months** (default 4), not calendar months. `monthly_equivalent = amount_paid / months_covered`; commission = `rate% × monthly_equivalent × min(months_covered, months_remaining)`. Cycle discounts flow through (commission is on money actually received). |
| D3 | The commission window **starts at the first verified subscription payment**, not at registration. Trial time never consumes the window. |
| D4 | Referral mechanism = **opaque code + share link carrying the code**. Code format `SAH-` + 4 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (no 0/O/1/I/L). Attribution locked at landlord registration; admin can attach/detach within a **7-day grace window** (audited). |
| D5 | Rate and months are **snapshotted onto the referral at attribution**. Changing the global default or an affiliate's override affects **future referrals only**. Admin may edit an individual referral's snapshot; that affects **future accruals only**, never rewrites history. |
| D6 | Payouts phase 1 = **manual admin queue** (admin pays via M-Pesa, enters reference, marks paid). Daraja B2C automation is a later phase — design the withdrawal flow so "approve" can later trigger B2C without schema change. |
| D7 | Withdrawal maths (order matters): `WHT = wht_rate% × gross` (quantized), `fee = fee% × gross` or flat (quantized), `net = gross − WHT − fee` (**derived, never independently rounded**). Admin-configurable: `min_withdrawal` (default KES 500), `wht_rate` (default 5% — owner to confirm with accountant; keep configurable), `fee_type` (`percent`/`flat`) + `fee_value` (default 3%). |
| D8 | Affiliates require **admin approval** before their code activates. Approval collects M-Pesa payout number + national ID. |
| D9 | A person may hold both landlord and affiliate accounts (separate logins). **Self-referral is hard-blocked**: attribution rejected when the registering landlord's email OR phone matches the affiliate's. Single-tier only — affiliates cannot refer affiliates. |
| D10 | Reversal of a commissioned billing transaction creates a **negative `reversed` ledger entry** and **restores the consumed months**. Balance may go negative; future commissions net against it. |
| D11 | Every withdrawal produces a **sequential-numbered PDF receipt** (gross / WHT % and amount / platform fee / net / M-Pesa ref / affiliate details / date), downloadable by the affiliate and the admin, stored like other generated PDFs. |
| D12 | All money is `Decimal`, quantized to `0.01` with **`ROUND_HALF_UP`** at each defined step. |
| D13 | Withdrawal guards are checked **in this order**: (1) another withdrawal already open → reject; (2) below minimum → reject; (3) exceeds available balance → reject. (Backtest S8–S10 found that any other order produces misleading errors.) Only **one open withdrawal** (`requested`/`processing`) at a time per affiliate. |
| D14 | A global **program kill switch** (`is_program_active`): when off, hide the public link, block new affiliate signups and new attributions; existing referrals keep accruing and balances remain withdrawable (obligations are honoured). |
| D15 | Suspending an affiliate: code stops attributing new landlords and withdrawals are blocked; existing referrals **keep accruing** (money earned on valid referrals is theirs). Admin sees a flag. |

---

## 3. Phase 0 (prerequisite): verified subscription payments

**Why:** `POST /api/billing/pay-subscription` (`server/routes/billing_routes.py`) currently trusts a typed `payment_reference` and instantly marks the `BillingTransaction` paid. If commissions keyed off that, a colluding affiliate+landlord could fabricate payments and withdraw real money. **Do not wire accrual to unverified transactions under any circumstances.**

Build:

1. **`POST /api/billing/pay-subscription/stk`** — same body as `pay-subscription` plus `phone`. Reuses the Daraja helpers in `server/routes/mpesa_routes.py` (`_daraja_access_token`, `_daraja_stk_password`) but with **platform** credentials from new env vars: `PLATFORM_DARAJA_SHORTCODE`, `PLATFORM_DARAJA_PASSKEY`, `PLATFORM_DARAJA_CONSUMER_KEY/SECRET`, `PLATFORM_DARAJA_STK_CALLBACK_URL` (falling back to the existing `DARAJA_*` vars in dev). Creates the `BillingTransaction` with a new status **`pending`** and stores the `CheckoutRequestID` in `payment_reference`.
2. **`POST /api/webhooks/mpesa/billing-callback`** (in `server/routes/webhook_routes.py`, following the existing STK-callback handler's shape): on success, set the transaction `paid`, set `is_verified=True`, activate the subscription (move the activation logic out of `pay_subscription` into a shared `billing_service` function so both paths use it), then call `affiliate_service.accrue_for_transaction(txn)` (§6). On failure/cancel, mark `failed`. **Must be idempotent** — look up by `CheckoutRequestID`; a duplicate callback is a no-op (backtest S11).
3. **Schema:** add `is_verified = Column(Boolean, default=False, nullable=False)` and `verified_at`, `verified_by_admin_id` (nullable FK `system_admins.id`) to `BillingTransaction`. Backfill existing rows `is_verified=False`.
4. **Admin manual confirmation** — `POST /api/admin/billing-transactions/<id>/verify`: for payments that arrive outside STK (bank, direct paybill). Sets `is_verified=True`, records who verified, then triggers the same accrual hook. Audited.
5. Keep the legacy `pay-subscription` endpoint working (it still activates the subscription) but its transactions stay `is_verified=False` and therefore **never accrue commission** until an admin verifies them.

---

## 4. Data model

One Alembic migration (follow `server/migrations/versions/b1c2d3e4f5a6_charge_category_restructure.py` conventions). All tables use the existing `TimestampMixin` / `CreatedAtMixin` from `server/models.py`.

### 4.1 New enums (add beside the existing ones in `models.py`)

```python
class AffiliateStatus(str, enum.Enum):
    pending   = "pending"     # signed up, awaiting admin approval
    active    = "active"
    suspended = "suspended"
    rejected  = "rejected"

class ReferralStatus(str, enum.Enum):
    active    = "active"      # attributed; window not yet exhausted
    completed = "completed"   # months_used == months_total
    void      = "void"        # admin-detached / fraud

class CommissionStatus(str, enum.Enum):
    pending   = "pending"     # created but underlying txn awaiting verification (rare; normally skip straight to confirmed)
    confirmed = "confirmed"   # counts toward balance
    reversed  = "reversed"    # underlying payment reversed — negative effect

class WithdrawalStatus(str, enum.Enum):
    requested  = "requested"
    processing = "processing"
    paid       = "paid"
    rejected   = "rejected"

class AffiliateFeeType(str, enum.Enum):
    percent = "percent"
    flat    = "flat"
```

Extend `UserRole` with `affiliate = "affiliate"`. Extend `AuditEntityType` with `affiliate`, `affiliate_referral`, `affiliate_commission`, `affiliate_withdrawal`. Extend `NotificationCategory` with `affiliate_approved`, `affiliate_commission_earned`, `affiliate_withdrawal_processed`, `affiliate_new_referral`.

### 4.2 `affiliates`

| column | type | notes |
|---|---|---|
| id | Integer PK | |
| user_id | FK `users.id`, unique, not null | role = `affiliate` |
| full_name | String(120) not null | |
| phone | String(20) not null | contact phone |
| mpesa_number | String(20) nullable | payout number, collected at/for approval; **required before first withdrawal** |
| national_id | String(30) nullable | required before first withdrawal (KRA) |
| kra_pin | String(20) nullable | optional, shown on receipts when present |
| referral_code | String(12) unique not null, index | `SAH-XXXX`, generated at signup, **inactive until approved** |
| status | String(12) not null default `pending` | enum AffiliateStatus |
| commission_rate_override | Numeric(5,2) nullable | null → use global default |
| commission_months_override | Integer nullable | null → use global default |
| approved_by_admin_id | FK `system_admins.id` nullable | |
| approved_at | DateTime nullable | |
| notes | Text nullable | admin-only |

`to_dict()` + a `to_admin_dict()` that adds ledger aggregates (balance, lifetime_earned, total_withdrawn, referral counts).

### 4.3 `affiliate_referrals`

| column | type | notes |
|---|---|---|
| id | Integer PK | |
| affiliate_id | FK `affiliates.id` not null, index | |
| landlord_id | FK `landlords.id` **unique** not null | one referrer per landlord, ever |
| rate | Numeric(5,2) not null | **snapshot** at attribution (D5) |
| months_total | Integer not null | snapshot |
| months_used | Integer not null default 0 | CheckConstraint `months_used >= 0 AND months_used <= months_total` |
| window_started_at | DateTime nullable | set on first verified payment (D3) |
| status | String(12) not null default `active` | enum ReferralStatus |
| attributed_by | String(20) not null default `registration` | `registration` \| `admin_grace` |

### 4.4 `affiliate_commissions`

| column | type | notes |
|---|---|---|
| id | Integer PK | |
| referral_id | FK `affiliate_referrals.id` not null, index | |
| affiliate_id | FK `affiliates.id` not null, index | denormalised for fast balance queries |
| billing_transaction_id | FK `billing_transactions.id` not null | **UniqueConstraint together with a `is_reversal=False` partial** — see idempotency below |
| amount | Numeric(12,2) not null | positive; reversal entries are separate negative rows? **No — see below.** |
| rate_applied | Numeric(5,2) not null | |
| monthly_equivalent | Numeric(12,2) not null | for receipts/reports |
| months_commissioned | Integer not null | |
| status | String(12) not null | enum CommissionStatus |
| reversed_at | DateTime nullable | |

Idempotency (backtest S11): partial unique index on `billing_transaction_id` `WHERE status != 'reversed'` (Postgres: `postgresql_where`). Reversal (D10) **flips the row's status to `reversed`** (and restores `months_used` on the referral) rather than inserting a negative row — this is exactly what the backtest verified. Balance treats `reversed` rows as 0.

### 4.5 `affiliate_withdrawals`

| column | type | notes |
|---|---|---|
| id | Integer PK | |
| affiliate_id | FK `affiliates.id` not null, index | |
| gross_amount | Numeric(12,2) not null | |
| wht_rate | Numeric(5,2) not null | snapshot of config at request time |
| wht_amount | Numeric(12,2) not null | |
| fee_type | String(10) not null | snapshot |
| fee_value | Numeric(12,2) not null | snapshot |
| fee_amount | Numeric(12,2) not null | |
| net_amount | Numeric(12,2) not null | CheckConstraint `wht_amount + fee_amount + net_amount = gross_amount` |
| status | String(12) not null default `requested` | enum WithdrawalStatus |
| receipt_number | String(30) unique nullable | assigned when marked paid: `AFR-YYYY-000001`, sequential (§7) |
| mpesa_reference | String(50) nullable | set by admin when paid |
| processed_by_admin_id | FK `system_admins.id` nullable | |
| processed_at | DateTime nullable | |
| rejection_reason | String(255) nullable | |

### 4.6 `affiliate_program_config` (single row, like `TrialConfig`'s global row)

| column | type | default |
|---|---|---|
| id | Integer PK | |
| default_commission_rate | Numeric(5,2) | 40.00 |
| default_commission_months | Integer | 4 |
| min_withdrawal | Numeric(12,2) | 500.00 |
| wht_rate | Numeric(5,2) | 5.00 |
| fee_type | String(10) | `percent` |
| fee_value | Numeric(12,2) | 3.00 |
| attribution_grace_days | Integer | 7 |
| is_program_active | Boolean | True |

Seed this row in the migration itself (and in `server/seed.py`).

### 4.7 `landlords` additions

`referral_code_entered = Column(String(12), nullable=True)` — raw code typed at signup, kept even if invalid, for the admin grace-window tool and dispute resolution.

---

## 5. Balance definition (single source of truth)

```
balance(affiliate) = SUM(commissions.amount WHERE status='confirmed')
                   − SUM(withdrawals.gross_amount WHERE status IN ('requested','processing','paid'))
```

- Never store a mutable balance column. Compute via one aggregate query in `affiliate_service.get_balance(affiliate_id)`; cache per-request only.
- `requested`/`processing` withdrawals hold the funds (backtest S8: a **rejected** withdrawal releases them automatically because it drops out of the sum).
- Balance **can be negative** after a clawback (backtest S5) — the UI must render this honestly ("KES −400.00 — a referred landlord's payment was reversed; future commissions will offset this").

---

## 6. Accrual engine — `server/services/affiliate_service.py`

The core function, called from the billing callback and from admin manual verification (§3). This algorithm is backtested; implement it exactly.

```python
def accrue_for_transaction(txn: BillingTransaction) -> AffiliateCommission | None:
    """Idempotent. Call ONLY with a verified subscription transaction."""
    if txn.type != BillingTransactionType.subscription.value: return None   # D1: SMS excluded
    if not txn.is_verified: return None                                      # D1: verified only
    referral = AffiliateReferral.query.filter_by(
        landlord_id=txn.landlord_id, status=ReferralStatus.active.value
    ).with_for_update().first()                                               # lock: races, see §10
    if referral is None: return None                                          # backtest S12
    # idempotency — partial unique index also enforces this at DB level (S11)
    if AffiliateCommission.query.filter(
        AffiliateCommission.billing_transaction_id == txn.id,
        AffiliateCommission.status != CommissionStatus.reversed.value,
    ).first(): return None

    months_covered = _CYCLE_MONTHS[subscription.billing_cycle]  # 1 / 3 / 12, same map as billing_routes
    remaining      = referral.months_total - referral.months_used
    commissionable = min(months_covered, remaining)
    if commissionable <= 0: return None

    monthly_equiv = Decimal(txn.amount) / months_covered
    commission    = (referral.rate / 100 * monthly_equiv * commissionable)\
                        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)   # D12

    if referral.window_started_at is None:
        referral.window_started_at = datetime.utcnow()                        # D3
    referral.months_used += commissionable
    if referral.months_used >= referral.months_total:
        referral.status = ReferralStatus.completed.value

    row = AffiliateCommission(referral_id=referral.id, affiliate_id=referral.affiliate_id,
                              billing_transaction_id=txn.id, amount=commission,
                              rate_applied=referral.rate, monthly_equivalent=q(monthly_equiv),
                              months_commissioned=commissionable,
                              status=CommissionStatus.confirmed.value)
    db.session.add(row)
    # record_audit(... entity_type="affiliate_commission" ...)
    # notify affiliate: affiliate_commission_earned
    return row
```

`reverse_for_transaction(txn)` implements D10: find the confirmed commission for `txn.id`, set `status=reversed`, `referral.months_used -= months_commissioned`, and if the referral was `completed`, set it back to `active`. Audited + affiliate notified. Wire it wherever a `BillingTransaction` gets refunded/failed after verification (admin `correct-data` path at minimum).

Also in this service: `attribute_referral(...)` (used by registration and the admin grace tool; enforces D4/D9 — self-referral block by email/phone match against the affiliate's user, unique landlord constraint, program kill switch, affiliate must be `active`), `get_balance`, `get_affiliate_summary` (dashboard aggregates), `request_withdrawal` (guards **in D13 order**, snapshot config values), `process_withdrawal` / `reject_withdrawal`.

**Registration hook** (`server/routes/auth_routes.py::register`): accept optional `referral_code`; store raw value on `landlord.referral_code_entered`; if it matches an `active` affiliate and passes the self-referral check, create the referral. **An invalid/inactive code must NOT block or fail landlord registration** — register normally, skip attribution silently (edge case E3, §10).

---

## 7. Withdrawals & the KRA receipt

Flow: affiliate requests (guards per D13; requires `mpesa_number` + `national_id` on file — else 400 telling them to complete their payout profile) → admin queue shows it → admin marks `processing` → pays manually via M-Pesa → enters `mpesa_reference`, marks `paid` → receipt number assigned → PDF becomes available to both sides → affiliate notified. Admin may `reject` with a reason (funds auto-release, D13/S8).

**Receipt numbering:** `AFR-<year>-<6-digit sequence>` assigned **only when paid**, from a `SELECT max ... FOR UPDATE`-guarded query per year (or a Postgres sequence). Never reuse or skip visible gaps silently — rejected withdrawals simply never get a number.

**Receipt PDF** — new `generate_affiliate_receipt_pdf(withdrawal)` in `server/services/pdf_service.py`, using the existing `_shell`/`_money` helpers so it matches house style (see `generate_tax_invoice_pdf` at `pdf_service.py:107` as the model). Required content:

- Header: Sahil branding, "Affiliate Commission Payout Receipt", receipt number, date paid.
- Payee: affiliate full name, national ID, KRA PIN (if on file), M-Pesa number (masked to last 4 in the affiliate's copy is NOT required — show full; both parties already know it).
- Breakdown table (all figures KES, 2dp):
  - Gross commission withdrawn: `gross_amount`
  - Withholding tax (`wht_rate`% — e.g. "5%"): `−wht_amount`
  - Sahil platform fee (`fee_value`% or flat): `−fee_amount`
  - **Net paid to affiliate: `net_amount`**
- M-Pesa transaction reference.
- Footer note: "Withholding tax deducted at source and remitted to KRA by Sahil." (static copy; owner's accountant may adjust wording later).
- **Invariant printed and enforced:** WHT + fee + net = gross, exactly (DB CheckConstraint from §4.5; backtest S15 fixture: gross 777.77 → WHT 38.89, fee 23.33, net 715.55).

Endpoints: `GET /api/affiliate/withdrawals/<id>/receipt` (own only) and `GET /api/admin/affiliates/withdrawals/<id>/receipt` — both return the PDF (`Content-Disposition: attachment`), generated on demand from the stored snapshot columns (no need to persist the file; regeneration is deterministic because every input is snapshotted on the row).

---

## 8. Backend routes

Three new blueprints, registered in `server/routes/__init__.py` and `server/app.py` like the others.

### 8.1 `affiliate_auth` (public, rate-limited like `auth_routes`)

- `POST /api/affiliate/register` — {full_name, email, phone, password}. Creates `User(role=affiliate, is_verified=False)` + `Affiliate(status=pending)` + referral code. Sends the existing verification email. Blocked when `is_program_active` is false (403 with clear message).
- Login reuses the existing `POST /api/auth/login` — extend its role handling so `affiliate` users get a token and the client redirect map (`client/src/routes/roleRedirect.js`) sends them to `/affiliate`.

### 8.2 `affiliate_portal` (`@jwt_required` + new `require_affiliate()` decorator modelled on `require_landlord_or_team`)

- `GET /api/affiliate/dashboard` — balance, lifetime earned, total withdrawn, pending withdrawal, counts {total referrals, active (window running), completed, not-yet-paying}, **projected monthly earnings** (sum over active referrals of `rate% × current subscription_cost` for landlords with a live subscription), referral code + share link.
- `GET /api/affiliate/referrals` — paginated; per row: landlord company name, package name, subscription status (trial/active/suspended), monthly value, `rate`, `months_used/months_total`, earned-so-far. **Do NOT expose landlord contact details** (email/phone) to affiliates — company name + status only.
- `GET /api/affiliate/commissions` — paginated ledger.
- `GET /api/affiliate/withdrawals` + `POST /api/affiliate/withdrawals` + the receipt endpoint (§7).
- `GET/PATCH /api/affiliate/profile` — name, phone, mpesa_number, national_id, kra_pin. Changing `mpesa_number` is audited and notifies the affiliate by email (payout-fraud guard).

### 8.3 `admin_affiliate_routes` (guard with the same `_require_admin()` pattern as `admin_routes.py`)

- `GET /api/admin/affiliates` — list + filters (status) + per-row aggregates; includes **total outstanding liability** (sum of all balances) in the envelope for the dashboard.
- `GET /api/admin/affiliates/<id>` — full drill-down: profile, referrals w/ landlord links, commissions, withdrawals.
- `POST .../<id>/approve` (requires mpesa_number+national_id present or supplied in body), `POST .../<id>/reject`, `POST .../<id>/suspend`, `POST .../<id>/reactivate`.
- `PATCH .../<id>` — rate/months overrides, notes (D5: affects future referrals only).
- `PATCH /api/admin/affiliates/referrals/<id>` — edit a single referral's `rate`/`months_total` snapshot (D5, backtest S7/S16; extending `months_total` on a `completed` referral must set it back to `active` — S16). `POST .../referrals/<id>/void`.
- `POST /api/admin/affiliates/attribute` — grace-window tool: {landlord_id, affiliate_id}; allowed only within `attribution_grace_days` of landlord registration; runs the same self-referral checks; audited with description naming both parties.
- `GET/PATCH /api/admin/affiliates/config` — program settings incl. kill switch.
- Withdrawal queue: `GET /api/admin/affiliates/withdrawals?status=`, `POST .../withdrawals/<id>/process`, `POST .../withdrawals/<id>/pay` {mpesa_reference}, `POST .../withdrawals/<id>/reject` {reason}.
- **Reports** (§9): `GET /api/admin/affiliates/reports/<report>?fmt=pdf|csv|xlsx&start_date&end_date`.

Every state-changing endpoint calls `record_audit` with the new entity types, both before-and-after data where the codebase pattern does (see `admin_routes.py::override_subscription`).

---

## 9. Admin reports & analytics

New `server/services/affiliate_report_service.py` reusing `export_service.py`'s `_render_table` / `_render_pdf_table` / `_render_excel` helpers (they already handle the three formats).

Reports (each filterable by date range, each downloadable in PDF/CSV/Excel):

1. **Payouts report** — per affiliate: gross paid out, WHT withheld, platform fee collected, net paid, # withdrawals. Totals row. *(This is the owner's KRA remittance working paper — WHT column is mandatory.)*
2. **Earnings report** — per affiliate: commissions confirmed in period, reversed in period, current balance, lifetime earned.
3. **Referral performance report** — per affiliate: referrals attributed in period, # converted (window started), # active windows, # completed, conversion rate, revenue generated by their landlords in period vs commission cost. Effective commission cost % for the platform.
4. **Program summary** — one-pager: total liability (all balances), total paid out to date, total WHT remitted, total platform fees collected, top 10 affiliates by earnings, kill-switch state.

Analytics endpoint for the admin page charts: `GET /api/admin/affiliates/analytics` — monthly time series (commissions accrued, payouts, fees, WHT), affiliate leaderboard, referral funnel counts (signed up → approved → ≥1 referral → ≥1 converted).

---

## 10. Edge-case & failure handbook (simulate-and-handle — all MUST be covered by tests)

Backtest-verified cases (fixtures in §12):

| # | Scenario | Required behaviour |
|---|---|---|
| E1 (S1) | Monthly landlord pays 6× KES 1000 | 4 commissions of 400.00; months 5–6 accrue **nothing**; referral `completed` after month 4; balance 1600.00 |
| E2 (S2) | Annual prepay 10 200 (15% off 12 000) in month 1 | ONE commission of **1360.00** (40% × 850 × 4), referral immediately `completed`; a second annual payment accrues nothing |
| E3 | Landlord enters invalid/expired/inactive code at signup | Registration succeeds normally, no attribution, raw code stored on `landlord.referral_code_entered`; admin can fix via grace tool |
| E4 (S3) | Quarterly 2 700 × 2 | 1080.00 then **360.00** (capped to 1 remaining month); total 1440.00 |
| E5 (S4) | Payment reversed before withdrawal | Commission → `reversed`, months restored, balance drops by the amount; a replacement payment accrues fresh |
| E6 (S5) | Clawback **after** payout | Balance goes **negative** (−400.00 in fixture); referral reopens (`active`, months_used 3); next accrual nets it to 0. Withdrawals blocked while balance < min |
| E7 (S6) | Admin changes global default rate | Existing referrals keep their snapshot; only new attributions take the new default |
| E8 (S7) | Admin edits one referral's rate mid-window | Applies to future accruals only (fixture: 400+400+500+500) |
| E9 (S8–10) | Withdrawal guards | Check order per D13; rejected withdrawal releases held funds |
| E10 (S11) | Daraja fires the callback twice | Second call is a no-op (app check + partial unique index as backstop) |
| E11 (S12) | Self-referral | Attribution rejected at registration AND at the admin grace tool (email or phone match) |
| E12 (S13/S14) | Custom package / package change mid-window | No special code path needed — commission follows the verified amount paid (fixtures 1200.00 / 2400.00) |
| E13 (S15) | Rounding | 999.99→400.00; 333.33→133.33; quarterly 1000.01 with 2 months left→266.67; receipt identity holds on 777.77 |
| E14 (S16) | Admin extends months on a completed referral | Referral reopens; further payments accrue (fixture 2400→3200 at 8 months) |
| E15 (S17) | Referred landlord never converts (trial expires) | `window_started_at` stays null; shows as "not yet paying" with **potential** earnings (rate × estimated cost); zero money moves |

Operational cases (not expressible in the pure-ledger backtest — handle in code):

| # | Scenario | Required behaviour |
|---|---|---|
| E16 | Two callbacks / a callback and an admin-verify race on the same landlord | `with_for_update()` on the referral row inside the accrual transaction; the partial unique index makes the loser a no-op, not a crash (catch `IntegrityError`, rollback, return None) |
| E17 | Affiliate requests withdrawal while admin reverses a commission concurrently | Take the affiliate row lock (`SELECT ... FOR UPDATE` on affiliate) in both `request_withdrawal` and `reverse_for_transaction`; re-check balance after acquiring |
| E18 | STK push times out / user cancels | Transaction stays `pending`→`failed`; subscription NOT activated; no accrual. Provide `GET /api/billing/transactions/<id>/status` for the client to poll |
| E19 | Landlord suspended/deactivated mid-window | Nothing special: no payments → no accrual. Referral stays `active` (window is payment-counted, not time-counted) |
| E20 | Affiliate suspended with positive balance | Withdrawals blocked with explicit message; accrual continues (D15); admin drill-down shows the held balance |
| E21 | Kill switch off | Public link hidden (public config endpoint §11.1), affiliate signup 403, attribution skipped at registration; everything else keeps working (D14) |
| E22 | Affiliate deletes… | There is no self-delete. Admin cannot hard-delete an affiliate with ledger rows — suspend instead (enforce 409) |
| E23 | Landlord already attributed, second code arrives via grace tool | 409 — `landlord_id` unique constraint; the admin must void the existing referral first (audited) |
| E24 | Receipt regenerated years later after config changed | Deterministic: every input (rates, fee type/value) is snapshotted on the withdrawal row — NEVER read live config when rendering a receipt |
| E25 | `months_covered` for a cycle the map doesn't know | Defensive: unknown `billing_cycle` → log + no accrual + admin notification, never a 500 in the webhook (Daraja retries on non-200; always return 200 with a result body once the payload is parsed) |

---

## 11. Frontend

Follow existing patterns exactly: RTK Query slice injected via `client/src/store/apiSlice.js` tag conventions, lazy imports + routes in **`client/src/routes/AppRoutes.jsx`** (this is the real layout/routing file — not DashboardLayout), role redirect in `client/src/routes/roleRedirect.js`.

### 11.1 Public site

- Footer (in the shared public layout used by `client/src/features/public/Home.jsx` et al.): "Become an Affiliate" link → `/affiliate/register`. Render only when the program is active — extend the existing public config/packages endpoint (`server/routes/public_routes.py`) with `affiliate_program_active`.
- `/affiliate/register` — public page in `features/public/` styling (mobile-first, matches Phase-2 SEO pages): short pitch (earn 40% of referred landlords' subscriptions for their first 4 months — pull the live defaults from the public config so marketing copy never drifts from config), signup form, "pending approval" success state.

### 11.2 Landlord registration (`client/src/features/auth/LandlordRegistration.jsx`)

- On mount: read `?ref=` from the URL **and** `localStorage.sahil_ref` (set it from any public page when `?ref=` is present, so the code survives browsing to Pricing first). 
- Collapsed optional field "Have a referral code?" pre-filled from the above. Send as `referral_code`. No commission messaging.

### 11.3 Affiliate portal — new `client/src/features/affiliate/`

`affiliateApiSlice.js`, plus pages wired under `/affiliate/*` behind the `affiliate` role:

- **AffiliateDashboard.jsx** — balance card (handle negative state per E6 with the explanatory copy), lifetime earned, projected monthly, referral code with copy-link button, referral stat tiles (total / paying / completed / not-yet-paying).
- **AffiliateReferrals.jsx** — table: company, package, status badge, monthly value, months used of total, earned so far. Paginated.
- **AffiliateEarnings.jsx** — commission ledger (date, landlord, amount, status incl. `reversed` rendered as a negative red row).
- **AffiliateWithdrawals.jsx** — balance, request form (shows live gross→WHT→fee→net preview computed from config fetched via API — never hardcode rates client-side), history table with status chips and a **Download receipt** button on `paid` rows.
- **AffiliateProfile.jsx** — payout details (M-Pesa number, national ID, KRA PIN); block withdrawal page with a banner if these are missing.
- Reuse the portal shell pattern from the tenant/teamMember portals (navbar/sidebar in a `components/` subfolder).

### 11.4 Admin — additions to `client/src/features/admin/`

`adminAffiliateApiSlice.js`, plus:

- **AffiliatesManagement.jsx** — tabs: All / Pending approval / Suspended. Row: name, code, status, referrals (active/total), lifetime earned, balance, actions. Header stat: **total outstanding liability**.
- **AffiliateDetail.jsx** — profile + approve/reject/suspend controls, rate & months override inputs, referral table (each row → landlord detail link, editable per-referral rate/months, void button), commission ledger, withdrawal history.
- **AffiliateWithdrawalsQueue.jsx** — requested/processing queue; process → pay (M-Pesa ref modal) → receipt download; reject with reason.
- **AffiliateReports.jsx** — the four reports of §9 with date-range pickers and PDF/CSV/Excel download buttons (mirror `StatementsPage.jsx` patterns); analytics charts (monthly accrual vs payout, leaderboard, funnel).
- **AffiliateProgramSettings.jsx** — global defaults, WHT rate, fee, min withdrawal, grace days, kill switch (with a confirm dialog spelling out D14 consequences).
- Add "Affiliates" to `AdminSidebar.jsx` and a summary card (affiliate count, liability, pending approvals, pending withdrawals) to `AdminDashboard.jsx`.

---

## 12. Mandatory test plan

### 12.1 Unit tests — port the backtest

The design was validated by a standalone ledger simulation (17 cases, all passing). **Port every scenario to pytest against the real service layer** (`server/tests/test_affiliate_service.py` or wherever tests live — check for an existing tests dir and follow it). The exact expected values are acceptance criteria:

| Fixture | Inputs | Expected |
|---|---|---|
| S1 | 40%/4mo, 6 monthly payments of 1000 | commissions `[400.00 ×4, none, none]`; balance 1600.00; referral completed |
| S2 | annual 10 200 (12 mo) | one commission **1360.00**; completed; second payment → None |
| S3 | quarterly 2 700 ×2 | 1080.00 then 360.00; total 1440.00 |
| S4 | 1000 paid, reversed, repaid | balance 400.00; months_used 1 |
| S5 | earn 1600, withdraw all, reverse one 1000 payment, repay | receipt 1600/80.00/48.00/1472.00; balance −400.00 then 0.00 |
| S6 | global default 40→50 mid-window | old referral accrues 400, new referral 500 |
| S7 | per-referral rate 40→50 after 2 months | 400+400+500+500 = 1800.00 |
| S8–10 | withdraw 100 / 9999 / second-while-open | errors in D13 order; reject releases funds (balance back to 800.00) |
| S11 | duplicate accrual call same txn | second returns None; balance 400.00 |
| S12 | affiliate email/phone == landlord email/phone | attribution raises/400s |
| S13 | custom package 750/mo ×4 | 1200.00 |
| S14 | payments 1000,1000,2000,2000 | 2400.00 |
| S15 | 999.99 / 333.33 / 1000.01-quarterly-2-left / withdraw 777.77 | 400.00 / 133.33 / 266.67 / receipt 38.89+23.33+715.55=777.77 |
| S16 | 6-month referral completed, extended to 8 | 2400.00 → 3200.00; status completed→active→completed |
| S17 | referral never pays | window_started_at null; balance 0; visible as not-yet-paying |

Plus integration tests for E16–E25 (webhook idempotency via double-POST of the same callback payload; race tests can be lighter — assert the locks/IntegrityError path exists).

### 12.2 End-to-end regression (both portals) — run before calling this done

Use the Playwright MCP workflow already used for the four-portal regression passes. Full pass, in order, against seeded data (`server/seed.py` must gain: 2 affiliates — one active w/ history, one pending; 3 referred landlords — one paying monthly mid-window, one completed, one still on trial; 1 paid withdrawal w/ receipt; 1 requested withdrawal):

1. **Public →** footer link visible; affiliate registration; success state. Toggle kill switch in admin → link disappears, signup 403s.
2. **Admin →** pending affiliate appears; approve (supply M-Pesa + ID); code becomes active.
3. **Landlord signup →** register via `?ref=` link (assert the field pre-fills), and a second landlord typing the code manually; a third with a garbage code (must register fine — E3). Verify attributions in admin drill-down.
4. **Billing →** run the STK flow in sandbox/simulation (per the no-Redis dev setup in the env-setup notes) or use the admin manual-verify endpoint; assert the commission appears in BOTH portals with the right amount (1000 → 400.00 at defaults).
5. **Window exhaustion →** verify 4 payments then a 5th: 5th accrues nothing; referral shows completed in both portals.
6. **Overrides →** change a referral to 50%, pay, assert 500.00. Extend months on the completed referral, pay, assert accrual resumes (S16).
7. **Withdrawal →** request below min (blocked with message); request valid; admin queue → process → pay with reference; **download the receipt from BOTH portals** and verify the four figures and that they sum; affiliate balance decremented; audit rows present for every step.
8. **Clawback →** reverse a commissioned transaction in admin; affiliate balance goes negative with the explanatory banner; next payment nets it back.
9. **Reports →** generate all four reports in all three formats; verify the payouts report's WHT/fee/net columns against the withdrawal from step 7. Check the analytics page renders.
10. **Audit →** master audit log filtered to the new entity types shows every action from steps 2–9 with correct actor + before/after data.
11. **Access control →** affiliate token cannot hit admin/landlord endpoints and vice-versa; affiliate A cannot read affiliate B's withdrawals/receipts (change the id in the URL); referrals endpoint does not leak landlord email/phone.

### 12.3 Definition of done

- [ ] Migration applies cleanly on a fresh DB AND on top of the current head; `seed.py` runs.
- [ ] All §12.1 fixtures pass with exact values.
- [ ] Full §12.2 pass completed in both portals, no console errors.
- [ ] Every state change appears in the audit log.
- [ ] No accrual path exists from an unverified transaction (grep for callers of `accrue_for_transaction` and prove each guards on `is_verified`).
- [ ] Receipt CheckConstraint present in DB (`wht + fee + net = gross`).
- [ ] Kill switch verified end-to-end.

---

## 13. Build order

1. **Phase 0** — verified billing (§3) + migration for `BillingTransaction` columns.
2. **Migration** — all §4 tables + enums + config seed.
3. **Service layer** — `affiliate_service.py` + pytest port of the backtest (§12.1). *Do not proceed until all fixtures pass.*
4. **Routes** — affiliate auth/portal, admin, registration hook, webhook accrual wiring.
5. **Receipts & reports** — pdf_service addition, report service, report/analytics endpoints.
6. **Frontend** — public page + registration field → affiliate portal → admin section.
7. **Seed data + full §12.2 regression in both portals.**
8. Notifications/emails polish; update `seed data credentials` file with the affiliate test logins.

Out of scope for this build (explicitly deferred): Daraja B2C automated payouts; multi-tier referrals; affiliate-facing marketing asset library.
