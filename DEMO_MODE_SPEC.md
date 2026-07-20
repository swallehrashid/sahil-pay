# DEMO MODE — Implementation Spec

**Status:** Approved by owner 2026-07-08. Branch: `backend-set-up`.
**Goal:** A landlord can toggle "Demo mode" (with confirmation), and their entire
portal fills with realistic example data — 3 properties → units → tenants →
invoices → payments → utilities → reports. Everything is fully interactive, but
nothing they do touches their real account. A persistent, non-dismissible banner
reminds them they are in demo mode at all times. Exiting returns them to their
real (possibly empty) account so they can repeat what they practiced.

---

## 1. Architecture decision (approved — do not deviate)

**Demo mode = a hidden "shadow" demo landlord per real landlord**, entered via a
request header, exactly like the existing impersonation feature.

Why this and not alternatives (recorded for posterity):

- `server/utils.py::current_landlord_id()` (~line 285) is **the single
  chokepoint** every landlord-scoped query uses. Swapping the id it returns
  swaps the entire portal's data — every route, every report, every future
  feature, with zero per-feature work. Impersonation already proves this works
  (`X-Impersonate-Landlord` header → resolver → scoped queries).
- Frontend mocks were rejected (every new endpoint would silently break demo).
- `is_demo` flags on every row were rejected (hundreds of queries to touch; one
  missed filter leaks demo rows into real reports/billing).

Other approved decisions:

| Decision | Choice |
|---|---|
| Toggle location | Sidebar footer control **and** mirrored card in Settings → General |
| Data lifecycle | Demo data **persists** across enter/exit; explicit **"Reset demo data"** action wipes + reseeds |
| Blocked in demo | All outbound comms forced to simulation; account-level pages blocked (billing, account settings, team, M-Pesa, impersonation grants, backups, SMS provider, Co-pilot) |
| Who can use it | `landlord` / `property_manager` roles only. Team members: header ignored (v1). Admins impersonating: header ignored |

---

## 2. Data model (additive migration)

Add to `Landlord` (`server/models.py`):

```python
is_demo                 = Column(Boolean, default=False, nullable=False, index=True)
demo_owner_landlord_id  = Column(Integer, ForeignKey("landlords.id"), nullable=True, unique=True, index=True)
demo_created_at         = Column(DateTime, nullable=True)
demo_last_reset_at      = Column(DateTime, nullable=True)
```

- `demo_owner_landlord_id` points from the **shadow** landlord to the **real**
  landlord. `unique=True` ⇒ at most one shadow per real landlord.
- Self-referential relationship: `demo_shadow = relationship("Landlord", uselist=False, remote_side=..., ...)` —
  or simply query `Landlord.query.filter_by(demo_owner_landlord_id=real_id)`;
  a relationship is optional, a query helper in demo_service is enough.
- Alembic migration: purely additive (2 bools/datetimes + 1 FK). Follow the
  existing migration chain on this branch (latest head is `e4f5a6b7c8d9`).

**Stub user requirement:** `Landlord.user_id` is `NOT NULL UNIQUE`, so the
shadow landlord needs its own `User` row. Create it as:
`email = f"demo+{real_landlord.id}@sahilpay.demo"`, `role="landlord"`,
`is_active=False`, `is_verified=True`, random unguessable password hash.
`is_active=False` guarantees it can never log in (verify the login route checks
`is_active`; it does — mirror how `seed.py::_create_user` builds users).

---

## 3. Backend

### 3.1 Resolver hook — `server/utils.py::current_landlord_id()`

This is the heart of the feature. Insert demo resolution **after** the
landlord/PM branch resolves their own id:

```python
if role in ("landlord", "property_manager"):
    if user.landlord_profile is None:
        raise ApiError("Landlord profile not found.", status=500)
    real_id = user.landlord_profile.id
    return _demo_scope_or(real_id)          # NEW
```

