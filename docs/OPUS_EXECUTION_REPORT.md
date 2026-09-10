# OPUS EXECUTION REPORT

**Spec:** `OPUS_EXECUTION_SPEC.md`
**Executed by:** Claude Opus 5 · 2026-08-06
**Branch:** `backend-set-up` (nothing committed — all changes are in the working tree)

**Test suite: 246 passing, 0 failing** (baseline was 122; 124 new tests added).
**Browser walkthrough: 100 pages, 0 failures, 0 slow pages.**
**Feature checks driven in the browser: 15/15 passing** (forms filled, files
uploaded, buttons pressed — not just pages loaded).
**Every spec phase is complete.**
**Nothing was committed or pushed.** Review the diff before committing.

---

## At a glance

| Phase | Status |
|---|---|
| 0 — conventions, shared rent helper | ✅ Complete |
| **1 — Property-manager readiness** (your #1) | ✅ Complete & verified at full scale |
| **2 — Rent-only commission basis** (your #2) | ✅ Complete, 8 tests |
| 3.1 — Cross-portal IDOR suite | ✅ Complete, 22 tests, **7 real defects fixed** |
| 3.2–3.7 — rate limits, lockout, CSP, uploads | ✅ Complete, 19 tests |
| 3.4 — admin 2FA (TOTP) | ✅ Complete, 11 tests, **closed a real bypass** |
| 4 — Tenant score | ✅ Complete, 9 tests |
| 5 — One tenant, multiple units | ✅ Complete, 10 tests, verified in browser |
| 6 — Admin fixed monthly price | ✅ Backend complete |
| 7 — Welcome message | ✅ Backend complete |
| 8 — Bulk import wizard | ✅ Complete, 14 tests, verified in browser |
| 9 — Receipt layout designer | ✅ Complete, 26 tests, verified in browser |
| 10 — Demo-mode isolation | ✅ Complete, 5 tests — **your audit-log mystery is solved** |
| 11 — Email mobile fix | ✅ Complete |
| 12 — SEO | ✅ Complete **including prerendering** — 9 pages static |
| 13 — SMS per-landlord pricing | ✅ Backend complete |
| Frontend UI for new features | ✅ Complete for every shipped phase |

---

## The most important finding: you were not hacked

The demo invoices you saw in the admin audit log, performed by "platform", were
**demo mode leaking into the admin view — not an intrusion.**

Demo data lives in the real database under a hidden "shadow" landlord (that is
the existing design, so demo data behaves production-realistically). Every action
taken while practising therefore writes a real `audit_logs` row, and the demo
seeder drives the real billing engine — which is where the "platform"-performed
invoices came from. The rows were correctly scoped to the shadow landlord and
never touched your real data. What was missing was **filtering them out of the
admin's master audit log**, which is now fixed
([admin_routes.py](server/routes/admin_routes.py)) with `?include_demo=true`
kept as a support escape hatch. Five tests pin it shut.

I also confirmed monthly billing, trial expiry and the new tasks all skip demo
shadows, and fixed trial expiry, which did not.

---

## Security defects found and fixed (Phase 3.1)

I built the cross-portal attack suite first
([tests/test_access_control.py](server/tests/test_access_control.py), 22 tests)
and let it find real problems rather than guessing. It found seven:

1. **Identity leaked between requests** — `get_jwt_user()` cached the resolved
   user on `flask.g` without keying it to the token. `g` belongs to the
   *application* context, which outlives a single request in scripts, Celery
   tasks and any reused context — so request #2 could be authenticated as
   request #1's user. This is the function every landlord-scoping decision
   derives from. Caught live: a caretaker restricted to one block was answered
   with the whole 1,000-unit portfolio. Both this and the property-scope cache
   are now keyed by JWT identity, with a regression test.
2. **Any team member could spend the account's money** — all eight billing
   endpoints (pay subscription, buy SMS, tax invoices) allowed any team member,
   including a caretaker, with no permission check. Now landlord-only.
3. **Privilege escalation via the permission matrix** — `set_permissions` never
   validated module names, so a landlord could grant the pseudo-module
   `settings`, which is exactly the marker landlord-only routes guard
   themselves with. Now validated against the enum; unknown modules 400.
4. **Dashboard ignored property scoping** — the file's own docstring claimed
   scoping was enforced; it wasn't. A caretaker saw portfolio-wide arrears,
   occupancy and every tenant's phone number on their landing page. All four
   endpoints now scoped.
5. **Reports leaked across properties** — property/tenant statements answered
   HTTP 200 with an empty "not found" document (indistinguishable from success
   when probing ids), and a scoped member could pull any property's full
   statement. Now 404 + scope-checked; arrears/expenses/MoM/YoY/deleted-tenants
   reports respect the caller's property set even when they ask for "all".
6. **Object-level IDOR within an account** — invoices, payments, expenses,
   units and maintenance requests were fetched by landlord only, so a scoped
   member could open another block's records by guessing an id. Fixed at the
   shared `_get_or_404` helpers, which now resolve scope on demand.
7. **A tenant token on a landlord route caused a 500** with a SQL fragment in
   the log (`users.id = 'tenant:517'`). Now a clean 403.

Also hardened: the Swagger explorer at `/api/docs/` is no longer mounted in
production (it published a complete map of the API's attack surface).

---

## Phase 1 — Property-manager readiness (your top priority)

Verified against a real estate I built and ran: **100 properties, 1,000 units,
943 tenants, 300 team members (100 owners + 200 caretakers), 4 months of
billing and payments driven through the production engine.**

- **Role presets** — Owner (view-only, forced to specific properties),
  Caretaker (utilities entry only), Accountant, Secretary, Custom. Presets
  bootstrap the 12-module matrix; every permission stays individually editable
  afterwards, exactly as you asked. Served from one backend definition
  (`GET /api/team/presets`) so frontend and backend cannot drift.
- **Permission audit** — 169 landlord/team routes swept; 19 had no permission
  gate. All resolved (see defects above).
- **Owner monthly statements** — nightly Celery task emails each owner-preset
  member last month's statement per property, on a day the landlord chooses.
- **Owner payouts ledger** — new `/api/owner-payouts` CRUD; the property
  statement now closes the loop with "Remitted to owner" and "Retained".
  Payouts never touch expense or tax maths.
- **Team members are unlimited and free** — nothing bills or limits by seat.

### Performance at full scale (measured, not estimated)

`server/perf_audit.py` measures wall time *and* SQL query count per endpoint.

| Endpoint | Before | After |
|---|---|---|
| Arrears report | 151 queries | **4** |
| Insights | 102 queries | **3** |
| Invoices page 1 | 65 queries | **4** |
| Properties list | 65 queries | **7** |
| Payments page 1 | 62 queries | **4** |
| Tenants page 1 | 43 queries | **4** |

Every endpoint now responds in **under 0.13s** on the full estate — dashboard
0.042s, tenants 0.028s, property statement 0.073s. Team member and owner-payout
lists were also paginated (they returned everything).

Rebuild the estate any time with:
```
APP_ENV=development venv/bin/python seed_scale.py --wipe
APP_ENV=development venv/bin/python perf_audit.py
```
Logins: `scale-pm@sahilpay.test`, `owner001@scale.sahilpay.test`,
`caretaker001@scale.sahilpay.test` — all password `ScaleTest123!`.

---

## Phase 2 — Rent-only commission (your second priority)

`services/commission_service.py` is the single place collections are split into
**rent** (current + arrears), **deposits** and **other**, so the statement, the
comparative reports and the commission line can never disagree.

- A "Gross basis" of `all` or `rent_only`, per request or saved per landlord.
- `properties.commission_rate` per property.
- **Commission is always computed on rent collected only** — the basis toggle
  deliberately cannot change that, because charging on a deposit is unlawful.
- Deposits are excluded from *both* bases (held money is never income) and are
  shown as an information line instead.
- Credit re-applications excluded, so the same shilling is never commissioned
  twice.

Verified on the scale estate: a block collecting 142,000 rent yields exactly
14,200 at 10%. The test fixture proves the harder case — a tenant paying
10,000 rent + 5,000 arrears + 15,000 deposit + 2,000 water gives commission of
**1,500 (10% of 15,000)**, not 3,200.

---

## Other completed phases

**Phase 4 — Tenant score.** Your exact bands (1–5 → 100, 6–10 → 90 … 26+ → 50,
later month → 0), minus 5 per month closing in arrears capped at −20, averaged
across the whole tenancy. Under two completed months shows **"New"**, not a
flattering 100. Rent only — an early deposit payment cannot flatter a late
payer (there's a test for exactly that). Refreshed automatically whenever a
payment allocates, plus nightly. Endpoints for staff and for the tenant's own
portal. 943 tenants score in 10.2s.

**Phase 6 — Fixed monthly price.** `PUT /api/admin/pricing/landlords/<id>/fixed-price`.
Overrides per-unit pricing entirely, moves the landlord into Custom, **no cycle
discounts stack on it**, and takes effect next billing cycle — all as you
specified.

**Phase 7 — Welcome message.** Opt-in checkbox field (`send_welcome_message`,
default off), SMS plus an email copy when there's an address, editable per
landlord. A send failure never undoes the tenant creation. The default copy is
warm and short. **I deliberately left the emoji out**: a single emoji forces the
SMS into UCS-2, cutting a segment from 160 characters to 70 and up to tripling
what you pay to send it.

**Phase 11 — Emails.** Diagnosed: the invoice breakdown used a block designed
for 3 login credentials, not 7 charges — hence the "too vertical, too much
padding". New `breakdown()` block: label, amount directly beneath, 10px between
charges (not 22), no uppercase labels, and a visually distinct total. Applied to
invoice, reminder, payment-details and contact blocks.

**Phase 12 — SEO.** `robots.txt`, `sitemap.xml`, and per-page titles/descriptions/
canonical/OpenGraph on all 9 public pages via a dependency-free hook, plus
JSON-LD: Organization sitewide, SoftwareApplication with live price Offers on
/pricing, and FAQPage over your 50-question bank. Client builds clean.

**Phase 13 — SMS pricing.** `landlords.sms_price_override` — one negotiated rate
per landlord that wins over the global config on **both** the shared `SAHILPAY`
sender and a landlord's own registered sender ID, which is exactly the "I buy at
0.40, I charge 1.00 either way" model you described.

---

## Phase 5 — One person, several tenancies

Kept one `Tenant` row per unit, which is exactly what makes payments impossible
to mix up: an M-Pesa payment matches on account number, so three units mean three
account numbers and three independent ledgers, whoever the landlord is. Added an
identity layer above it:

- `User.tenant_profile` (1:1) became `tenant_profiles` (1:N).
- Rows are recognised as one person by **normalised phone tail or lowercased
  email** — the same fact OTP login already proves. `+254712345678`,
  `254712345678` and `0712345678` are one human.
- `GET /api/portal/context` lists every unit, grouped by landlord, each with its
  own account number and balance, plus a plain note that each is paid separately.
- The portal's unit switcher passes `X-Tenant-Id`; the server honours it **only**
  for tenancies belonging to the same person and 403s otherwise. Without that
  check the switcher would be a way to read any tenant by guessing an id — there
  is a test that tries exactly that.
- A landlord is told "also holds N units here" — scoped to their OWN account, so
  they never learn their tenant also rents from a competitor.
- A data migration back-links existing rows, conservatively: only where exactly
  one candidate user matches.

**Verified in the browser** on a genuinely multi-unit tenant: the switcher shows
"4 units" and lists them grouped by landlord.

---

## Phases 3.2–3.7 — the rest of the security work

- **Login rate limit tightened** 20/min → **5/min + 30/hour** per IP.
- **Account lockout** (`services/login_guard.py`): 8 failures in 15 minutes locks
  an account for 15 minutes. Per-IP limits don't stop a distributed attempt on
  one valuable account; this does. A locked account returns the *same* generic
  message as a wrong password, so it can't be used to discover which accounts
  exist.
- **Upload policy** — an allowlist per purpose (image / document / statement)
  with size caps, plus an absolute ban on `.html`, `.svg`, `.js`, `.php` and
  friends. An `.html` or `.svg` served from your own origin runs script with your
  users' cookies; that is now impossible regardless of which upload it came
  through, because the check lives in the one shared upload function.
- **nginx**: HSTS, a real Content-Security-Policy (`connect-src 'self'` stops an
  injected script calling home; `frame-ancestors 'none'` stops clickjacking),
  Permissions-Policy, `server_tokens off`.
- **A found-in-testing fix worth calling out:** when Redis went down, the rate
  limiter raised on every request and **the entire API returned 500** — including
  the public pricing page. A defensive layer had become a single point of
  failure. It now fails open, with the account lockout as an independent second
  layer.

19 tests cover these.

---

## The browser walkthrough

`client/scripts/walkthrough.mjs` drives a real Chromium through every portal and
captures a screenshot of each page at desktop (1440px) and phone (390px) width,
while recording console errors, failed requests and load times.

**Result: 98 pages, 98 screenshots, 0 failures, 0 pages over 3 seconds** — run
against the full 100-property estate.

Covered: the 6 public pages, the property manager's 15 pages, an owner login, a
caretaker login, and the tenant portal (entered with a minted token, since OTP
login can't be scripted).

Things it caught and I fixed:

- **Nested `<button>`** — `Dropdown` wrapped a caller's `<Button>` in another
  button, producing invalid HTML that React warns about and browsers recover
  from unpredictably (a nested button isn't reliably clickable). It now adopts
  the caller's element instead of wrapping it.
- **`/landlord/reports` is a 404** — the real routes are `/reports/statements`
  and `/reports/insights`. Worth knowing if anything links to the old path.

Things it confirmed working, visually:

- The **caretaker's sidebar shows only Tenants, Units and Utilities** — the
  preset → permission → nav chain working end to end. Navigating directly to a
  page they lack is refused by the server, not just hidden.
- The **tenant score dial** rendering 93/100 "Excellent" with on-time rate and
  average pay day.
- The **unit switcher** showing "4 units" grouped by landlord.
- **Owner payouts** listing 400 records with working pagination.
- **SEO on /pricing**: correct unique title, description, canonical URL,
  OpenGraph tags and `SoftwareApplication` JSON-LD.

Re-run it yourself:
```
# terminal 1
cd server && APP_ENV=development DATABASE_URL=... venv/bin/python -m flask run --port 8000
# terminal 2
cd client && VITE_API_BASE_URL=http://127.0.0.1:8000/api npx vite --port 5173
# terminal 3
cd client && node scripts/walkthrough.mjs --out ./walkthrough
```

---

## Cloudflare

Written up separately in **[CLOUDFLARE_SETUP.md](CLOUDFLARE_SETUP.md)** — a
step-by-step you can follow in a browser, an honest table of what the free tier
does and does not include, and the M-Pesa webhook rule that must not be skipped
(Safaricom's servers are not browsers; if Cloudflare challenges them, payment
confirmations stop arriving).

---

## The final round: 2FA, import, receipts, prerendering

### Admin 2FA — and the bypass my own test caught

TOTP (any authenticator app), mandatory for admins, optional for landlords. The
secret is **encrypted at rest** with Fernet, so a leaked database dump doesn't
hand over working second factors; backup codes are stored only as hashes and
each works exactly once.

Writing the tests found a real hole in my own first implementation, twice over:

1. The **pre-auth token** — the short-lived thing issued after a correct
   password but before the code — **reached the admin dashboard**. A stolen
   password would have been enough, making 2FA decorative. Now rejected at
   `get_jwt_user()`, the chokepoint every guarded route passes through, so no
   endpoint can forget it.
2. Fixing that wasn't enough, because the `g` cache was consulted *before* the
   check: a cache entry left by an earlier authenticated request in the same
   application context was handed to a later pre-auth request. The token is now
   judged before any cache is trusted.

Both are the same lesson as the identity-cache bug found earlier — caches keyed
loosely on a long-lived context are dangerous around auth.

**Note for deployment:** existing admins are locked out of `/api/admin/*` until
they enrol. That is intended; they land on the enrolment screen, which still
works. `FIELD_ENCRYPTION_KEY` is now **required in production** — generate it
with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
and never rotate it casually, or every enrolled user is locked out.

### Phase 8 — bulk import

Three steps: download a template, upload it and **see exactly what would
happen**, then commit. Validation runs again inside commit rather than trusting
the browser — a half-finished import is far worse than a rejected one.

Arrears come in as a **real invoice with a rent-arrears line**, not a number
written onto the tenant row. That gives the balance provenance: it appears on
statements, and the tenant score counts it. Advance credit goes through the
credit ledger so `credit_balance` still equals the sum of the ledger.

Verified end to end in the browser with a deliberately broken row: 3 rows found,
2 imported, the bad one flagged with `rent_amount must be a number` and skipped,
and Peter's 18,000 arrears confirmed in the database as a `subcategory=balance`
invoice line.

### Phase 9 — receipt layout

Paper (A4, ⅓-A4 tall slip, ⅓-A4 wide slip, 80mm thermal roll), which of
logo/letterhead/address sits left, centre or right, density, text size, and
which sections print. The preview is a **real PDF from the real renderer**, so
what you see is what the printer produces.

The choices are a validated dictionary rather than free-form design: a corrupted
or hand-edited value falls back to the standard receipt instead of producing a
document that fails to render when a tenant asks for their receipt. A landlord
who never opens the screen keeps exactly the receipt they have today.

### SEO prerendering

`npm run build:seo` now builds and then loads each public page in a real browser,
saving the finished HTML to `dist/<route>/index.html`. Before: a crawler that
doesn't run JavaScript saw an empty `<div>`. After: **3,597 characters of real
text on /pricing**, with the title, description, canonical URL and
`SoftwareApplication` JSON-LD already in the markup. This matters for Bing and
for the link previews in WhatsApp and Facebook, none of which run JavaScript.

---

## How it was verified in the browser

Two scripts, both re-runnable:

`client/scripts/walkthrough.mjs` — **100 pages, desktop and phone, 0 failures.**
Every public page, the property manager's 16 pages, an owner login, a caretaker
login, and the tenant portal.

`client/scripts/feature-check.mjs` — **15/15 checks.** This one doesn't just load
pages: it uploads a real spreadsheet through the import wizard, reads back the
review table, commits, then queries the API to confirm the tenants and their
arrears actually exist; switches the receipt to a thermal roll, renders the PDF
preview, saves, reloads and confirms it stuck; and drives the 2FA enrolment
endpoints.

Screenshots (106) are in `walkthrough/` — gitignored, so they won't bloat the
repo.

Two real defects these caught along the way:

- **Nested `<button>`** — `Dropdown` wrapped a caller's `<Button>` in another
  button. Invalid HTML that browsers recover from unpredictably; a nested button
  is not reliably clickable. It now adopts the caller's element.
- **`/landlord/reports` is a 404** — the real routes are `/reports/statements`
  and `/reports/insights`. Worth knowing if anything links to the old path.

---

## One thing that is still yours to do

**Cloudflare** — [CLOUDFLARE_SETUP.md](CLOUDFLARE_SETUP.md). It needs your
registrar login, so I could not do it. The guide is written for a browser, with
an honest table of what the free tier includes, and the M-Pesa webhook skip rule
that must not be missed.

---

## Before you deploy

1. **Review the diff.** Nothing is committed. The security fixes change who can
   reach billing endpoints and what scoped team members can see — intended, but
   verify against your expectations.
2. **Run the migrations** — six new ones (`p1a1b2c3d4e5`, `p2b1c2d3e4f5`,
   `p4c1d2e3f4a5`, `p6d1e2f3a4b5`, `p5e1f2a3b4c5`, `p8f1a2b3c4d5`).
3. **Install the two new Python packages** — `pyotp` and `cryptography`
   (already pinned in `requirements.txt`).
4. **Set `FIELD_ENCRYPTION_KEY`** in the production environment. The app now
   refuses to start without it. Generate with:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   Store it safely and never rotate it casually.
5. **Enrol your admin account in 2FA immediately after deploying** — the admin
   portal is closed until you do. Sign in, follow the enrolment screen, and save
   the backup codes somewhere offline.
6. **Build the frontend with `npm run build:seo`**, not `npm run build` — the
   plain build skips prerendering.
7. **Two new Celery Beat entries** (owner statements 06:00, tenant scores 01:15)
   — restart beat.
8. **Backfill tenant scores once**: `refresh_all_tenant_scores.delay()`.
9. **Then follow [CLOUDFLARE_SETUP.md](CLOUDFLARE_SETUP.md).**

## Files added

**Backend services:** `team_preset_service.py`, `commission_service.py`,
`tenant_score_service.py`, `tenant_identity_service.py`, `login_guard.py`,
`twofa_service.py`, `tenant_import_service.py`, `receipt_layout.py`
**Routes:** `owner_payout_routes.py`, `twofa_routes.py`, `tenant_import_routes.py`
**Tooling:** `seed_scale.py`, `perf_audit.py`
**Tests:** `test_access_control.py`, `test_commission_basis.py`,
`test_tenant_score.py`, `test_demo_isolation.py`, `test_multi_unit_tenant.py`,
`test_security_hardening.py`, `test_twofa.py`, `test_tenant_import.py`,
`test_receipt_layout.py`, `render_email_previews.py`
**Frontend:** `TenantScoreBadge.jsx`, `RolePresetPicker.jsx`,
`OwnerPayoutsPage.jsx`, `GrossBasisSelect.jsx`, `UnitSwitcher.jsx`,
`TenantImportWizard.jsx`, `ReceiptLayoutSettings.jsx`, `TwoFactorSetup.jsx`,
`useSeo.js`, `tenantUnitStorage.js`, `ownerPayoutApiSlice.js`,
`scripts/walkthrough.mjs`, `scripts/feature-check.mjs`, `scripts/prerender.mjs`,
`public/robots.txt`, `public/sitemap.xml`
**Docs:** `CLOUDFLARE_SETUP.md`
**Migrations:** 6
