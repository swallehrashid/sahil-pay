# OPUS EXECUTION SPEC — SahilPay Feature & Hardening Programme

**Audience:** Claude Opus, executing autonomously in this repo.
**Authored by:** Fable 5, after a full repo survey and requirement clarification with the owner (Swalleh).
**Date:** 2026-08-06

This file is the single source of truth for the next development programme. Execute the
phases **in order** — they are sequenced so that schema changes land early, the two
business-critical phases (1 and 2) ship first, and cosmetic work comes last. Every phase
ends with tests and explicit acceptance criteria. Do not skip the tests.

---

## Phase 0 — Conventions & guardrails (read before writing any code)

1. **Stack recap:** Flask + SQLAlchemy (declarative, `server/models.py`, ~3,400 lines), Alembic
   migrations (`server/migrations/versions/`), Celery + Beat (`server/tasks/`), React 19 + Redux
   Toolkit Query + Tailwind 4 (`client/`), portals: admin / landlord / teamMember / tenant /
   affiliate / public under `client/src/features/`.
2. **Every schema change = one Alembic migration.** Autogenerate, then hand-verify. Never edit
   an already-applied migration.
3. **Scoping chokepoints:** all landlord-scoped routes resolve the acting landlord through
   `decorators.get_current_landlord_id()` and team permissions through
   `@require_permission(module, action)`. Any new route MUST use the same pattern —
   `@jwt_required()` → `@require_landlord_or_team()` → `@require_permission(...)` → filter every
   query by the resolved `landlord_id`.
4. **Soft delete:** `Tenant`, `Property`, `Unit`, `Invoice`, `Payment`, `Expense` are soft-deleted.
   Always filter `is_deleted.is_(False)` in new queries unless the feature is explicitly about
   archived rows.
5. **Money:** `Decimal` everywhere server-side, `Numeric(12,2)` columns, `_serialise()` in
   `to_dict()`s.
6. **Do NOT touch:** the M-Pesa webhook URL paths (`/api/webhooks/daraja/...` are registered with
   Safaricom against `https://sahilpay.co.ke` and cannot change), the allocation engine
   (`services/allocation_service.py`) semantics, and the charge-category subcategory model
   (`deposit` / `balance` / `current` on `InvoiceLineItem.subcategory`).
7. **Demo shadow landlords:** rows with `Landlord.is_demo == True` are hidden practice accounts.
   Every new admin-facing query, list, metric, and Celery task MUST exclude them
   (`Landlord.is_demo.is_(False)`). Phase 10 sweeps the existing ones; don't add new leaks.
8. **Audit:** mutations call `services.audit_service.record_audit(...)` — follow the existing
   call shape (see `routes/tenant_routes.py:create_tenant` for the canonical example).
9. **Tests** live in `server/tests/`. Run with the venv at `server/venv`. New backend behaviour
   gets pytest coverage; security phase adds a dedicated cross-portal access suite.
10. **Rent identification (used by Phases 2 and 4):** rent charges are line items whose
    `category_id` points at the landlord's default **"Rent"** `ChargeCategory` (created by
    `services/category_service.seed_default_categories`; `is_default=True`, `name="Rent"`).
    Add one shared helper in `services/category_service.py`:
    ```python
    def rent_category_id(landlord_id: int) -> int | None:
        """The landlord's canonical Rent category id (is_default, name 'Rent')."""
    ```
    - Rent **commissionable / scoreable** money = allocations to line items with that
      `category_id` AND `subcategory IN ('current', 'balance')`.
    - `subcategory == 'deposit'` is NEVER rent income — it is refundable held money.

---

## Phase 1 — Huge property-manager readiness  *(HIGHEST PRIORITY)*

### Business context
A target client ("Raa"-type property manager): 100+ landlords/properties under management,
1,000+ tenants, 200+ caretakers. All tenants pay the PM's paybill; the PM signs up as ONE
SahilPay account (`Landlord.account_type == "property_management"`); the individual property
owners get **view-only team-member logins scoped to their own properties**; caretakers get
**utilities-entry-only team-member logins scoped to their properties**. Reports are per property.

The bones already exist: `TeamMember` (viewer/editor role), `TeamMemberPermission` (12 modules ×
can_view/can_edit), `TeamMemberPropertyAccess` (per-property scoping via
`decorators.scope_to_accessible_properties`). This phase makes it operable and provable at scale.

### 1.1 Role presets (frontend + one new column)

**Migration:** add `team_members.preset` — `String(20)`, nullable. Values:
`owner`, `caretaker`, `accountant`, `secretary`, `custom` (null = legacy/custom).

**Backend:** `routes/team_routes.py` — accept and persist `preset` on create/update. Include in
`TeamMember.to_dict()`.

