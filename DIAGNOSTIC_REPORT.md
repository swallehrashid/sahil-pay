# SahilPay — Pre-Deployment Diagnostic Report

**Date:** 2026-07-16 · **Branch:** `backend-set-up` · **Prepared for:** Swalleh

> You asked me to run a full diagnostic, simulate 5 months across all portals,
> rename "impersonation" to "Client Support", fix anything that breaks, and report
> back **before** preparing the repo for deployment. That's done. **Nothing has been
> committed and no deployment prep has started** — I'm waiting for your go-ahead.

---

## 1. Headline

- **All tests green:** the 103-test pytest suite passes, plus **60 custom money-invariant checks** across a real 5-month simulation, **28 HTTP portal/access-control checks**, and a **9-check live browser walkthrough** with zero console errors. **97 additional checks, 0 failures.**
- **1 real bug found and fixed:** tenant OTP login was sending **real SMS** (via the production FluxSMS key) from any environment, bypassing simulation mode. Fixed.
- **"Impersonation" is gone from the UI everywhere** — renamed to **"Client Support"** — verified visually in the running app.
- **Deployment blockers checked:** migrations apply cleanly on a fresh database; the M-Pesa `/api` routing question is resolved. **Two production requirements the deployment plan doesn't mention** (Cloudinary + AWS S3) need your attention before launch — details in §6.

---

## 2. Scope simulated (5 payer archetypes × 5 months, real engine)

I built a simulation that drives the **actual** billing/rollover/credit/allocation
engine — the same code that runs in production — month by month from Aug to Dec 2026.
It is not a mock; it exercises `allocation_service`, `invoice_tasks`, and the ledger.

| Tenant | Behaviour | Outcome after 5 months | Verified |
|---|---|---|---|
| Alice | Pays in full every month | Balance 0 | ✓ |
| Ben | Pays only part (5,000) every month | Arrears accumulate; rollover carries forward with correct multi-month provenance (8 rollover rows) | ✓ |
| Carol | Overpays in month 1 | Credit auto-applied to later months, then settled | ✓ |
| Dan | Pays months 1–2, then stops | Deep arrears (−36,000); every unpaid month rolls forward | ✓ |
| Eve | Pays nothing for 4 months, clears everything in month 5 | Balance 0 after catch-up | ✓ |

**Money invariants asserted after every single month (all held):**
- Outstanding line items == −tenant balance (the ledger never drifts)
- `credit_balance` == sum of the credit ledger (credit is always accounted for)
- **No deposit line ever rolled** (deposits are held money, never treated as arrears/income)
- Re-running a month's billing does **not** double-bill (idempotency guard works)

---

## 3. Portal-by-portal results (HTTP + browser)

Every portal was exercised against the running API and, for the two admin-facing
ones, the real browser UI.

