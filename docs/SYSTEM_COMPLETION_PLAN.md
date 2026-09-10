# SahilPay — System Completion & Verification Plan

> A phased roadmap to take SahilPay from "boots and logs in" to "every portal, every
> CRUD action, reports, audit, impersonation, and in-app notifications work end-to-end
> against real PostgreSQL data."
>
> **How to use this document:** each phase is self-contained and leaves the system in a
> working, testable state. Execute them **in order** — later phases depend on the data
> and fixes from earlier ones. To run a phase, hand it back as *"Do Phase N"* and it will
> be executed task-by-task with verification at the end.
>
> Generated 2026-06-26. Branch: `backend-set-up`.

---

## Legend

- 🟢 **Exists & verified** — confirmed working against the live stack.
- 🟡 **Exists, unverified / partially broken** — code is there; needs testing and likely fixes.
- 🔴 **Net-new** — does not exist; must be built from scratch.
- 🧪 **Verify** — a concrete check (curl + `psql`, or a UI click-through) proving real DB data.

---

## What is already fixed (this debugging arc, for the record)

These are done — listed so nothing is re-done:

1. `config.py` — `_normalize_db_url` mis-call; added `127.0.0.1` CORS origins.
2. Missing packages installed (boto3, cloudinary, marshmallow-sqlalchemy, openpyxl, requests).
3. `models.py` — Expense/MaintenanceRequest relationship conflict.
4. `extensions.py` — `Base.query` via `query_property()`.
5. `billing_routes.py` — wrong enum (`BillingCycle` → `SubscriptionPlan`).
6. JWT identity loader handles string identities (login was failing).
7. `SoftDeleteQuery.paginate()` implemented (list endpoints were 500ing).
8. **Audit-log commit-order bug** — 22 route files called `commit()` *before* `record_audit()`, silently dropping every audit row. Fixed across all of them.
9. Auth response-shape mismatches — `Login.jsx`, `AuthContext.jsx`, `TenantOtpLogin.jsx` read a `{user}` envelope that doesn't exist. Fixed; `/me` now also emits team-member `permissions` + `property_access`.
10. `CELERY_TASK_ALWAYS_EAGER=True` in dev so `.delay()` tasks (OTP, invoices, exports) run inline — no worker terminal needed.
11. `otp_tokens.code` widened `VARCHAR(10)` → `VARCHAR(64)` (stores a sha256 hash).
12. Dev logging lowered to `INFO` so the OTP stub line is visible in the backend terminal.
13. Impersonation request modal now sends the required `reason` field.

---

## Honest scope note

This plan spans **verify-and-fix** work (fast) and **net-new builds** (slow). The single
largest item is the **in-app notification system (Phase 8)** — it does not exist at all and
is a full-stack feature (model + migration + routes + templates + four portal UIs).
Third-party integrations (SMS, email, S3, M-Pesa) remain **log-stubs** until real
credentials are added to `server/.env`; every phase below is designed to be fully
testable **without** those credentials.

---

## Phase 0 — Baseline lock-in  🟢 (≈15 min)

**Goal:** confirm the stack is green before building on it, and snapshot a clean DB.

1. 🧪 `pg_isready && redis-cli ping && curl -s localhost:5000/api/health`
2. 🧪 Run the existing test login flow for all four roles (admin/landlord/team/tenant-OTP),
   confirm each returns tokens and `/me` hydrates the right role.
3. Run `flask db upgrade` to confirm migrations are current; commit the working tree so
   there's a clean rollback point before the big changes.

**Exit criteria:** all three services healthy; four-role login confirmed; git committed.

---

## Phase 1 — Extensive seed data  🟡→🟢 (foundation; do FIRST)

**Why first:** every single one of your requirements — *"data in each portal must be real
DB data relating to that individual"* — is untestable without rich, realistic, multi-entity
data. The current `seed.py` is a **single-landlord vertical slice** (1 landlord, 1 property,
3 units, 2 tenants). We replace it with a broad dataset.

**Build a new `seed.py` that creates:**

- **Platform:** global `TrialConfig`, 3 `Package` tiers (already present), plus 1 expired-trial
  landlord and 1 paying landlord so admin filters have variety.
- **3–4 landlords**, each with distinct `LandlordSettings` / `AutomationSettings` /
  `Subscription` (one on trial, one active-paid, one suspended, one near-expiry).
- **Per landlord:** 2–3 properties (one grouped under a `PropertyGroup`), 4–8 units each
  with a realistic mix of occupied/vacant.
