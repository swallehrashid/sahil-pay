# Deploy Guide — 5-Category Fix Batch (2026-07-23)

Step-by-step guide to deploy the 2026-07-23 changes to the Sahil Pay production
VPS and **prove each change works** across the **frontend, backend, and database**.

> **Two new database migrations must run.** They are the single most important
> step — skip them and the SMS credit calculator will 500 and tenant in-app
> notifications will fail. See **Step 4** and **Appendix A**.
>
> **Celery Beat must be restarted** — a new scheduled task (SMS delivery
> reconciliation) only starts running after a Beat restart. See **Step 3/4**.

All work was committed to branch **`backend-set-up`**. Production runs from
**`main`**, so the first job is getting these commits onto `main`.

---

## 0. What changed (so you know what you're verifying)

| Area | Change | Migration? | FE rebuild? |
|------|--------|:---:|:---:|
| **Tenant dashboard** | Full itemised balance breakdown (rent/utilities/**deposits**) — no charge is silently dropped | – | ✅ |
| **Tenant notifications** | Popup no longer overflows on mobile; solid background | – | ✅ |
| **Emails** | Every landlord→tenant email is Sahil-themed (was plain text) | – | – |
| **Reminders (email/SMS/in-app)** | Always broken down (itemised) + landlord details + payment details; 3 new default templates | – | – |
| **Landlord SMS delivery** | Robust FluxSMS parsing + raw-response logging + **DLR reconcile task** | – | – |
| **Co-pilot settings** | "Recent activity" is now a paginated, scrollable, **clickable** inbox | – | ✅ |
| **Co-pilot review** | Every parsed message → Review & allocate (from Settings, Payments inbox, and the notification) | – | ✅ |
| **Automations** | "Run now" now also generates recurring rent invoices + bills | – | ✅ |
| **Account settings** | Password never shown + dedicated change-password flow (current→new→confirm) | – | ✅ |
| **Login** | "Keep me logged in (24 hours)" checkbox → 24h session | – | ✅ |
| **In-app notifications** | Now reach **OTP-only tenants** (no login), team members, and landlords; fixes "no channel selected" | ✅ `fd0e10981cd2` | ✅ |
| **SMS credit pricing** | Admin-editable **word→credit tiers** + **pre-send cost calculator** | ✅ `5435e6002fe8` | ✅ |

> **SMS still showing "SCHEDULED" on the FluxSMS dashboard is NOT a code bug.**
> That is Safaricom queuing an alphanumeric sender ID (`SAHILPAY`) that is
> pending network approval — a FluxSMS/Safaricom provider action, not a deploy
> step. See **Step 9**.

---

## 1. Pre-flight (on your machine, before touching production)

```bash
cd ~/projects/sahil-pay

# 1a. Everything committed on backend-set-up?
git checkout backend-set-up
git add -A
git commit -m "5-category fix batch: tenant portal, comms/emails/SMS, landlord+admin"   # if there are uncommitted changes
git status            # must be clean

# 1b. Backend test suite — expect 118 passed, 1 pre-existing failure
cd server
export DATABASE_URL="postgresql+psycopg2://sahilpay:sahilpay@localhost:5432/sahilpay"
venv/bin/python -m pytest tests/ -q
#   Expected: "118 passed, 1 failed"
#   The ONE allowed failure is: test_copilot_service.py::test_pipeline_matched_by_account_number
#   (pre-existing, unrelated to this batch). Any OTHER failure → stop and fix.

# 1c. Frontend builds cleanly
cd ../client
npm run build          # expect "✓ built in ..." with no errors
```

If 1b shows failures other than that one, or 1c errors — **stop and fix before deploying.**

---

## 2. Merge `backend-set-up` → `main`

```bash
cd ~/projects/sahil-pay
git checkout main
git pull origin main                 # get whatever is live
git merge backend-set-up             # bring in this batch
# resolve any conflicts, then:
git push origin main
```

> If you deploy directly from `backend-set-up` on the VPS instead of `main`,
> skip this step and check out that branch on the VPS in Step 3.

---

## 3. Deploy on the VPS — the easy path (`update.sh`)

SSH in as the `sahilpay` user, then:

```bash
cd /var/www/sahilpay/app
git fetch origin
git checkout main          # (or backend-set-up if that's your deploy branch)
./deploy/update.sh
```

`deploy/update.sh` does, in order:
1. `git pull --ff-only`
2. `pip install -r server/requirements.txt`
3. **`flask db upgrade`** ← runs the two new migrations
4. `npm ci && npm run build` (frontend)
5. publishes `client/dist` → `/var/www/sahilpay/client`
6. `systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat`
7. health check against `https://sahilpay.co.ke/api/health`

If it prints **`API healthy ✔ — deploy complete`**, jump to **Step 5** (verification).

> **`update.sh` restarts `sahilpay-celerybeat`**, so the new SMS-DLR scheduled
> task is picked up automatically. If you deploy manually (Step 4), don't forget
> that restart.

---

## 4. Manual deploy (if not using `update.sh`) — DO NOT SKIP THE MIGRATION

```bash
cd /var/www/sahilpay/app
git pull --ff-only

# --- Backend deps ---
server/venv/bin/pip install -r server/requirements.txt

# --- Migrations (the critical step) ---
cd server
set -a && source .env && set +a          # load prod env (DATABASE_URL etc.)
venv/bin/flask db current                # note the current head first
venv/bin/flask db upgrade                # applies fd0e10981cd2 then 5435e6002fe8
venv/bin/flask db current                # MUST now print: 5435e6002fe8 (head)
cd ..

# --- Frontend build + publish ---
cd client
npm ci && npm run build
cd ..
rm -rf /var/www/sahilpay/client.bak
[ -d /var/www/sahilpay/client ] && mv /var/www/sahilpay/client /var/www/sahilpay/client.bak
cp -r client/dist /var/www/sahilpay/client

# --- Restart everything (Beat restart is required for the new task) ---
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
sudo systemctl status sahilpay --no-pager | head -5
```

### The two migrations you are applying

| Order | Revision | What it does |
|-------|----------|--------------|
| 1 | `fd0e10981cd2` | Adds `notifications.recipient_tenant_id` + makes `recipient_user_id` nullable (lets OTP-only tenants receive in-app notifications) |
| 2 | `5435e6002fe8` | Creates `sms_credit_ranges` table (word→credit pricing tiers) |

After `flask db upgrade`, **`flask db current` must show `5435e6002fe8 (head)`.**
If it errors, read the message — do not restart services on a half-migrated DB.

---

## 5. Post-deploy verification — prove each change works

Run these from any machine (they hit production HTTPS). Replace credentials with
real production ones where noted.

### 5a. Database — both migrations landed

```bash
# On the VPS:
cd /var/www/sahilpay/app/server
set -a && source .env && set +a
venv/bin/flask db current          # -> 5435e6002fe8 (head)

# Confirm the new table + column exist and the credit tiers seeded:
venv/bin/python - <<'PY'
from app import create_app
from models import SmsCreditRange, Notification
app = create_app()
with app.app_context():
    print("sms credit ranges:", SmsCreditRange.query.count())          # expect 5 (seeds on first read)
    cols = [c.name for c in Notification.__table__.columns]
    print("recipient_tenant_id present:", "recipient_tenant_id" in cols)  # expect True
PY
```

### 5b. Backend health + services

```bash
curl -sf https://sahilpay.co.ke/api/health && echo "  <- API up"
# On the VPS:
sudo systemctl status sahilpay sahilpay-celery sahilpay-celerybeat --no-pager | grep -E "●|Active:"
#   all three must be "active (running)"

# Confirm the new scheduled task is registered in Beat:
sudo journalctl -u sahilpay-celerybeat -n 40 --no-pager | grep -i "reconcile-sms-delivery" || echo "check beat started"
```

### 5c. Tenant dashboard — accurate itemised breakdown

1. Log in to the **tenant portal** (`https://sahilpay.co.ke/tenant/login`) as a
   tenant who has more than one charge type (e.g. rent + a utility + a deposit).
2. On the dashboard, confirm:
   - **Total outstanding** equals the sum of every open charge.
   - The **"What makes up your balance"** card lists each charge (Rent, Water,
     Electricity, deposits marked *Refundable deposit*, etc.).
   - A **Deposits held** tile appears when there's a deposit.
3. The numbers in the card must add up to the Total outstanding.

### 5d. Tenant notification popup (mobile)

On a phone (or browser at ~390px width), log into the tenant portal and tap the
**bell**. The panel must sit fully on-screen (no overflow off the left edge) with
a solid background.

### 5e. Themed + broken-down reminders

1. As a **landlord**, go to **Tenants → (a tenant with a balance) → Send reminder**
   (or **Communications → Send message**).
2. Send via **Email** and **In-app** (and SMS if you have credits).
3. Verify:
   - The **email** arrives Sahil-branded (dark card, logo lockup) — not plain text.
   - The body is **broken down** (each charge listed) with **landlord details**
     (name, location, phone, email) and **payment details** (paybill/till + account).
   - The **in-app** notification reaches the tenant (see 5h) and is also itemised.

### 5f. In-app notifications reach everyone (the "no channel selected" fix)

- **Landlord → tenant:** send an in-app-only reminder to an **OTP tenant** (one
  with no password login). It must succeed ("sent via in_app"), **not** say
  "no communication channel selected."
- **Landlord → team member:** Communications/Notifications send to a team member;
  log in as that team member and confirm the bell badge + notification.
- **Admin → landlord:** from the admin portal, notify a landlord; log in as that
  landlord and confirm it appears with an incremented bell badge.

### 5g. Co-pilot: scrollable table + clickable review

1. As a landlord with Co-pilot history: **Settings → Co-pilot → Recent activity**.
2. Confirm the table **paginates and scrolls** (rows control at the bottom).
3. Click a **parsed** row (or its **View**) → a detail modal opens →
   **Review & allocate** opens the payment review with the amount **prefilled**.
4. Also confirm the Co-pilot "payment needs review" **notification** deep-links
   straight into that review modal (`/landlord/payments?review=<id>`).

### 5h. Automations "Run now" creates invoices

1. **Settings → General → Automated tasks.** All six checkboxes toggle and save.
2. Ensure "recurring rent invoices" / "other recurring bills" are checked.
3. Click **Run scheduled automations now.** The toast must report counts, e.g.
   `X rent invoice(s), Y recurring bill(s), … reminders, … lease notices.`
4. Check **Invoices** — the newly generated invoices for the current month appear.
   (Re-running is safe/idempotent — already-billed tenants are skipped.)

### 5i. Account: password hidden + change-password pipeline

1. **Settings → Account.** Your password is **not** displayed anywhere.
2. In the **Change password** card: wrong current password is rejected; a
   mismatched confirmation is rejected; a valid current→new→confirm succeeds.
3. Log out and log back in with the **new** password to confirm (then change it
   back if this was a test account).

### 5j. Login: keep me logged in

On the login page confirm the **"Keep me logged in (24 hours)"** checkbox is
present. Log in with it ticked; the session should persist for the working day
rather than timing out quickly.

### 5k. SMS credit tiers (admin) + pre-send calculator (landlord)

- **Admin → SMS → Pricing:** the **"SMS credit tiers (words → credits)"** editor
  shows the default tiers. Add a tier, edit one, and **Save credit tiers**. Try
  an overlapping range → it must be rejected. Restore sensible values.
- **Landlord → Communications → Send message** (SMS channel): as you type, the
  **SMS cost** panel shows the credit cost and your balance (e.g. "2 credits for
  1 message · 35 words each"), and warns if the balance is insufficient.

---

## 6. Environment variables to confirm in prod `server/.env`

No **new** required variables were introduced this batch. Confirm the existing
production values are still correct:

```
DATABASE_URL=postgresql+psycopg2://sahilpay:...@localhost:5432/sahilpay
JWT_SECRET_KEY=...            # long random; do NOT rotate casually (invalidates sessions)
SECRET_KEY=...
RATELIMIT_STORAGE_URI=redis://localhost:6379/1
CELERY_BROKER_URL=redis://localhost:6379/0
COMMS_SIMULATION_MODE=false   # real SMS/email in production
MPESA_SIMULATION_MODE=false
FLUXSMS_API_KEY=...           # live key
FLUXSMS_SENDER_ID=SAHILPAY
```

> Optional session tuning: `JWT_ACCESS_MINUTES` sets the default (unchecked)
> session length. "Keep me logged in" overrides it to 24h at login regardless.

---

## 7. Smoke-test checklist (tick before calling it done)

- [ ] `flask db current` → `5435e6002fe8 (head)`
- [ ] `SmsCreditRange.query.count()` → 5 ; `recipient_tenant_id` column present
- [ ] `curl https://sahilpay.co.ke/api/health` → 200
- [ ] `sahilpay`, `sahilpay-celery`, `sahilpay-celerybeat` all **active (running)**
- [ ] Beat log mentions `reconcile-sms-delivery`
- [ ] Tenant dashboard total = sum of itemised charges; deposits shown
- [ ] Tenant bell popup on mobile stays on-screen
- [ ] Landlord→tenant email is Sahil-themed and itemised (breakdown + landlord + payment)
- [ ] In-app reminder to an OTP tenant succeeds (no "no channel selected")
- [ ] In-app to team member and admin→landlord both received (badge increments)
- [ ] Co-pilot Recent activity paginates/scrolls; parsed row opens Review & allocate
- [ ] "Run scheduled automations now" reports invoice counts; invoices appear
- [ ] Change-password flow works (current→new→confirm); password never shown
- [ ] "Keep me logged in (24 hours)" checkbox present on login
- [ ] Admin SMS credit-tier editor saves + rejects overlaps
- [ ] Landlord SMS compose shows the live credit calculator

---

## 8. If something breaks

```bash
# Backend errors:
sudo journalctl -u sahilpay -n 80 --no-pager
# Celery / scheduled tasks:
sudo journalctl -u sahilpay-celery -n 80 --no-pager
sudo journalctl -u sahilpay-celerybeat -n 40 --no-pager
# nginx (frontend routing / 502s):
sudo tail -n 50 /var/log/nginx/error.log
```

A 500 on the SMS credit calculator or on sending an in-app notification almost
always means **the migrations didn't run** — recheck Step 4 / `flask db current`.

---

## 9. Known non-deploy item: SMS "SCHEDULED"

If a landlord's SMS shows **SCHEDULED / no network / no message ID** on the
FluxSMS dashboard, that is **Safaricom queuing an unapproved alphanumeric sender
ID**, not a Sahil Pay bug. The code now logs the full provider response and a DLR
reconciliation task flips the status to *delivered* once Safaricom dispatches it.
**Action:** confirm with FluxSMS that sender ID **`SAHILPAY`** is approved on the
Safaricom route. Email + in-app reminders work regardless.

---

## 10. Rollback

If you must revert:

```bash
cd /var/www/sahilpay/app
git log --oneline -5                          # find the previous good commit
git checkout <previous-good-commit>

# Frontend: restore the backup update.sh kept
sudo rm -rf /var/www/sahilpay/client
sudo mv /var/www/sahilpay/client.bak /var/www/sahilpay/client

sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
```

> The two new migrations are **additive** (a new nullable column + a new table),
> so they are safe to leave in place after a code rollback — the old code simply
> ignores them. Only downgrade the DB if you specifically need to:
> ```bash
> cd server && set -a && source .env && set +a
> venv/bin/flask db downgrade c2b3d4e5f6a7   # undoes BOTH of this batch's migrations
> ```

---

## Appendix A — the two migrations in detail

**`fd0e10981cd2` — notifications: add `recipient_tenant_id`**
- Adds nullable `notifications.recipient_tenant_id` (FK → tenants) and makes
  `recipient_user_id` nullable. A notification now targets **either** a User
  **or** a Tenant, so OTP-only tenants (who have no User row) can receive in-app
  notifications. Additive and reversible.

**`5435e6002fe8` — add `sms_credit_ranges` table**
- New table holding admin-editable word→credit pricing tiers. On first read the
  app seeds five market-standard defaults (1–25 words = 1 credit, 26–50 = 2,
  51–75 = 3, 76–100 = 4, 101+ = 5). Additive and reversible.

**Apply both:** `flask db upgrade` from `server/` with the prod env loaded.
**Confirm:** `flask db current` → `5435e6002fe8 (head)`.