**Frontend:** in the landlord portal's team-member create/edit form
(`client/src/features/landlord/...` team management components) add a **preset picker** rendered
as cards ABOVE the permission matrix. Selecting one pre-fills the matrix + property scope but
everything stays individually editable afterwards (owner's requirement: "very, very specific and
finite permissions" — presets are shortcuts, the matrix is the truth):

| Preset | role | Permissions pre-filled | Property scope |
|---|---|---|---|
| **Owner (view only)** | viewer | view: properties, units, tenants, payments, invoices, reports, expenses, maintenance | specific properties (forced — cannot pick "all") |
| **Caretaker** | editor | view+edit: utilities, unit_utilities; view: units, tenants (name+unit only via normal views) | specific properties (forced) |
| **Accountant** | editor | view+edit: payments, invoices, expenses, reports; view: tenants, properties, units | all (default, editable) |
| **Secretary** | editor | view+edit: tenants, messages, maintenance; view: units, properties | all (default, editable) |
| **Custom** | — | empty matrix | free |

Show the preset as a colored badge in the team member list and in the admin portal's
`AdminTeamMembers.jsx` / `TeamMemberDetail.jsx`.

### 1.2 Permission coverage audit (make "hide it from them" true everywhere)

Walk EVERY page reachable in the team-member portal (`client/src/features/teamMember/` renders
the landlord feature pages behind permission gates) and every `/api` route decorated
`@require_landlord_or_team()`, and verify each maps to a `PermissionModule` with the correct
action. Known gaps to check and fix:

- Charge-category management (`routes/charge_category_routes.py`) — must require `invoices` edit
  (or introduce nothing new; just gate it).
- Utility bulk upload + invoice generation (`routes/utility_routes.py` `/bulk-upload*`) — `utilities` edit.
- Documents (`routes/document_routes.py`) — gate under `tenants` view/edit.
- Communications/bulk reminders (`routes/communication_routes.py`, `tenant_routes.py:bulk_reminder`) — `messages` edit.
- Reports exports — `reports` view (verify every endpoint in `report_routes.py` — already done, confirm).
- Settings routes must remain landlord-only (no team access) — verify `settings_routes.py` rejects team members.
- **Frontend:** the team portal must HIDE (not just 403) any nav item / button whose module the
  member lacks `can_view` for. Audit `TeamMemberDashboard.jsx` + the shared nav for all 12 modules.
- **Property scoping:** verify `scope_to_accessible_properties` is applied on every list endpoint
  a team member can reach (tenants, units, payments, invoices, expenses, utilities, maintenance,
  reports). Any endpoint that filters only by `landlord_id` and not by the member's property set
  is a bug — fix it. Write one parametrised pytest that creates a member scoped to property A and
  asserts rows from property B never appear in ANY list endpoint.

### 1.3 Owner monthly statements (automation)

**Migration:** add to `automation_settings`: `owner_reports_enabled` (Boolean, default False),
`owner_reports_day` (Integer, nullable, 1–28).

**Backend:** new Celery Beat task in `tasks/communication_tasks.py`:
`send_owner_monthly_statements` — daily tick; for each non-demo landlord with
`owner_reports_enabled` and `owner_reports_day == today.day`: for each team member with
`preset == 'owner'` and an email, for each property in their
`TeamMemberPropertyAccess`, render last calendar month's property statement PDF
(`report_generators.build_property_statement` + `report_builder.render_document`, honouring the
Phase 2 gross-basis setting) and email it via a new `email_service.send_owner_statement_email`
(use the standard `render_email` shell + attachment, mirroring `send_statement_email`). Log one
`CommunicationLog` row per send. Skip and log per-property failures; never abort the batch.

**Frontend:** two controls in landlord Settings → Automation.

### 1.4 Owner disbursements (payouts ledger)

**Migration:** new table `owner_payouts`:
`id, landlord_id (FK, idx), property_id (FK, idx), amount Numeric(12,2) NOT NULL,
payout_date Date NOT NULL, period String(7) ("YYYY-MM", idx), method String(30)
(mpesa|bank|cash|other), reference String(100), notes Text, created_by_user_id FK users,
timestamps`. Model `OwnerPayout` + `to_dict`.

**Backend:** new `routes/owner_payout_routes.py` (blueprint prefix `/api/owner-payouts`):
CRUD (list w/ `?property_id=&period=`, create, update, delete), permission module: `payments`.
Audited. Registered in `app.py` like the other blueprints.

**Reports integration:** the property statement summary section gains a line
**"Remitted to owner (period)"** summing payouts for the property in the date range, and the
net-income roll-up shows `Net — Remitted = Retained`. (Purely informational — payouts are not
expenses and must NOT affect tax/expense math.)

**Frontend:** a "Owner payouts" tab/section in the landlord Reports or Payments area: table +
add/edit modal (property, period, amount, date, method, reference, notes).

### 1.5 Scale-proofing (performance)

1. **Seed script:** new `server/seed_scale.py` (mirrors `seed_production.py` conventions):
   creates ONE property-management landlord + **100 properties / 10 units each (1,000 units)** /
   **1,000 tenants** (one per unit; ~5% with multi-unit setups once Phase 5 lands) /
   **200 caretaker team members** (2 per 10 properties, preset caretaker) / **100 owner team
   members** (preset owner, one per property) / **6 months of billing + payments** driven through
   the real engine (`tasks.invoice_tasks._run_monthly_billing_for_tenant` + allocation service,
   exactly like `demo_service._seed_dataset` does). Runnable idempotently:
   `python seed_scale.py --wipe` recreates.
2. **Pagination audit:** every list endpoint must be server-paginated. `tenant_routes` already
   paginates; verify and fix `payment_routes`, `invoice_routes`, `expense_routes`,
   `communication_routes` (logs), `audit_routes`, `unit_routes`, admin lists. Default
   `per_page=20`, hard cap 100.
3. **N+1 sweep:** run the scale seed, hit each list endpoint with SQLAlchemy echo or
   `flask-sqlalchemy` record queries, and add `selectinload`/`joinedload` where a list endpoint
   issues > ~10 queries. Priority: tenants list (unit→property joins), payments list,
   invoices list, landlord dashboard (`landlord_dashboard_routes.py`), reports.
4. **Indexes:** confirm composite indexes exist for the hot paths; add if missing:
   `payments (landlord_id, payment_date)`, `invoices (landlord_id, issue_date)`,
   `invoices (tenant_id, status)`, `payment_allocations (invoice_id)`,
   `communication_logs (landlord_id, created_at)`, `audit_logs (landlord_id, created_at)`.
5. **Acceptance (measured against the scale seed, locally):** dashboard, tenants page 1,
   payments page 1, and a single property statement each return in **< 1s**; no list endpoint
   returns an unpaginated 1,000-row payload; team member scoped to 1 property sees only that
   property's data on every page.

---

## Phase 2 — Rent-only commission basis + per-property commission  *(SECOND PRIORITY)*

### Business context
Kenyan property managers may legally charge commission ONLY on rent collected — current month's
rent and rent arrears — never on rent deposits, and typically not on utilities either. Reports
must therefore support switching the **gross** between "everything collected" and "rent only",
and compute the commission line automatically.

### 2.1 Schema

- `properties.commission_rate` — `Numeric(5,2)`, nullable (percent, e.g. 10.00). Editable in the
  property create/edit form (landlord portal) and shown on `PropertyDetail`/admin. Add to `to_dict`.
- `landlord_settings.report_gross_basis` — `String(10)`, default `'all'`; allowed `'all' | 'rent_only'`.
  Exposed via the existing settings GET/PUT (`settings_routes.py`) and persisted from the reports UI.

### 2.2 Computation (single shared helper)

New `services/commission_service.py`:

```python
def collections_breakdown(landlord_id, property_id, date_from, date_to) -> dict:
    """
    Sums CONFIRMED payment allocations in the window, split into:
      rent_collected      — allocations to line items of the Rent category, subcategory in (current, balance)
      deposits_collected  — subcategory == 'deposit' (any category)
      other_collected     — everything else (utilities, penalties, custom)
    Excludes NON_CASH_PAYMENT_SOURCES (credit re-application) from cash figures,
    consistent with models.NON_CASH_PAYMENT_SOURCES.
    """
```

Rules: join `PaymentAllocation → Payment` (confirmed, not deleted, in range, property match) and
`PaymentAllocation → InvoiceLineItem` for category/subcategory. Use
`category_service.rent_category_id()` from Phase 0.

### 2.3 Report changes

All in `services/report_generators.py` (+ `payment_report_service.py` where relevant):

- **Property statement** (`build_property_statement`): accept `gross_basis` (query param
  `?gross_basis=all|rent_only`, defaulting to the landlord's saved setting). Summary section
  becomes, for `rent_only`:
  ```
  Gross — rent collected (current + arrears)        X
  Commission @ {commission_rate}%                  (Y)
  Other collections — not commissionable            Z   (info line)
  Deposits held — not income                        D   (info line)
  Expenses                                         (E)
  Tax @ rate                                       (T)
  Net income                                        N
  Remitted to owner (Phase 1.4)                    (R)
  Retained                                          N − R
  ```
  For `'all'` the current behaviour is preserved, with the commission line added when
  `commission_rate` is set (commission still computed on **rent only** — that is the legal rule —
  labelled "Commission @ r% of rent collected").
- **Month-on-month / Year-on-year / Grouping reports:** add the same `gross_basis` param; when
  `rent_only`, the "collected" metric per month/year/property uses `rent_collected` and the
  column header says "Rent collected" instead of "Total collected".
- The chosen basis is printed in the report meta/letterhead block so a printed report is
  self-describing.

### 2.4 Frontend

Reports pages (`client/src/features/landlord/reports/`): a "Gross basis" `select` (options:
"All collections", "Rent only — excl. deposits") shown on property statement, MoM, YoY, grouping.
On change: refetch with the param AND persist via settings PUT so it sticks (owner's decision).
Property form gains "Commission rate (%)" field with helper text "Commission is always computed
on rent collected only (current + arrears), never on deposits."

### 2.5 Tests

Pytest fixtures: tenant pays rent current 10,000 + rent balance 5,000 + deposit 15,000 + water
2,000 in the window; `commission_rate=10`. Assert: `rent_collected == 15000`,
commission == 1,500, deposits and water excluded; `gross_basis=all` unchanged legacy totals;
credit-source payments excluded from cash sums.

---

## Phase 3 — Security hardening  *(runs early; nothing later may regress it)*

### 3.1 Cross-portal isolation test suite (IDOR sweep) — the core deliverable

New `server/tests/test_access_control.py`, parametrised over EVERY registered route
(introspect `app.url_map`):

1. Build fixture users: system_admin, landlord A, landlord B, team member of A (viewer, one
   property), tenant of A, tenant of B, affiliate.
2. For each `/api` route (excluding auth/otp/public/webhooks), assert:
   - No token → 401.
   - A tenant token on any landlord/admin route → 403. A landlord token on any admin route → 403.
     A team token on any admin route → 403. An affiliate token on landlord/admin routes → 403.
   - **Cross-landlord object access:** for the ~20 highest-risk `<int:id>` routes (tenant detail,
     tenant transactions, invoice, payment, receipt, unit, property, expense, statement,
     documents, maintenance, messages, team member, owner payout), landlord B requesting
     landlord A's object id → 404/403, never data. Add explicit tests; do not rely on spot checks.
   - Tenant portal: tenant B's token can never fetch tenant A's dashboard/statement/receipts.
3. Fix every failure found. The historical bug class here is real (see commit d91fd5d — tenant
   OTP resolved to the wrong account), so treat every miss as a genuine defect.

### 3.2 Rate limiting & brute-force protection

- Add `Flask-Limiter` (storage: Redis, already required by Celery config): `/api/auth/login`
  5/min/IP + 20/hour/IP; `/api/otp/request` 3/min per identifier and 10/hour per identifier
  (the OtpToken docstring already demands this); `/api/otp/verify` 10/hour per identifier;
  password reset request 5/hour per email; global default 300/min/IP for `/api/*`.
- Account lockout: after 8 failed password attempts on one account within 15 min, lock 15 min
  (track in Redis, keyed by user id). Generic error message — do not reveal lock state precisely.
- OTP: `OtpToken.attempts` max 5 then invalidate token (verify this is enforced; fix if not).

### 3.3 Auth/JWT hardening

- Access token lifetime ≤ 1 hour; refresh token 30 days with rotation
  (`flask_jwt_extended` refresh flow) — check current `config.py` and implement refresh if the
  app currently issues long-lived access tokens. Frontend: silent refresh in the RTK Query
  baseQuery on 401-expired, one retry, then logout.
- On password change / reset: revoke outstanding refresh tokens (store a per-user
  `token_version` claim; bump on change).
- Password policy on registration/reset: min 8 chars incl. letter + number (server-side).
- Verify OTP codes remain hashed (they are — sha256), password hashing uses a strong scheme
  (check `utils.hash_password`; if it is not bcrypt/argon2, migrate to bcrypt with on-login rehash).

### 3.4 Admin 2FA (TOTP) — mandatory for system admins, optional for landlords

**Migration:** `users.totp_secret` (String(64), nullable, encrypted at rest using a Fernet key
from env `FIELD_ENCRYPTION_KEY`), `users.totp_enabled` (Boolean default False),
`users.totp_backup_codes` (Text JSON of 8 hashed one-time codes).

**Backend (`auth_routes.py` + new `routes/twofa_routes.py`):**
- `POST /api/auth/2fa/setup` → provisioning URI + QR payload (pyotp).
- `POST /api/auth/2fa/enable` → verify first code, enable, return backup codes (once).
- Login flow: when `totp_enabled`, `/login` returns `{"requires_2fa": true, "pre_auth_token": …}`
  (a 5-min JWT with a `pre_2fa` claim, usable ONLY on `/api/auth/2fa/verify`); verify returns the
  real tokens. Backup code accepted in place of TOTP, then invalidated.
- **Enforcement:** system_admin accounts cannot reach any `/api/admin/*` route until
  `totp_enabled` — return 403 `{"code": "2fa_required"}`; the admin frontend redirects to a
  mandatory setup screen. Landlords: optional toggle in Settings → Security.
- Rate-limit verify (5/min).

**Frontend:** setup screen (QR + confirm code + backup codes download) in admin portal and in
landlord Settings → Security; 2FA step on the login page.

### 3.5 Transport & headers (nginx — `deploy/nginx/sahilpay.conf`)

Add (keep existing headers):
```
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'" always;
```
Validate the CSP against the built app (fonts.googleapis.com is used in `client/index.html`;
adjust for any inline scripts Vite emits — prefer hashes over `'unsafe-inline'` for scripts).
Also: `server_tokens off;`.

### 3.6 Input/upload/webhook hardening

- **Uploads** (tenant documents, logos, signatures, bank statements, copilot APKs): enforce an
  extension + MIME allowlist and size caps server-side in `services/storage_service.py` (images:
  png/jpg/webp ≤ 5 MB; docs: pdf/png/jpg ≤ 10 MB; statements: pdf/csv/xlsx ≤ 20 MB). Never serve
  user uploads with a content-type sniffable as HTML. Randomised stored filenames (verify).
- **Daraja webhooks** (`routes/webhook_routes.py`, `mpesa_routes.py`): validate payload shape
  strictly, log + 200 on unknown shapes (Safaricom retries), enforce idempotency on
  `TransID`/`CheckoutRequestID` (unique constraint or get-or-create), and confirm amounts are
  parsed as Decimal. No auth bypass beyond these paths.
- **SQL:** ORM-only. `grep` for `text(` / raw f-string SQL outside `demo_service._wipe_landlord_scoped_rows`
  (parametrised — fine) and migrations; eliminate any interpolated SQL found.
- **Secrets:** verify `.env` files are gitignored and `deploy/server.env.production.example`
  contains no real values (the recent "credential hygiene" commit suggests history awareness —
  do not re-introduce). `LandlordSettings.sms_api_key` should be encrypted at rest with the same
  Fernet key as 3.4.

### 3.7 Dependency + platform audit

- `pip-audit` on `server/requirements.txt`, `npm audit` on `client/` — upgrade vulnerable
  packages (patch/minor only unless a critical requires more; note any breaking upgrade in the
  final report).
- Postgres: document (in `DEPLOY_RUNBOOK.md`) a least-privilege app role (no SUPERUSER/CREATEDB),
  `pg_hba` local-only, and a nightly `pg_dump` cron shipped off-box. Backups are configuration,
  not code — write the exact commands into the runbook.

### 3.8 Demo-mode write restrictions

Server-side blocks when the request is in demo scope (`utils.is_demo_scope()` — extend it or add
`require_not_demo()` decorator): SMS/email real dispatch (already simulated — additionally
return a clear `{"blocked": "demo"}` for bulk sends), SMS top-up purchase routes, billing/
subscription payment routes, team member invites, Copilot device registration, backup creation.
Return 403 `{"code": "demo_mode"}` and show a friendly toast in the UI.

### Acceptance
- The full access-control suite passes and runs in CI (add to whatever test entrypoint exists).
- Rate limits demonstrably fire (tests with limiter enabled).
- Admin cannot use the admin portal without TOTP.
- CSP live without console violations on all portals.

---

## Phase 4 — Tenant score

### 4.1 Definition (owner-approved)

Per tenant, per **fully elapsed** month from `move_in_date` (fallback `lease_start_date`,
fallback first invoice month) through last complete month:

1. Find the month's **rent-current** line items (Rent category, `subcategory='current'`) across
   that month's invoices (the `monthly` invoice primarily).
2. Determine the date rent became **fully paid**: the `payment_date` of the confirmed payment
   whose allocation brought cumulative `amount_paid` on those line items to ≥ the rent amount.
   (Credit-source allocations count as payment on the date applied.)
3. Month score by **day of month** rent was completed:
   - day 1–5 → 100 | 6–10 → 90 | 11–15 → 80 | 16–20 → 70 | 21–25 → 60 | 26–end → 50
   - completed in a LATER month, or still unpaid → **0** for that month.
4. **Tenant score** = mean of month scores, **minus 5 per month** (within the same window) that
   *ended* with an uncleared rent balance (`subcategory='balance'` outstanding at month end —
   derive from `BalanceRollover` rows for the Rent category), penalty capped at −20 total.
   Clamp to 0–100, round to integer.
5. Tenants with **< 2 fully elapsed months** of history → score is `null`, displayed as **"New"**.
6. Deposits and utilities never affect the score.

### 4.2 Implementation

- New `services/tenant_score_service.py`:
  - `compute_tenant_score(tenant) -> dict` returning
    `{score: int|None, months: [{month, rent_due, paid_on_day, band_score, had_arrears}], penalty, on_time_rate, avg_pay_day}`.
  - `refresh_tenant_score(tenant)` persisting to new columns.
- **Migration:** `tenants.tenant_score` (Integer, nullable), `tenants.tenant_score_updated_at`
  (DateTime, nullable). Add both to `Tenant.to_dict()`.
- **Refresh triggers:** (a) nightly Celery Beat task `refresh_all_tenant_scores` in
  `tasks/payment_tasks.py` (batch, non-demo landlords, chunked commits); (b) inline refresh for
  the affected tenant whenever a payment is confirmed/allocated (payment routes, webhook
  confirmation, copilot pipeline — one shared call site inside `apply_allocations` completion or
  immediately after each commit point).
- **Endpoints:** score included in every tenant list/detail `to_dict`;
  `GET /api/tenants/<id>/score` → full breakdown (permission `tenants` view);
  `GET /api/tenant-portal/score` → the tenant's own breakdown.

### 4.3 Display (all four portals)

Shared UI component `client/src/components/ui/TenantScoreBadge.jsx`: circular/pill badge —
≥ 90 green "Excellent", 75–89 lime "Good", 60–74 amber "Fair", 40–59 orange "Poor",
< 40 red "High risk", null → neutral gray "New".

- Landlord portal: tenants list column + tenant detail header + breakdown card (months table:
  month, paid day, band, arrears flag) on the tenant detail page.
- Team member portal: same (inherits landlord pages; visible with `tenants` view permission).
- Admin portal: `AdminTenants.jsx` list column + `TenantDetail.jsx`.
- Tenant portal: dashboard card "Your payment score" with the badge, `on_time_rate`,
  `avg_pay_day`, and one motivating line ("Pay by the 5th to keep your score at 100").

### 4.4 Tests
Fixtures: always-pays-day-3 tenant → 100; always-day-12 → 80; paid-next-month once → months
average includes a 0; arrears penalty applies and caps at 20; 1-month tenant → null; deposit
invoice ignored. Verify inline refresh fires on payment confirmation.

---

## Phase 5 — One tenant, multiple units

### Design (owner-approved)
Keep **one `Tenant` row per unit occupancy** (payment isolation by unique per-landlord
`account_number` stays intact — this is why payments can never mix up). Add an identity layer
so one human with one phone can hold several tenant rows, within one landlord or across many.
Invoices and payments remain strictly per unit; the tenant pays each unit's account separately.

### 5.1 Model change: User ↔ Tenant becomes 1:N

- `models.py`: change `User.tenant_profile` (uselist=False) → `User.tenant_profiles`
  (list). Grep EVERY use of `tenant_profile` (server: `utils.py`, `auth_routes.py`,
  `otp_routes.py`, `tenant_portal_routes.py:_get_portal_tenant`, `communication_service`, tests;
  none in client — it consumes APIs) and update deliberately. No schema change needed
  (`tenants.user_id` already supports many rows per user).
- **Linking rule:** when a tenant row is created/updated with a phone that exactly matches
  (normalised, `utils` phone normaliser) an existing tenant-role `User.phone`, set
  `tenant.user_id` to that user. When a tenant with no user logs in via OTP for the first time,
  the existing user-creation path must attach ALL tenant rows sharing that normalised phone
  (across landlords) to the new user. Write a one-off Alembic data migration that back-links
  existing same-phone tenant rows to the existing user where exactly one user matches.

### 5.2 Tenant portal: unit switcher

- `GET /api/tenant-portal/context` → `[{tenant_id, unit_name, property_name, landlord_company,
  account_number, balance}]` for all non-deleted tenant rows of the JWT user, ordered by landlord
  then property.
- Every existing tenant-portal endpoint accepts an optional `?tenant_id=` (or header
  `X-Tenant-Id`); `_get_portal_tenant()` validates the requested id **belongs to the JWT user**
  (else 403) and defaults to the first row. THIS VALIDATION IS SECURITY-CRITICAL — cover it in
  the Phase 3 access suite (tenant B's id with tenant A's token → 403).
- Frontend (`client/src/features/tenant/`): when context has > 1 row, render a unit switcher in
  the portal header — grouped by landlord company then property, per owner's requirement that
  units are "well separated and listed". All dashboard/invoices/payments/statement queries carry
  the selected `tenant_id`. Invoices/payment instructions always show THAT unit's account number
  and paybill.

### 5.3 Landlord + admin heads-up

- Tenant list/detail (landlord + team portals): badge "×N units" when the same normalised phone
  has N > 1 active tenant rows **within this landlord**, with a popover listing the sibling
  units (name + property + balance) and links.
- Admin `TenantDetail.jsx`: same badge but across ALL landlords (admin may see everything).
- Tenant create form: when the entered phone matches an existing active tenant of this landlord,
  show a non-blocking info banner: "This phone already belongs to [name] in [unit]. Adding them
  here gives one person two units — payments stay separate by account number." (No hard block.)
  Backend: remove/soften any duplicate-phone rejection within a landlord if one exists — verify.

### 5.4 Tests
User with 3 tenant rows across 2 landlords: context lists 3; switching returns the right
statements; OTP login binds all rows; cross-user tenant_id → 403; per-unit account numbers stay
unique per landlord (existing constraint `uq_tenants_landlord_account` untouched).

---

## Phase 6 — Admin fixed monthly price (custom package)

- **Migration:** `landlords.fixed_monthly_price` — `Numeric(12,2)`, nullable.
- **`services/billing_service.py`:**
  - `recompute_subscription`: if `landlord.fixed_monthly_price is not None` →
    `cost = fixed_monthly_price` (ignore unit count and `per_unit_price`), and assign the
    landlord to the `is_custom` package (create the "Custom" package row if absent — admin
    seeding may already have it). Unit-count changes never alter the cost.
  - `preview_subscription_cost`: when the landlord has a fixed price →
    `amount_due = fixed_monthly_price × months` with **NO cycle discount** (owner's decision:
    the negotiated price is final; return `discount = 0` regardless of cycle).
  - Price changes take effect at the **next** billing event: changing the field must NOT touch
    `amount_due` or `next_billing_date` on an already-issued cycle (the existing
    "auto-fill only when unset" behaviour already gives this — verify and test).
- **Admin UI:** `AdminLandlordBillingModal.jsx` gains "Fixed monthly price (KES)" with helper
  text "Overrides per-unit pricing entirely. No cycle discounts apply. Takes effect next billing
  cycle." Clearing the field reverts to per-unit/package pricing on next recompute. Audited
  (`record_audit` with before/after).
- **Landlord billing page:** shows "Custom plan — KES X / month (fixed)" and hides the
  per-unit×count math when fixed.
- **Tests:** fixed price wins over `per_unit_price` and package; quarterly/annual preview has no
  discount; clearing restores band pricing; `recompute_subscription` never mutates an in-flight
  `amount_due`.

---

## Phase 7 — Welcome message on tenant creation

- **Enum:** add `MessageTemplateType.welcome = "welcome"`.
- **Default template** (seeded per landlord on first use, editable in Message Templates; SMS
  channel; keep ≤ ~2 SMS segments, warm per the owner's explicit request):
  > Karibu {tenant_name}! 🎉 Welcome home to {unit_name}, {property_name}. We're truly glad to
  > have you with us. Rent is payable via Paybill {mpesa_number}, Account {account_number}.
  > Anything you need, call us on {landlord_phone}. Wishing you a wonderful stay! — {company_name}
  (Resolve variables through `services/message_variables.py`; add any missing placeholders
  there. Emoji: verify FluxSMS/UCS-2 handling — if a non-GSM7 char forces UCS-2 segment costs,
  drop the emoji from the default and note it.)
- **API:** `POST /api/tenants/` accepts `"send_welcome_message": true|false` (default false).
  After the tenant commit + `on_tenant_created` automation, when true and not demo scope:
  dispatch via `communication_service.dispatch_message` — SMS always (normal credit billing,
  respecting the balance gate), plus email copy when the tenant has an email (reuse the standard
  `render_email` shell: same content, heading "Welcome to {company_name}"). Log to
  `CommunicationLog`; failures must NOT roll back tenant creation (catch, log, surface
  `"welcome_message": "sent"|"failed"|"skipped"` in the 201 response).
- **Frontend:** checkbox in the Add Tenant form (landlord + team portals), label "Send a welcome
  message to this tenant", default UNCHECKED, with a small preview link showing the resolved
  template. Toast reflects sent/failed.
- **Tests:** flag off → no dispatch; on → SMS logged + credits decremented; no email address →
  SMS only; failure path returns 201 with `welcome_message: "failed"`.

---

## Phase 8 — Bulk tenant import wizard (migration tooling)

Owner does free setups from clients' Excel/PDF/photos/handwritten books. Workflow: owner
converts anything messy into the template (using Claude chat externally — NOT in-app), then
uploads. Build the wizard; no in-app AI.

### 8.1 Template
`GET /api/tenants/import/template` → generated `.xlsx` (openpyxl — already a dependency), one
sheet "Tenants", header row + 3 example rows + a "Notes" sheet documenting each column:

`property_name*, unit_name*, rent_amount*, first_name*, last_name*, phone*, email,
national_id, account_number, lease_start_date (YYYY-MM-DD), lease_expiry_date, move_in_date,
deposit_amount, deposit_paid, opening_balance (arrears brought forward, positive number),
credit_balance (advance held), notes`

### 8.2 Validate + commit endpoints (`routes/tenant_routes.py` or new `tenant_import_routes.py`)
- `POST /api/tenants/import/validate` (multipart xlsx/csv, ≤ 2,000 rows, permission `tenants`
  edit): parse, normalise phones, and return per-row
  `{row, data, errors: [...], warnings: [...], actions: {create_property, create_unit, duplicate_phone}}`.
  Errors (block commit): missing required field, bad date/number, duplicate `account_number`
  within landlord or within file, unit already occupied by a different active tenant.
  Warnings (allowed): new property/unit will be created, phone matches an existing tenant
  (multi-unit person — fine per Phase 5), missing account_number (one will be auto-generated —
  reuse whatever generation exists; if none, `<ABBR>-<seq>`).
- `POST /api/tenants/import/commit` (same payload revalidated server-side — never trust the
  client's validation): in ONE transaction per chunk of 100:
  1. Create missing properties (`number_of_units` = count from file, city = "-" placeholder
     flagged for later edit) and units (with `rent_amount`).
  2. Create tenants (+ `TenantUnitHistory`, `unit.is_occupied=True`) — same field handling as
     `create_tenant`.
  3. `opening_balance` > 0 → create an Invoice (`invoice_type='custom'`, title
     "Opening balance brought forward", issue_date = today) with ONE line item: Rent category,
     `subcategory='balance'`, amount = opening_balance; set `tenant.balance` accordingly
     (mirror how `demo_service` seeds the unpaid deposit — same pattern).
  4. `deposit_amount/deposit_paid` → stored on the tenant (held deposits; do NOT invoice paid
     deposits — record only), consistent with existing create-tenant semantics.
  5. `credit_balance` > 0 → `CreditLedger` entry + `tenant.credit_balance` (follow the invariant
     "credit_balance always equals the sum of the credit ledger", models.py §1.5 comment).
  6. One `record_audit` per import summarising counts; NO welcome messages from imports.
  Response: `{created_tenants, created_units, created_properties, skipped: [...]}`.

### 8.3 Frontend
Landlord portal → Tenants page → "Import" button → 3-step modal/page:
1. Upload (+ "Download template" link).
2. Review: editable grid of parsed rows, error rows highlighted red (inline-fixable), warning
   chips; footer summary "18 tenants · 2 new units · 1 new property".
3. Commit → progress → result summary with links.
Admin portal: when impersonating a landlord (existing impersonation flow), the same UI is
reachable — verify impersonation covers the new endpoints (it should automatically via
`get_current_landlord_id`).

### 8.4 Tests
Golden-file xlsx fixtures: happy path (creates property/unit/tenant/opening invoice/credit),
each error class blocks, duplicate account within file blocks, 2,001 rows rejected, commit is
idempotent-safe (re-uploading the same file → duplicate account_number errors, no double rows).

---

## Phase 9 — Receipt layout designer (component presets)

### 9.1 Storage
`landlord_settings.receipt_layout_json` — Text (JSON):
```json
{
  "paper": "a4 | a4_third_portrait | a4_third_landscape | thermal_80",
  "header_slots": {"left": "logo", "center": "letterhead", "right": "address"},
  "hidden_components": [],
  "density": "normal | compact",
  "font_scale": 1.0,
  "sections": {"deposits": true, "notes": true, "signature": true}
}
```
`header_slots` values are any permutation of `logo` / `letterhead` (company name + invoice
title) / `address` (PO box, location, phone, email); a slot may be `null`; components may be
hidden. Defaults (when the JSON is null) reproduce today's exact output — **backwards
compatible, zero migration risk for existing landlords**.

### 9.2 Renderer
`services/receipt_service.py` (+ the letterhead helpers it imports from `report_builder.py`):
- Parameterise the receipt HTML/CSS by the layout: `@page` size/margins per paper
  (a4_third_portrait = 99×210 mm; a4_third_landscape = 297×99 mm; thermal_80 = 80 mm wide,
  auto height — WeasyPrint supports custom `@page size`), header as a 3-column table driven by
  `header_slots`, `compact` density = reduced paddings/12px base font, `font_scale` multiplies
  base font sizes.
- Receipts ONLY — reports/invoices keep the shared letterhead untouched (owner's decision).
- `POST /api/receipts/preview` (landlord auth): body = a candidate layout JSON, renders a PDF
  with fixed sample data → used by the editor's live preview. `PUT /api/settings/receipt-layout`
  saves after server-side validation of every enum value.

### 9.3 Frontend
Landlord Settings → "Receipt layout" page: paper picker (visual cards with aspect-ratio
thumbnails), three header slot dropdowns with a live schematic, density + font scale controls,
section toggles, an embedded PDF preview (iframe of the preview endpoint response blob),
"Reset to default". Save → toast.

### 9.4 Tests
Renderer unit tests: each paper renders non-empty PDF; slot permutation is honoured (assert the
generated HTML string order); invalid JSON in the column falls back to defaults silently.

---

## Phase 10 — Demo-mode isolation (visibility + blocked features)

Diagnosis (verified in code): demo data intentionally lives in the real DB under a hidden shadow
landlord (`is_demo=True`, `demo_owner_landlord_id`); demo actions DO write real `audit_logs`
rows (prefixed `[DEMO]`, scoped to the shadow) and the seeding/billing engine acts as
"platform". The owner saw exactly this in the admin Master Audit Log. Data isolation is sound;
**visibility filtering is the bug.** Decisions: keep writing demo audit rows but hide them
everywhere; keep the persistent shadow + manual Reset (no auto-wipe on exit).

1. **Admin visibility sweep — exclude `is_demo` landlords (and their `landlord_id`s / user ids)
   from:** `routes/audit_routes.py` (master audit log — the reported bug), every list/metric in
   `admin_routes.py` (landlord counts, revenue, dashboards), `admin_billing_routes.py`,
   `admin_sms_routes.py`, `admin_pricing_routes.py` analytics, `pricing_analytics_service.py`,
   `sms_analytics_service.py`, affiliate metrics. Grep every `Landlord.query` /
   `join(Landlord)` in admin-facing code and add the filter. Add ONE helper
   `non_demo_landlords()` query-filter utility and use it consistently.
2. **Celery sweep:** `tasks/invoice_tasks.py` already filters `is_demo.is_(False)`; verify and
   fix ALL other tasks (`payment_tasks`, `communication_tasks`, `admin_tasks`, `backup_tasks`,
   `mpesa_reconciliation_tasks`, `sms_dlr_tasks`, the new Phase 1/4 tasks) exclude demo shadows.
3. **Blocked-in-demo actions** (server-side 403 `{"code":"demo_mode"}` + friendly UI toast; see
   Phase 3.8): real message dispatch beyond the simulated log, SMS top-ups, billing payments,
   team invites, Copilot registration, backups. Reports/printing remain allowed.
4. **UI:** persistent "DEMO MODE — nothing here is real" banner while `X-Demo-Mode` is active
   (verify `useDemoMode.js` already does this; make it unmissable), and demo-blocked buttons
   render disabled with a tooltip.
5. **Tests:** admin audit endpoint with a seeded shadow returns zero shadow rows; admin landlord
   count excludes shadows; each blocked route 403s in demo scope; monthly billing task skips
   shadows.

---

## Phase 11 — Email mobile responsiveness (invoice/reminder breakdown fix)

Owner's precise complaint: the **invoice email** breakdown is cramped — too much padding
relative to a phone screen, poorly spaced. Wanted: strictly layered rows — label, then amount
directly beneath, minimal padding, never side-by-side.

1. In `services/email_templates.py` add a purpose-built block (do NOT keep using
   `credentials()` for money breakdowns):
   ```python
   def breakdown(rows: list[tuple[str, str]], total: tuple[str, str] | None = None) -> str:
       """Layered charge list: label line (12px, muted) with the value on its own
       line directly below (16px, white, semibold); 6px vertical padding per pair,
       hairline separator between pairs only; total row visually distinct
       (top border, 17px). No side-by-side columns anywhere. Fits 320px."""
   ```
2. Switch every money/detail email to it: `reminder_content.py` (balance + invoice reminders —
   its `contact_rows`/amount rows), `email_service.send_invoice_email` /
   `send_receipt_email` / `send_statement_email` intro blocks, and the monthly-invoice dispatch
   path in `communication_service.dispatch_invoice`. Grep ALL `T.credentials(` call sites and
   convert the ones that show amounts (keep `credentials()` for login-credential emails, where
   it's appropriate).
3. Tighten the shell for small screens: card padding at < 480px to 18px/14px; verify the
   `.sp-*` media queries; keep dark theme but add `<meta name="supported-color-schemes">` and
   test light-forced rendering (Gmail).
4. **Verification (mandatory):** write a small script `server/tests/render_email_previews.py`
   that renders EVERY email builder to `scratch/emails/*.html`; open each at 320 px and 390 px
   viewport (Playwright) and screenshot; fix any horizontal scroll or cramped spacing found.
   Commit the script (not the screenshots).

---

## Phase 12 — SEO: sitemap.xml, robots.txt, meta, prerendering

The public site is client-rendered — Google currently sees an empty `<div id="root">`. Sitemap
alone is insufficient; ship all four:

1. **`client/public/robots.txt`:**
   ```
   User-agent: *
   Allow: /
   Disallow: /landlord
   Disallow: /admin
   Disallow: /tenant
   Disallow: /team
   Disallow: /affiliate/portal
   Sitemap: https://sahilpay.co.ke/sitemap.xml
   ```
   (Match the disallow paths to the actual route prefixes in `client/src/routes/AppRoutes.jsx`.)
2. **`client/public/sitemap.xml`:** static, hand-written — the public routes only (read them
   from `AppRoutes.jsx`; expected: `/`, `/features`, `/pricing`, `/about`, `/contact`, `/faq`,
   `/privacy-policy`, `/terms-of-service`, affiliate signup). Absolute URLs on
   `https://sahilpay.co.ke`, sensible `changefreq`/`priority`. Update whenever a public page is
   added (leave a comment in the file saying so).
3. **Per-page meta:** add `react-helmet-async`; every public page sets unique
   `<title>` / `<meta description>` / OpenGraph + Twitter tags / `<link rel="canonical">`.
   Source copy from the existing `client/src/features/public/content/seoContent.js`. Add JSON-LD:
   `SoftwareApplication` (+ `Offer`s from public pricing) on `/pricing`, `FAQPage` on `/faq`,
   `Organization` sitewide.
4. **Prerendering:** post-build script (`client/scripts/prerender.mjs`, wired as
   `npm run build && node scripts/prerender.mjs`): launch headless Chromium (Playwright is
   acceptable as a devDependency), render each public route from the built `dist/` via a local
   static server, and write `dist/<route>/index.html` snapshots with the helmet tags baked in.
   nginx `try_files $uri $uri/ /index.html` already serves directory index.html files before
   falling back — verify with `curl` that `/pricing` returns prerendered HTML containing the
   title tag while `/landlord/...` still falls back to the SPA shell.
5. **Runbook for the owner** (append to `DEPLOY_RUNBOOK.md`): create a Google Search Console
   property for `sahilpay.co.ke` (DNS TXT verification), submit `https://sahilpay.co.ke/sitemap.xml`,
   request indexing of `/`. Note: ranking for competitive terms needs content + backlinks over
   months; this work makes the site fully indexable and rich-result-eligible.

---

## Phase 13 — SMS pricing per landlord + sender-ID operations

The desired commercial model (confirmed with the owner) **already matches the code's model**:
every landlord — shared `SAHILPAY` sender or their own registered sender ID — buys SMS credits
from SahilPay at an admin-set KES price (owner buys wholesale at 0.40, resells at ~1.00). A
custom-sender landlord registers their sender ID under their own fluxsms.co.ke account, tops up
FluxSMS delivery credit directly with FluxSMS, and STILL pays SahilPay per SMS
(`SmsPricingConfig.custom_price_per_sms`); the admin links their API key + sender ID
(self-service in Settings or `PUT /api/admin/sms/landlords/<id>/provider`). Work remaining:

1. **Per-landlord price override.** Migration: `landlords.sms_price_override` —
   `Numeric(8,4)`, nullable. `sms_billing` price resolution becomes: landlord override →
   `SmsPricingConfig` (custom/default by path) → module fallback constants. Surface in the admin
   SMS management UI (`SmsManagement.jsx`): per-landlord price field + effective-price display.
   Landlord-facing price displays (settings, top-up modal) must show the effective price.
2. **Verify the balance gate** holds for BOTH paths (custom senders must also be blocked at 0
   credits — FLUXSMS spec G2 said they historically were not; confirm the fix landed, else fix).
3. **Ops runbook** (new section in `DEPLOY_RUNBOOK.md`, written for the owner): the exact
   click-path for onboarding a custom sender ID — landlord registers sender ID at fluxsms.co.ke
   (or owner assists), owner links key+sender in Admin → SMS → landlord, sets their per-SMS
   price, landlord buys credits via the normal top-up; margin math example (0.40 cost vs 1.00
   charged); what happens when their FluxSMS delivery balance runs dry (sends fail — the DLR/
   failure path should already surface this; verify a failed provider send does NOT decrement
   SahilPay credits, per FLUXSMS spec).
4. **Tests:** override beats global config; effective price shown by the settings GET; zero
   balance blocks custom-path send; failed send doesn't bill.

---

## Phase 14 — Explicitly deferred (do NOT implement)

- **`app.sahilpay.co.ke` split:** deferred. The M-Pesa C2B URLs are registered against
  `https://sahilpay.co.ke/api/...` and cannot move; a split adds auth/CORS/cookie complexity for
  minimal present benefit. Revisit when the marketing site becomes a separate build. Leave a
  short note in `DEPLOYMENT_GUIDE.md` describing the future shape (marketing on root, app on
  `app.`, API stays on root `/api`).
- **One-payment auto-split across a tenant's multiple units:** deferred (risk to M-Pesa account
  matching). Tenants pay per unit account number.
- **In-app AI extraction of handwritten/photo tenant lists:** deferred; the import template +
  external Claude chat is the workflow.
- **Team-member seat pricing:** team members are unlimited and free on all packages. Make sure
  nothing bills or limits by team-member count, and the public pricing copy says so.

---

## Appendix A — Cloudflare migration runbook (owner-facing; write into DEPLOY_RUNBOOK.md, polished)

To be executed by the owner AFTER all phases are deployed. Free plan; no cost. Total active time
~30 minutes; propagation up to 24 h (typically < 1 h); zero expected downtime if TLS mode is set
BEFORE switching nameservers.

1. Create a free Cloudflare account → "Add a site" → `sahilpay.co.ke` → Free plan.
2. Cloudflare auto-imports DNS records. Verify the A record(s) for `sahilpay.co.ke` and `www`
   point at the server IP and are set to **Proxied** (orange cloud).
3. **Before changing nameservers:** SSL/TLS → set encryption mode **Full (strict)** (the origin
   already has a valid certbot certificate — this avoids redirect loops and keeps traffic
   encrypted end-to-end).
4. Create a WAF exception so Safaricom is never challenged:
   Security → WAF → Custom rules → "Skip" rule: `URI Path starts with /api/webhooks/` →
   Skip: Bot Fight Mode, Managed Challenge, Browser Integrity Check.
5. Enable: Bot Fight Mode (Security → Bots), "Under Attack" mode only during an actual attack,
   Speed → Auto Minify OFF (Vite already minifies; avoid double-processing), Caching → Standard.
6. At the DOMAIN REGISTRAR (wherever sahilpay.co.ke is registered — KeNIC registrar panel):
   replace the two nameservers with the pair Cloudflare displays. Save.
7. Wait for Cloudflare to email "site is active" (minutes–24 h). During propagation both paths
   work; nothing goes down.
8. Verify: site loads, `curl -I https://sahilpay.co.ke` shows `server: cloudflare`; make a test
   M-Pesa payment end-to-end to confirm the Daraja callback still lands (watch
   `daraja_callback_logs`).
9. Rollback (if anything misbehaves): restore the original nameservers at the registrar —
   nothing on the server changed.

## Appendix B — Final report Opus must produce

On completion, write `OPUS_EXECUTION_REPORT.md` at repo root: per phase — what shipped, files
touched, migrations added, test results (paste the pytest summary), anything intentionally
deviated from this spec and why, and any discovered pre-existing bugs fixed along the way
(list each). Fable will then run an independent Playwright walkthrough against the scale seed
(`server/seed_scale.py`) covering all four portals before the owner deploys.