- **Tenants:** 1 per occupied unit, with `TenantUnitHistory`; include at least one
  **moved-out** tenant and one **soft-deleted** tenant per landlord (so "deleted tenants"
  report + shifting flows have data).
- **Financial loop (the important part for reports):** for each tenant generate several
  months of `Invoice` rows (rent + a utility + an occasional penalty), matching
  `InvoiceLineItem`s, and `Payment` + `PaymentAllocation` rows so that:
  - some tenants are **fully paid**, some in **arrears** (negative balance), some in
    **advance** (credit). This makes arrears/statement reports meaningful.
  - running balances on `Tenant.balance` reconcile exactly with invoices − allocations.
- **Operations:** `UtilityReading`s across months, `Expense`s (several categories incl.
  recurring), `MaintenanceRequest`s in varied statuses, `MessageTemplate`s.
- **Team members:** 2 per landlord with *different* permission matrices (one editor with
  full access, one viewer scoped to a single property) so permission-gating is visibly testable.
- **Billing history:** `BillingTransaction` rows (subscription payments + SMS purchases)
  so the admin/landlord billing views and tax-invoice flow have data.
- **Audit + (after Phase 8) notifications** seeded with a few historical rows.

**Keep it idempotent** (the current `_get_or_create` pattern) so it's safe to re-run.

🧪 **Verify:** after `python seed.py`, run a `psql` row-count summary
(`SELECT count(*) FROM <table>`) for the 15 core tables and confirm non-trivial counts;
print a credentials table for every seeded login (all roles, all landlords).

**Exit criteria:** one command (`python seed.py`) produces a database rich enough that
every later phase has real data to display, and prints every login you'll use to test.

---

## Phase 2 — System Admin portal  🟡 (verify + fix)

**Pages:** `AdminDashboard`, `LandlordsManagement`, `LandlordDetail`, `PricingPackages`,
`TrialConfig`, `MasterAuditLogs` (Impersonation handled in Phase 3).

For **each page**, click every button and confirm the result is real DB data:

1. **Dashboard** (`GET /api/admin/dashboard`) — 🧪 cross-check the platform totals
   (landlord count, MRR, units, trials) against `psql` aggregates.
2. **Landlords management** (`GET /api/admin/landlords`) — list, filter, paginate; 🧪
   confirm rows match `landlords` table. Open a landlord → `LandlordDetail`.
3. **Suspend / reactivate** (`POST …/suspend`, `…/reactivate`) — 🧪 confirm `is_active`
   flips in DB **and** an `audit_logs` row is written (actor = admin).
4. **Data correction** (`POST /api/admin/correct-data`) — confirm the audited-change flow.
5. **Pricing & packages** (`admin_pricing_routes`) — **CRUD a Package** (create/edit/delete)
   and set a landlord's per-unit price; 🧪 confirm `packages` / `landlords.per_unit_price`.
6. **Trial config** (`admin_trial_routes`) — edit global trial; override one landlord's trial;
   🧪 confirm `trial_config` + landlord trial fields.
7. **Master audit log** (`GET /api/admin/audit`) — 🧪 confirm it shows rows from **all**
   landlords; test the **revert** action and confirm it both reverts and logs.