```python
def _demo_scope_or(real_id: int) -> int:
    """If the caller sent X-Demo-Mode and a demo shadow exists, scope to it."""
    if request.headers.get("X-Demo-Mode") != "1":
        return real_id
    shadow = Landlord.query.filter_by(demo_owner_landlord_id=real_id).first()
    return shadow.id if shadow else real_id   # header w/o shadow ⇒ silently real
```

Rules:
- Impersonation resolution stays **first** and demo is NOT applied on the
  impersonation path (admin impersonating + demo header ⇒ demo header ignored).
- Team-member branch: demo header ignored (v1).
- Falling back to `real_id` when no shadow exists is deliberate: the frontend
  must call `POST /api/demo/enter` before setting the header, so this is only a
  stale-localStorage safety net, never an error.

Also add `utils.is_demo_scope() -> bool` (header present AND shadow resolved)
for routes/services that need to know (audit description prefix — see §3.5).

### 3.2 New blueprint — `server/routes/demo_routes.py`, prefix `/api/demo`

Register in `routes/__init__.py`. All endpoints `@jwt_required()` +
`require_role("landlord", "property_manager")`. **These routes always resolve
the REAL landlord** (read `user.landlord_profile.id` directly — do NOT go
through the demo-aware resolver).

| Endpoint | Behaviour |
|---|---|
| `GET /api/demo/status` | `{ "exists": bool, "created_at": ..., "last_reset_at": ... }` |
| `POST /api/demo/enter` | Idempotent. If no shadow: create stub user + shadow landlord + seed dataset (§4), commit. Returns `{ "ready": true }`. Audit on the REAL landlord: `demo_mode_entered`. |
| `POST /api/demo/exit` | Audit-only on the REAL landlord: `demo_mode_exited`. Returns `{ "ok": true }`. |
| `POST /api/demo/reset` | 404 if no shadow. Wipe all shadow-scoped rows (§4.3) + reseed + stamp `demo_last_reset_at`. Audit `demo_mode_reset` on the REAL landlord. |

Seeding takes a few seconds — that's fine synchronously (backup generation is
already synchronous); frontend shows a loading state in the confirm modal.

### 3.3 Outbound-send hard block (server-side safety, layer 1)

In `services/communication_service.dispatch_message` (and any other provider
dispatch path used by alert_service / automation_service — they all funnel
through communication_service; verify): before dispatch, if the scoped
landlord's `is_demo` is true, **force the simulation path** regardless of
`COMMS_SIMULATION_MODE`. Messages still get logged/delivered-in-DB so the
comms page works realistically in demo — nothing ever reaches Africa's Talking
/ SendGrid. Layer 2: all demo tenants/users get obviously fake phone numbers
(`+2547000000xx`) and `@sahilpay.demo` emails (§4.2).

Give the shadow landlord `sms_balance = 500` at seed time so SMS sending
"works" during training.

### 3.4 Exclude demo landlords everywhere the platform enumerates landlords

Sweep for `Landlord.query` and add `filter(Landlord.is_demo.is_(False))`:

1. `routes/admin_routes.py:73` (landlord list), `:87` (`total_landlords` count),
   `:146` (joined list) — and any other admin listing/analytics in that file or
   `admin_*_routes.py` that counts or lists landlords (do a full grep sweep:
   revenue rollups, SMS analytics, affiliate attribution, package distribution).
2. `tasks/invoice_tasks.py:337` `run_monthly_billing_all()` — skip demo
   landlords (scheduled billing must not churn demo data overnight).
3. `services/billing_service.recompute_subscription` — early-return no-op when
   `landlord.is_demo` (the shadow must never get a Subscription/amount_due).