**Landlord / PM** — login, property list, cross-landlord isolation (Sunrise cannot
read Acme's data → correctly blocked). Settings page renders "Client Support". ✓

**Team Member** — editor and viewer both log in; **viewer is correctly read-only**
(blocked 403 from creating a property). ✓

**Tenant** — OTP login end-to-end: request code → verify → token issued. Wrong code
rejected. Tenant dashboard + statement load. **A tenant token is correctly blocked
from admin endpoints** and sees only its own data. ✓

**Admin** — dashboard + landlord drill-down load; a landlord token is correctly
blocked from admin. **Client Support** request flow works: created a consent request
to Acme, the response text says "Support" (not "Impersonation"), and it shows in the
UI as *Pending*. Audit "Client support actions only" filter works. ✓

**Affiliate** — login works; affiliate is correctly **blocked from admin affiliate
management** (isolation holds). ✓

---

## 4. The rename: Impersonation → "Client Support"

Done as **user-facing text only** (the option you chose). Every visible string —
nav labels, page titles, banners, buttons, toast/notification messages, audit
badges, and the audit-log prefix — now reads "Client Support" / "Support". The
word "Impersonation" no longer appears anywhere a user can see it.

**Deliberately left unchanged** (to keep deployment risk at zero): the API route
paths (`/api/admin/impersonation/...`), database enum values, and internal code
identifiers. These are wired to the frontend and are invisible to users; renaming
them would require a database migration right before launch for no user benefit.

**Verified live in the browser** (screenshots saved): the admin sidebar and page
title both show "Client Support", and a scan of the rendered landlord Settings and
admin pages confirms zero occurrences of "Impersonation".

Files changed: 7 backend, 6 frontend. The audit-log prefix change was made in both
places that write it, and the frontend badge + admin audit filter were updated to
match **both** the new and the old prefix, so your existing audit history still
displays correctly.

---

## 5. The bug I found and fixed

**Tenant OTP login was sending real SMS from every environment.**

- `send_otp_sms` called the low-level `send_sms()` directly, which fires a real
  FluxSMS message whenever `FLUXSMS_API_KEY` is set.
- Your `.env` carries the **real production FluxSMS key**, and `COMMS_SIMULATION_MODE=true`
  is supposed to prevent *all* outbound messages in dev/test — but the OTP path
  ignored that flag. (When I first tested OTP, it sent a live SMS to a seeded
  Kenyan number.)
- **Fix:** `send_otp_sms` now honours `COMMS_SIMULATION_MODE` (logs the code instead
  of sending when simulation is on). I added the same guard to the transactional
  **email** path as a single chokepoint, so OTP/receipt/verification emails are also
  safe if a SendGrid key is ever added to a non-production environment.
- **Production is unaffected:** with `COMMS_SIMULATION_MODE=false` (the go-live
  setting), real OTP codes still send exactly as before. This only closes the
  accidental-send hole in dev/staging.

Re-verified after the fix: OTP request now logs `SMS [simulated — OTP not sent]`
instead of dispatching. All 103 pytest tests still pass.

---

## 6. Deployment readiness audit (per the plan's §2) — what you need to know

I ran the plan's readiness checklist. Most items are ✅; three need your attention.

**✅ Ready:**
- Migrations apply **cleanly on a fresh PostgreSQL database** (58 tables, single
  migration head — no conflicts). This was the plan's main "deployment blocker" check.
- `requirements.txt` includes gunicorn, celery, redis, weasyprint, psycopg2. ✓
- M-Pesa routes **are** `/api`-prefixed → the Nginx config in the plan
  (`proxy_pass http://127.0.0.1:8000;`, no trailing slash) is **correct as written**.
  This resolves the open question flagged in the plan's §5.4.
- CORS is env-driven and restricted to `/api/*`. No hardcoded localhost/sqlite in app
  code. `app.run()` is gated to dev only; debug is env-driven (off by default).
- The frontend production build compiles cleanly (`dist/`), and `.env.production`
  already points the API at `https://sahilpay.co.ke/api`.

**⚠️ Needs a decision / action before launch:**

1. **Production requires Cloudinary AND AWS S3 credentials — the plan doesn't mention
   these.** `ProductionConfig` will **refuse to boot** unless these are set:
   `SECRET_KEY`, `DATABASE_URL`, `JWT_SECRET_KEY`, `REDIS_URL`, `SENDGRID_API_KEY`,
   **`CLOUDINARY_CLOUD_NAME`** (property images), **`AWS_ACCESS_KEY_ID`** (PDF/document
   storage), `PLATFORM_DARAJA_CONSUMER_KEY`, and `PLATFORM_DARAJA_PASSKEY`. You'll need
   Cloudinary and AWS accounts, or we relax those requirements for v1.

2. **`.env.example` is incomplete.** It's missing `REDIS_URL`, `JWT_SECRET_KEY`,
   `CORS_ORIGINS`, the FluxSMS keys, `COMMS_SIMULATION_MODE`, and the Cloudinary/AWS
   vars. When you give the go-ahead, I'll produce a complete, deployment-ready
   `.env.example` tailored to `ProductionConfig`.

3. **`wsgi.py` doesn't exist** (the plan's systemd unit references `wsgi:app`). Not a
   real blocker — `app.py` already exposes a module-level `app`, so gunicorn can target
   **`app:app`** instead. On go-ahead I'll either add a one-line `wsgi.py` or adjust the
   systemd unit — your call.

---

## 7. What I did NOT do (waiting on you)

Per your instruction, I have **not** prepared the repo for deployment: no `wsgi.py`,
no systemd units, no `deploy.sh`, no `.env.example` rewrite, no commit, no push.
Those are the next step once you've reviewed this and given the word.

---

## Artifacts left in the repo (for your review / re-running)

- `SIMULATION_SCENARIO_CATALOGUE.md` — the full list of scenarios I designed and tested.
- `server/simulate_5months.py` — the 5-month money-engine simulation (re-run anytime).
- `server/sim_http_checks.py` — the 28 HTTP portal/access checks.
- `client/browser_walkthrough.mjs` — the Playwright UI walkthrough + screenshots.
- Screenshots in the session scratchpad (landlord dashboard/settings, admin dashboard,
  Client Support page).

**Give the go-ahead and I'll move on to preparing the repo for deployment** (§6 items 2–3,
plus the systemd/Nginx/deploy.sh generation from the plan's §8).