**Likely fixes:** response-shape mismatches (same class as the auth bug — frontend reading
keys the route doesn't send), pagination params, and any 🟡 button wired to a missing field.

**Exit criteria:** every admin page renders real data; every button's effect is visible in
`psql`; every mutating admin action writes an audit row.

---

## Phase 3 — Consent-based impersonation  🟡 (finish the wiring)

**What exists:** admin `request`/`list`/`revoke`; landlord `pending`/`grant`/`deny`;
`ImpersonationRequests.jsx` (landlord), `Impersonation.jsx` (admin), `ImpersonationBanner.jsx`;
`utils.active_impersonation()` + `current_landlord_id()` resolve the impersonated scope from a
request header.

**What's incomplete / to fix:**

1. **Header application** — `apiSlice.js` `prepareHeaders` only sets `Authorization`. The
   client never sends the impersonation header the backend reads, so a granted session is
   never actually *used*. Wire the client to send it once impersonation is active.
2. **Session hydration** — `AuthContext` reads `data.impersonating` from `/me`, but `/me`
   doesn't emit it. Either have `/me` report active impersonation, or store the granted
   landlord in client state when entering a session, so `ImpersonationBanner` shows.
3. **Enter / exit session UX** — confirm the admin can *enter* a granted account, the banner
   shows "acting as <landlord>", scoped data loads, and *exit* returns to admin scope.

🧪 **Verify the full consent loop end-to-end:**
admin requests (with reason) → landlord sees pending → landlord grants → admin enters →
admin creates e.g. a property → 🧪 `psql` shows the property under the **impersonated
landlord** and an `audit_logs` row with **actor = admin**, description noting impersonation →
admin exits → landlord revokes.

**Exit criteria:** the documented consent flow works in the UI, scoped to the right
landlord, fully audit-trailed with the admin as actor.

---

## Phase 4 — Landlord portal  🟡 (verify + fix, broad CRUD)

The largest portal. For each area: do the full CRUD and confirm DB + audit.

- **Properties** — create / edit / soft-delete; 🟢 create verified already. 🧪 each writes audit.
- **Units** — add single + bulk; rent, occupancy. 🧪 unique-name enforcement.
- **Tenants** — add; **shift tenant** between units (writes `TenantUnitHistory`,
  flips `Unit.is_occupied`); soft-delete; 🧪 confirm history + occupancy transitions.
- **Invoices** — create manual invoice; bulk-generate rent/recurring/penalty/utility
  (Celery-eager, runs inline); 🧪 confirm invoices + line items + tenant balance bump.
- **Payments** — record payment; allocate to invoice(s); 🧪 confirm `Payment`,
  `PaymentAllocation`, invoice status → paid/partial, tenant balance reconciles.
- **Expenses** — CRUD incl. recurring templates; link an expense to a maintenance request.
- **Utilities** — readings CRUD; generate utility invoices from readings.
- **Maintenance** — CRUD; status transitions; convert to expense.
- **Settings** — general/automation/mpesa; team management (invite/activate/permissions);
  message + document templates.
- **Billing** — pay subscription, buy SMS, transactions list, tax-invoice PDF.

🧪 **Data-isolation check (critical):** log in as Landlord A and confirm you **cannot** see
Landlord B's properties/tenants/invoices via list endpoints or by guessing IDs
(`landlord_id` row-level scoping). This is the heart of *"data relates to that individual."*

**Exit criteria:** every landlord CRUD action persists, reconciles financially, writes
audit, and is strictly scoped to the logged-in landlord.

---

## Phase 5 — Team Member portal  🟡 (permission enforcement)

**Goal:** prove the permission matrix actually gates the UI **and** the API.

1. Log in as the **full-access editor** team member → confirm all permitted modules load
   real data scoped to the parent landlord.
2. Log in as the **property-scoped viewer** → confirm:
   - hidden modules don't render in nav (`buildVisibleNav`),
   - view-only modules show data but edit/delete controls are disabled/absent,
   - 🧪 a direct `curl` to an unpermitted endpoint with the viewer's token is **rejected by
     the backend** (defense in depth — UI gating alone isn't security).
3. Confirm property-access scoping: the viewer sees only their assigned property's data.

**Exit criteria:** team-member permissions are enforced on both client and server; scoped
data only.

---

## Phase 6 — Tenant portal  🟡 (self-service, own data only)

1. OTP login 🟢 (working; code prints in backend terminal).
2. Tenant dashboard — 🧪 shows **only their own** invoices, payments, balance, statements,
   maintenance. Confirm via `psql` that no other tenant's data leaks.
3. **Make a payment** (tenant-initiated) → confirm `Payment`/allocation + balance update.
4. **Raise a maintenance request** → confirm row created, visible to the landlord in Phase 4.
5. Download own statement PDF.

**Exit criteria:** tenant sees and acts on only their own records; actions surface correctly
in the landlord portal.

---

## Phase 7 — Reports & financial accuracy  🟡 (the ledger must be exact)

**Endpoints present:** tenant statement, property statement, arrears, expenses, MoM, YoY,
grouping, deleted-tenants, insights, occupancy.

For each report:

1. Generate it from the UI for a landlord with rich seed data.
2. 🧪 **Reconcile every figure against a hand-computed `psql` query.** Reports are financial
   records — a statement's closing balance must equal Σ invoices − Σ allocations for that
   tenant; arrears must equal Σ negative balances; expense totals must match the
   `expenses` table for the period; MoM/YoY must tie out month over month.
3. Confirm PDF and Excel exports render with correct, detailed line-item breakdowns.
4. Add any missing detail the reports need to be "very detailed and accurate" (per-line
   items, running balances, date ranges, property/unit grouping).

**Exit criteria:** every report's numbers provably match the database ledger; exports are
detailed and correct.

---

## Phase 8 — In-app notification system  🔴 NET-NEW (the big build)

> Nothing here exists yet. This is a full-stack feature. Build in this order so each step is
> testable.

**8a. Data model + migration**
- `Notification` table: `id, recipient_user_id (FK), landlord_id (nullable, for scoping),
  sender_user_id, audience_role, title, body, category/template_key, is_read, read_at,
  created_at`, plus optional `link`/`entity_type`/`entity_id` for deep-links.
- Optionally a `NotificationTemplate` table (or a Python template registry) for the
  "specific templates per user situation" requirement (e.g. *trial expiring*, *payment
  received*, *new maintenance*, *lease expiring*, *custom broadcast*).
- `flask db migrate` + `upgrade`.

**8b. Backend routes (`routes/notification_routes.py`)**
- `GET /api/notifications` — current user's notifications (paginated, unread-first).
- `GET /api/notifications/unread-count` — for the navbar bell badge.
- `POST /api/notifications/<id>/read` and `POST /api/notifications/read-all`.
- **Admin/landlord send** `POST /api/notifications/send` with **audience filters**:
  by role (all tenants / all landlords / all team members), by specific landlord, by
  specific property's tenants, by a single user — plus a `template_key` to pre-fill
  title/body. Fan-out creates one `Notification` row per resolved recipient.
- Authorization: system admin can target anyone; a landlord can target only *their own*
  tenants/team. Every send writes an audit row.

**8c. Notification creation hooks (the "current situation" templates)**
- Fire notifications from existing events so dashboards populate organically: payment
  received → tenant; new maintenance → landlord; trial expiring → landlord (Beat task);
  team activation → team member; impersonation granted → admin.

**8d. Frontend — shared**
- RTK Query `notificationApiSlice` (list, unread-count, mark-read, send).
- Navbar **bell** (currently a static icon in `LandlordNavbar`/`TeamMemberNavbar`) → live
  unread badge + dropdown.
- A **Notifications page/tab** in **all four** portal shells (admin, landlord, team, tenant):
  list, open to read (marks read), filter by read/unread/category.

**8e. Frontend — sender UI**
- System-admin **"Send notification"** screen: pick audience (role / landlord / property /
  individual), pick a template or write custom, preview, send.
- Landlord version scoped to their tenants/team.

🧪 **Verify:** as admin, send a templated notification to "all tenants of Landlord A" →
log in as one of those tenants → the notification appears in their bell + Notifications tab →
open it → 🧪 `is_read` flips in DB. Repeat targeting landlords and team members.

**Exit criteria:** admin (and landlord, scoped) can broadcast templated, filtered in-app
notifications that land in the correct users' dashboards, are readable, and track read state.

---

## Phase 9 — Audit coverage + full regression  🟡 (lock it down)

1. **Audit completeness sweep:** confirm *every* mutating endpoint across all portals writes
   an `audit_logs` row (the commit-order class of bug is fixed, but verify coverage —
   especially newer notification sends and any endpoint missed). 🧪 spot-check each entity type.
2. **Audit views:** confirm the **landlord** audit view shows only their scope, and the
   **system-admin** master audit shows everything, with working filters and revert.
3. **Full four-portal regression:** one scripted pass — admin → impersonation → landlord
   CRUD → team-member gating → tenant self-service → reports → notifications — confirming no
   regressions and all data ties to the database.
4. Update `seed.py` if any new tables (notifications/templates) should be pre-populated.

**Exit criteria:** complete, scoped audit trails; a clean end-to-end regression across every
portal with all data provably sourced from PostgreSQL.

---

## Suggested execution order & rough effort

| Phase | Title | Type | Rough size |
|------:|-------|------|-----------|
| 0 | Baseline lock-in | verify | XS |
| 1 | Extensive seed data | rewrite | M |
| 2 | System Admin portal | verify+fix | M |
| 3 | Impersonation wiring | fix | S–M |
| 4 | Landlord portal CRUD | verify+fix | L |
| 5 | Team Member permissions | verify+fix | S–M |
| 6 | Tenant portal | verify+fix | S–M |
| 7 | Reports & financial accuracy | verify+fix | M |
| 8 | In-app notifications | **net-new** | **XL** |
| 9 | Audit coverage + regression | verify | M |

**Recommended next step:** start with **Phase 1** (extensive seed) — it unblocks the
realistic testing every other phase depends on. Then proceed in order.

> To execute, hand back: *"Do Phase 1"* (or any phase). Each will be done task-by-task with
> `psql`/curl verification and a short report at the end before moving on.