4. Any other scheduled task that iterates all landlords
   (`automation_service.run_monthly_reminders` / `run_lease_expiry_notices`
   run per-landlord from settings — verify how they enumerate; if they iterate
   all landlords, skip demo ones; the in-demo "Run now" button path SHOULD
   still work since it's scoped).
5. Public/tenant-facing: demo tenants must not be reachable from the public pay
   page or tenant OTP login — enforced by fake phone numbers + no active tenant
   user rows (§4.2) + a guard in the public tenant-lookup route:
   if the resolved tenant's landlord `is_demo` → 404.

### 3.5 Audit trail

Writes inside demo scope land on the **shadow** landlord's audit trail (fully
isolated — this is correct and useful: the landlord can practice reading the
audit trail too). Additionally, prefix descriptions with `[DEMO] ` at the same
chokepoints impersonation uses (`utils.audit()` and
`services/audit_service.record_audit()`) when `is_demo_scope()` — cheap
insurance if a row is ever eyeballed in the DB.

---

## 4. Demo dataset — `server/services/demo_service.py` (new)

Public API:

```python
def ensure_demo_landlord(real_landlord) -> Landlord   # create+seed if absent, return shadow
def reset_demo_data(real_landlord) -> Landlord        # wipe + reseed
def get_demo_shadow(real_landlord_id) -> Landlord | None
```

### 4.1 Content (compact but hits every feature)

Model it on `seed.py::_seed_category_demo` (~line 973): **drive the real
engine**, do not hand-write ledger rows. Use `services/category_service.seed_default_categories`,
`services/allocation_service`, and `tasks/invoice_tasks._run_monthly_billing_for_tenant`
across 3 months ending at the current month, so rollover/credit/allocation/
statement data is production-identical. Do NOT import from `seed.py` (it's a
dev script that truncates tables) — copy the small builder patterns you need
into demo_service.

- **Shadow landlord fields:** `company_name = f"{real.company_name} (Demo)"`
  (fallback "Demo Properties Ltd"), copy `currency`/`timezone` from the real
  landlord, `is_on_trial=False`, `package_id=None`, `sms_balance=500`,
  `is_demo=True`, `demo_owner_landlord_id=real.id`.
- **3 properties:** e.g. "Sunrise Apartments" (8 units, 2 vacant),
  "Green Court" (4 units, 1 vacant), "Palm Villas" (3 units, all occupied).
  One property group containing two of them (so grouping reports have data).
- **~12 tenants** across the occupied units with varied, teachable scenarios:
  - several fully paid up (auto-allocated payments),
  - one partial payer with a rent **balance b/f** (rollover trail exists),
  - one overpayer whose **credit** was consumed by the next month's billing,
  - one with an **unpaid deposit** (never rolls),
  - one with metered **water/electricity readings** on the current month,
  - one brand-new tenant added this month with only a current invoice.
- **Custom charge categories:** one custom utility ("Garbage", auto-bill 300)
  and one custom invoice category ("Parking") on top of the seeded defaults.
- **Operational garnish:** 2–3 expenses (+1 recurring), 1–2 maintenance
  requests, a couple of communication log entries (simulated), 2 message
  templates, a few notifications. Mirror `seed.py::_seed_operations` patterns.
- **Identity safety:** every tenant phone is fake (`+2547000000xx` sequential),
  every email `demoN@sahilpay.demo`, account numbers prefixed `DEMO-`.
  Demo tenants get **no** user rows (or `is_active=False` ones) — they can
  never log into the tenant portal.
- Dates relative to `date.today()` so the demo always looks current.

### 4.2 Ordering / integrity

`seed_default_categories(shadow.id)` FIRST (registration normally does this;
the shadow is created outside registration so call it explicitly). Then
properties → units → tenants → 3 months of `_run_monthly_billing_for_tenant` +
payments through `allocation_service` (mirror `_seed_category_demo`'s
bill/pay/line_of helpers). One commit at the end of enter/reset (service
flushes, route commits — matches existing service conventions).

### 4.3 Wipe (for reset)

`_wipe_landlord_scoped_rows(shadow_id)` — delete in FK-dependency order:
payment_allocations → payments → balance_rollovers → credit_ledger →
invoice_line_items → invoices → utility_readings → mpesa_transactions →
maintenance_requests → communication_logs → message_templates →
notifications → expenses/recurring_expenses/recurring_bills → tenants →
units → properties → property_groups → charge_categories → audit_logs →
alert/automation/landlord_settings rows → any other landlord-FK table.
Build the list by grepping models.py for `ForeignKey("landlords.id")` and
tenant/property/unit-scoped children — a missed table = orphaned rows, so be
exhaustive. Keep the shadow landlord + stub user rows themselves (reseed into
them). Use bulk `delete(synchronize_session=False)` for speed.

---

## 5. Frontend

### 5.1 State — `client/src/utils/demoStorage.js` (new)

Exact mirror of `client/src/utils/impersonationStorage.js`: key
`sahilpay_demo_mode`, value `{ active: true }`, read synchronously.

### 5.2 Header injection — `client/src/store/apiSlice.js`

In `prepareHeaders` (next to the `X-Impersonate-Landlord` line ~17):

```js
if (getDemoMode()?.active) headers.set("X-Demo-Mode", "1");
```

### 5.3 Enter / exit / reset flow

- **Enter:** confirm modal → `POST /api/demo/enter` (button shows
  "Preparing demo data…" while pending) → `setDemoMode({active:true})` →
  `dispatch(apiSlice.util.resetApiState())` → navigate to landlord dashboard.
- **Exit:** `POST /api/demo/exit` → clear storage → `resetApiState()` →
  navigate to dashboard. Exit must never be blockable by a failed request —
  clear storage even if the POST fails.
- **Reset:** confirm modal ("This wipes your practice data and restores the
  original examples") → `POST /api/demo/reset` → `resetApiState()`.

Cache reset is **mandatory** on every transition — same reason impersonation
does it: RTK Query must never mix demo and real cached responses.

### 5.4 Persistent banner — `client/src/features/landlord/components/DemoModeBanner.jsx` (new)

Mount in `routes/AppRoutes.jsx` inside the authenticated layout, adjacent to
`<AdminImpersonationBanner />` (~line 161). Renders only when demoStorage is
active AND the user role is landlord/PM.

- Sticky at the very top, above everything, full width, high-contrast (amber
  works with the existing impersonation-banner language), **no dismiss/close
  affordance whatsoever**.
- Copy: **"Demo mode — you're practicing with example data. Nothing you do
  here is saved to your real account."**
- Two actions on the banner: **Exit demo** and **Reset demo data**.
- Must be visible on every landlord page including Settings; ensure the layout
  offsets content below it (don't cover the topbar).

### 5.5 Toggle entry points

1. **Sidebar footer** — `LandlordSidebar.jsx` already passes a `footer` prop
   (~line 59). Add a compact "Try demo mode" button/row (with a small flask or
   sparkles icon). When demo is active the sidebar row shows "Exit demo mode"
   instead. Clicking opens the confirm modal (below).
2. **Settings → General** (`GeneralSettings.jsx`) — a "Demo mode" card with the
   same explanation + the same enter button, so users who look in Settings
   find it.

**Confirm modal (enter):** explains in 2–3 sentences what demo mode is (example
data, fully interactive, nothing saved to the real account, constant banner,
exit anytime, practice data kept until reset) + Cancel / "Enter demo mode".

### 5.6 Blocked pages while in demo

Blocked settings sub-pages (route-level, inside `SettingsLayout`/route guard):
**Billing, Account settings, Team management, M-Pesa status/config,
Impersonation requests, Backups, SMS provider, Co-pilot.** When demo is
active, hide these items from the settings nav AND (belt-and-braces) render a
friendly interstitial if navigated directly: "This page manages your real
account and is unavailable in demo mode." with an Exit-demo button.
Everything else — properties, units, tenants, invoices, payments, utilities,
communications, reports/statements, expenses, maintenance, general settings,
allocation priority, document templates, alerts, automation, audit trail —
stays fully interactive.

(Server side needs no per-route blocks for these: they'd merely edit shadow
rows, which is harmless — the UI block is about not confusing trainees. The
only HARD server-side blocks are outbound sends §3.3 and enumeration
exclusions §3.4.)

### 5.7 Onboarding-tutorials interplay

The tutorials/tour engine (ONBOARDING_TUTORIALS_SPEC.md) keys off
`onboarding_state_json`. The shadow landlord has its own row, so tutorials in
demo are independent — that's fine and actually desirable (practice the
checklist on demo data). No special handling needed; just seed the shadow's
`onboarding_state_json = None`. If the welcome modal firing inside demo feels
noisy during verification, pre-mark it dismissed at seed time.

---

## 6. Edge cases & invariants (implement/verify each)

1. **Demo header + no shadow** → resolver silently scopes to real account
   (stale localStorage safety net). Frontend always calls `/enter` first.
2. **Impersonating admin** → demo header ignored; admin sees the real account.
3. **Team member** with a demo header → ignored (v1).
4. **JWT refresh while in demo** → unaffected; demo is a header, not a token
   claim.
5. **Two tabs, one exits demo** → other tab's storage is shared (localStorage)
   so both leave demo on next request; acceptable v1.
6. **Shadow landlord must never appear** in: admin landlord lists/counts,
   billing runs, monthly billing task, affiliate attribution, SMS analytics,
   public tenant lookup/pay, tenant OTP login.
7. **Shadow can never authenticate:** stub user `is_active=False`; demo
   tenants have no active users.
8. **No real sends ever:** service-level force-simulation (`is_demo`) is the
   guarantee; fake phone numbers are only defense-in-depth.
9. **Reset is idempotent & complete:** after reset, row counts match a fresh
   seed; no orphans (assert in tests via the FK-sweep list from §4.3).
10. **Demo never expires** (unlike impersonation) — it's the landlord's own
    sandbox; persists until reset.

---

## 7. Verification plan (do all before declaring done)

**Pytest (`server/tests/test_demo_mode.py`, new):**
- enter creates shadow+stub user, idempotent on second call;
- resolver: header+shadow ⇒ shadow id; no header ⇒ real id; header w/o shadow
  ⇒ real id; team member + header ⇒ real landlord id; impersonation + header ⇒
  impersonated real id;
- seeded invariants: ≥3 properties, ≥12 units, ≥10 tenants, every tenant
  statement reconciles to `-tenant.balance` (reuse the reconciliation check
  pattern from the category-restructure tests), one b/f line exists, one
  credit-consumption exists, deposit never rolled;
- a write in demo scope (create tenant via test_client + `X-Demo-Mode: 1`)
  lands on shadow, real landlord's counts unchanged;
- dispatch_message on demo landlord never calls the provider (monkeypatch
  provider client, assert not called even with `COMMS_SIMULATION_MODE=False`);
- admin landlord list + counts exclude the shadow; `run_monthly_billing_all`
  skips it; `recompute_subscription` no-ops;
- reset: mutate demo data, reset, assert fresh-seed counts + no orphaned rows
  for the shadow id in every table on the §4.3 list.

**Browser (Playwright, both dev servers):**
- login as a real seeded landlord → sidebar "Try demo mode" → confirm modal →
  dashboard shows demo data + banner; banner has no close button and persists
  across Properties/Units/Tenants/Invoices/Payments/Reports pages;
- create a tenant in demo, exit demo, confirm it does NOT exist in the real
  account; re-enter demo, confirm it DOES (persistence);
- Reset demo data → practice tenant gone, originals back;
- blocked settings pages hidden from nav + interstitial on direct URL;
- send an SMS/communication in demo → appears in demo comms log as
  simulated-delivered; 0 console errors throughout.

---

## 8. Out of scope (v1, deliberate)

- Demo mode for team members and for the tenant portal.
- Auto-expiring/cleaning old shadow landlords (revisit if DB size matters).
- Admin visibility into who uses demo mode (the audit rows
  `demo_mode_entered/reset/exited` on the real landlord already give this if
  ever needed).
- Guided-tour integration beyond what §5.7 gets for free.
