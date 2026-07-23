# Redeploy Guide — `main` branch (changes of 2026-07-22)

This guide redeploys Sahil Pay to production (`main` branch) and verifies that
**every change made on 2026-07-22 actually works** across the **frontend, the
backend, and the database**.

> **Do NOT forget the two new database migrations.** They are the single most
> important step. Without them the SMS-credit feature will 500 and the Co-pilot
> bank presets will be missing. See **Step 4** and **Appendix A**.

Everything today was committed to branch **`backend-set-up`**
(commits `a49cca4`, `d91ef98`). Production runs from **`main`**, so the first job
is to get these commits onto `main`.

---

## 0. What changed today (so you know what you are verifying)

| Area | Change | Needs migration? | Needs FE rebuild? |
|------|--------|:---:|:---:|
| **Tenant OTP login** | `/api/auth/me` now handles `tenant:<id>` identity (was 500 → bounce) | – | – (backend) |
| **Reports/receipts branding** | Landlord logo/signature now render in PDFs from **local disk storage** (WeasyPrint URL fetcher) | – | – |
| **Landlord receipt download** | Now uses the **branded** receipt (logo+signature), matching reports | – | – |
| **Co-pilot parser** | Tolerant wording + **8 bank preset templates** (Co-op, NCBA, Absa, Family, DTB, Stanbic, I&M, M-Pesa till) | ✅ `c1a2b3d4e5f6` | – |
| **OTP not-registered** | Returns clear 404 message instead of failing silently | – | ✅ (TenantOtpLogin.jsx) |
| **Admin: SMS credit per landlord** | New `sms_landlord_credits` table + endpoint + "Add SMS credit" button | ✅ `c2b3d4e5f6a7` | ✅ (LandlordDetail.jsx) |
| **SMS delivery logging** | Captures FluxSMS `message_id` + logs DLR on OTP send | – | – |

> **SMS not arriving is NOT a code bug.** Confirmed via live FluxSMS: the send
> succeeds but Safaricom's delivery report stalls at `SentToNetwork`. This means
> the alphanumeric sender ID **`SAHILPAY` must be registered/approved on the
> Safaricom route with FluxSMS**. This is a provider action, not a deploy step.
> Email OTP works regardless. See **Step 9**.

---

## 1. Pre-flight (on your machine, before touching production)

```bash
cd ~/projects/sahil-pay

# 1a. Make sure everything is committed on backend-set-up
git checkout backend-set-up
git status            # must be clean
git log --oneline -3  # expect: d91ef98 updates landlord reports / a49cca4 ...

# 1b. Run the full backend test suite — must be 119 passed
cd server
source venv/bin/activate
export DATABASE_URL="postgresql+psycopg2://sahilpay:sahilpay@localhost:5432/sahilpay"
python -m pytest tests/ -q          # expect: 119 passed

# 1c. Confirm the frontend builds cleanly
cd ../client
npm run build                        # expect: "✓ built in ..." with no errors
```

If any of these fail, **stop** and fix before deploying.

---

## 2. Merge `backend-set-up` → `main`

```bash
cd ~/projects/sahil-pay
git checkout main
git pull --ff-only origin main        # get whatever prod already has
git merge --no-ff backend-set-up -m "Deploy 2026-07-22: OTP login, report/receipt branding, Co-pilot presets, admin SMS credit"
```

Resolve any conflicts (there should be none if `main` hasn't diverged). Then:

```bash
git push origin main
```

> If you prefer to keep working on `backend-set-up` and only fast-forward `main`,
> that is fine too — the key is that `main` on the remote contains commits
> `a49cca4` and `d91ef98`.

---

## 3. On the VPS — pull, deps, migrate, build, restart (the easy path)

There is already a battle-tested redeploy script that does the whole sequence
**including the migrations**. SSH in as the `sahilpay` user and run it:

```bash
ssh sahilpay@<your-vps>
cd /var/www/sahilpay/app
git checkout main          # ensure the live checkout is on main
./deploy/update.sh
```

`deploy/update.sh` performs, in order:
1. `git pull --ff-only`
2. `pip install -r server/requirements.txt`
3. **`flask db upgrade`**  ← runs the two new migrations
4. `npm ci && npm run build` (frontend)
5. Publishes `client/dist` → `/var/www/sahilpay/client` (with a `.bak` rollback copy)
6. `systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat`
7. Health check against `https://sahilpay.co.ke/api/health`

If the script prints **"API healthy ✔ — deploy complete"**, the mechanical
deploy worked. Now go to **Step 5 (verification)** — do not skip it.

> If you'd rather run each step by hand (e.g. first deploy, or the script
> errors), use **Step 4** below instead, then **Step 5**.

---

## 4. Manual deploy (if not using update.sh) — DO NOT SKIP THE MIGRATION

```bash
ssh sahilpay@<your-vps>
cd /var/www/sahilpay/app
git checkout main
git pull --ff-only

# --- Backend deps ---
server/venv/bin/pip install -r server/requirements.txt

# --- DATABASE MIGRATIONS (the part you must not forget) ---
cd server
set -a && source .env && set +a        # loads DATABASE_URL etc. from the prod .env
venv/bin/flask db upgrade              # applies c1a2b3d4e5f6 then c2b3d4e5f6a7
venv/bin/flask db current              # MUST print: c2b3d4e5f6a7 (head)
cd ..

# --- Frontend build + publish ---
cd client
npm ci
npm run build
cd ..
rm -rf /var/www/sahilpay/client.bak
[ -d /var/www/sahilpay/client ] && mv /var/www/sahilpay/client /var/www/sahilpay/client.bak
cp -r client/dist /var/www/sahilpay/client

# --- Restart everything ---
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
sudo systemctl status sahilpay --no-pager | head -5
```

### The two migrations you are applying (Appendix A has full detail)
- **`c1a2b3d4e5f6`** — Co-pilot bank preset templates (idempotent data insert)
- **`c2b3d4e5f6a7`** — creates table **`sms_landlord_credits`**

After `flask db upgrade`, **`flask db current` must show `c2b3d4e5f6a7 (head)`**.
If it shows an older revision, the migrations did not run — re-run
`flask db upgrade` and read the error.

---

## 5. Post-deploy verification — prove each change actually works

Run these from the VPS (or any machine that can reach the API). Replace the
domain if different.

### 5a. Database — migrations landed
```bash
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
venv/bin/flask db current              # -> c2b3d4e5f6a7 (head)

# The new table exists:
psql "$DATABASE_URL" -c "\d sms_landlord_credits" | head

# The Co-pilot bank presets exist (expect rows for CO-OP BANK, NCBA, ABSA, etc.):
psql "$DATABASE_URL" -c "SELECT sender_id, name FROM sms_parser_templates ORDER BY sender_id;"
```

### 5b. Backend health + auth
```bash
curl -sf https://sahilpay.co.ke/api/health && echo "  <- API up"
```

### 5c. Tenant OTP login (the auth bug that's now fixed)
- In a browser: go to `https://sahilpay.co.ke/tenant/login`.
- Enter an **unregistered** email → you should see the red inline message
  *"This email address isn't registered as a tenant on Sahil Pay…"* (not a
  silent hang). ✔ verifies the not-registered fix.
- Enter a **real** tenant's email/phone → enter the OTP → you should land on
  **`/portal/dashboard`** with the tenant's balances (not a refresh loop). ✔
  verifies the `/api/auth/me` tenant-identity fix.

### 5d. Reports + receipts carry the landlord's logo/signature (biggest fix)
This is the "does the logo appear on reports" check.

1. Log in as a landlord who has uploaded a **logo** and **signature** in
   Settings → General. (If none, upload one first — see Step 7.)
2. Go to **Reports → Statements**, pick any report (e.g. Arrears), click
   **Generate**, then **Download PDF**.
3. Open the PDF: the landlord's **logo + company name + address** must appear in
   the letterhead and the **signature** at the bottom.
4. Go to **Payments**, open any confirmed payment, **Download receipt** — the
   receipt PDF must also carry the logo + signature.

Programmatic proof (optional, run on VPS) — counts embedded images in a report PDF:
```bash
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
venv/bin/python - <<'PY'
import io, logging; logging.disable(logging.WARNING)
from app import create_app; from extensions import db
from models import Landlord
from services.report_generators import build_arrears_report
from services.report_builder import render_document
from datetime import date
from pypdf import PdfReader
app = create_app()
with app.app_context():
    l = Landlord.query.filter(Landlord.logo_url.isnot(None)).first()
    if not l:
        print("No landlord has a logo yet — upload one, then re-run."); raise SystemExit
    pdf = render_document(build_arrears_report(l, None, date.today().isoformat()), "pdf")
    imgs = sum(len(list(p.images)) for p in PdfReader(io.BytesIO(pdf)).pages)
    print(f"Report PDF for '{l.company_name}': {len(pdf)} bytes, embedded images = {imgs}")
    print("PASS: logo/signature embed" if imgs >= 1 else "FAIL: no images embedded")
PY
```
Expect `embedded images = 2` (logo + signature) and **PASS**.

### 5e. Co-pilot tolerant parser + bank presets
- Admin portal → **Co-pilot → Templates**: confirm presets for **Co-op Bank,
  NCBA, Absa, Family Bank, DTB, Stanbic, I&M** (plus the existing KCB/Equity/M-Pesa).
- Admin → **Co-pilot → Templates → test console**: paste a real bank SMS (e.g.
  a KCB "credited"/"Reference" wording) and confirm it matches.

### 5f. Admin manual SMS credit (new feature + new table)
- Admin portal → **Landlords → (a landlord) → "Add SMS credit"**.
- Enter e.g. `100` and a reason like `M-Pesa 100 KES, code TEST` → Save.
- The landlord's **SMS balance** increases by 100 and an audit entry is written.
  (A 500 here means the `sms_landlord_credits` migration did not run — go back to
  Step 4.)

### 5g. Admin activate/deactivate + billing date (already existed — sanity check)
- Admin → Landlords → a landlord → **Suspend** (with reason) → status flips;
  **Reactivate** restores it; the billing modal can set the next billing date.

---

## 6. Uploads on local VPS storage (logo/signature/documents)

You are deliberately **not** using AWS S3 / Cloudinary yet. The app already
falls back to **local disk** and the report/receipt branding fix depends on that
folder being writable and served.

Verify on the VPS:
```bash
# The uploads dir must exist and be writable by the app user (sahilpay):
ls -ld /var/www/sahilpay/app/server/uploads
# If missing:
mkdir -p /var/www/sahilpay/app/server/uploads && chown sahilpay:sahilpay /var/www/sahilpay/app/server/uploads
```
- Uploaded files are stored under `server/uploads/...` and served by the
  `/uploads/<path>` route.
- A landlord uploading a logo in Settings → General should see it appear on the
  page and (per Step 5d) on their PDFs.

> When you later pay for AWS/Cloudinary: set `S3_BUCKET`,
> `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (+ optional `S3_REGION`,
> `S3_PUBLIC_BASE_URL`) in `server/.env` and restart. No code change needed — the
> same `upload_to_s3()` switches to real S3, and the PDF fetcher already handles
> both `/uploads/...` and full `https://` URLs.

---

## 7. Environment variables to confirm in prod `server/.env`

No **new** env vars were introduced today, but confirm these are set for the
features to behave in production:

```ini
APP_ENV=production
DATABASE_URL=postgresql+psycopg2://<user>:<pass>@localhost:5432/<db>

# SMS — real delivery ON in production:
FLUXSMS_API_KEY=<live key>
FLUXSMS_SENDER_ID=SAHILPAY
COMMS_SIMULATION_MODE=false      # false in prod so OTP/reminders actually send

# Email (SendGrid) — so email OTP + receipts send:
SENDGRID_API_KEY=<key>

# JWT / secrets:
SECRET_KEY=<...>
JWT_SECRET_KEY=<...>

# Storage: leave S3_* UNSET to use local /uploads (current plan)
```

> With `COMMS_SIMULATION_MODE=false`, real SMS are attempted. Remember the
> delivery caveat in Step 9.

---

## 8. Smoke-test checklist (tick before calling it done)

- [ ] `flask db current` → `c2b3d4e5f6a7 (head)`
- [ ] `sms_landlord_credits` table exists
- [ ] Bank preset templates present (Co-op/NCBA/Absa/Family/DTB/Stanbic/I&M)
- [ ] `GET /api/health` → 200
- [ ] Tenant OTP: unregistered → clear 404 message; real → lands on dashboard
- [ ] Landlord report PDF shows logo + signature
- [ ] Landlord receipt PDF shows logo + signature
- [ ] Admin "Add SMS credit" works (balance +, audit written)
- [ ] `server/uploads` writable by `sahilpay` user
- [ ] `sudo systemctl status sahilpay sahilpay-celery sahilpay-celerybeat` all active
- [ ] Frontend loads and shows the new "Add SMS credit" button on admin LandlordDetail

---

## 9. Known non-deploy item: SMS delivery

The SMS pipeline code is correct and the FluxSMS API accepts the send, but
Safaricom's delivery report stalls at `SentToNetwork` — the signature of an
**unapproved / throttled alphanumeric sender ID**.

**Action (with FluxSMS, not a deploy step):** confirm that `SAHILPAY` is a
registered and **approved transactional sender ID** on the Safaricom route.
Until then, SMS may be delayed or dropped even though the backend logs "sent".
Email OTP is unaffected.

---

## 10. Rollback

If something is wrong after deploy:

```bash
# Frontend: restore previous build
sudo rm -rf /var/www/sahilpay/client
sudo mv /var/www/sahilpay/client.bak /var/www/sahilpay/client

# Code: check out the previous main commit
cd /var/www/sahilpay/app && git log --oneline -5
git checkout <previous-good-commit>
server/venv/bin/pip install -r server/requirements.txt
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
```

> **Database rollback is possible but rarely needed.** Both new migrations have
> working `downgrade()`:
> ```bash
> cd server && set -a && source .env && set +a
> venv/bin/flask db downgrade b3c4d5e6f7a8   # undoes both today's migrations
> ```
> `c2b3d4e5f6a7` down = drops `sms_landlord_credits` (loses manual-credit history).
> `c1a2b3d4e5f6` down = removes the bank preset templates.
> Only downgrade if you are also rolling code back to before these features.

---

## Appendix A — the two migrations in detail

**Order (linear, no branches):**
```
… b3c4d5e6f7a8  (previous prod head)
   └─ c1a2b3d4e5f6  Co-pilot bank preset templates      (server/migrations/versions/c1a2b3d4e5f6_copilot_bank_preset_templates.py)
        └─ c2b3d4e5f6a7  Per-landlord SMS-credit ledger  (server/migrations/versions/c2b3d4e5f6a7_sms_landlord_credit_ledger.py)   ← head
```

**`c1a2b3d4e5f6` — Co-pilot bank preset templates**
- Pure data migration. Inserts tolerant parser templates for Co-op, NCBA, Absa,
  Family Bank, DTB, Stanbic, I&M and an extra M-Pesa till format.
- **Idempotent**: each row is inserted only if a template with the same
  (name, sender_id) doesn't already exist — safe to re-run.
- `downgrade()` deletes exactly those rows.

**`c2b3d4e5f6a7` — Per-landlord SMS-credit ledger**
- Schema migration. Creates table **`sms_landlord_credits`**:
  `id, landlord_id (FK), admin_user_id (FK), credits_added (signed int),
  balance_after (int), reason (str, required), created_at` + two indexes.
- Backs the admin "Add SMS credit" feature (audited, reversible manual credits).
- `downgrade()` drops the table and its indexes.

**Apply both:** `flask db upgrade` (from `server/`, with the env loaded).
**Confirm:** `flask db current` → `c2b3d4e5f6a7 (head)`.

---

## Appendix B — files changed today (for reference / review)

Backend:
- `server/routes/auth_routes.py` — `/me` tenant identity handling
- `server/routes/otp_routes.py` — not-registered 404
- `server/routes/payment_routes.py` — receipt download → branded service
- `server/routes/admin_sms_routes.py` — SMS-credit endpoints
- `server/services/copilot_service.py` — tolerant parser
- `server/services/sms_service.py` — message_id + DLR logging
- `server/utils.py` — `render_pdf` local-uploads URL fetcher (the branding fix)
- `server/models.py` — `SmsLandlordCredit` model
- `server/seed.py` — bank presets in seed (fresh DBs)
- `server/simulate_5months.py` — cleanup fix (repeatable 5-month sim harness)
- `server/tests/test_demo_mode.py` — OTP 404 expectation
- `server/migrations/versions/c1a2b3d4e5f6_*.py`, `c2b3d4e5f6a7_*.py` — the two migrations

Frontend:
- `client/src/features/auth/TenantOtpLogin.jsx` — surfaces not-registered message
- `client/src/features/admin/LandlordDetail.jsx` — "Add SMS credit" modal + SMS balance card
- `client/src/features/admin/adminSmsApiSlice.js` — credit mutation/query

Config:
- `.mcp.json` — pinned Playwright MCP `@0.0.77`, de-isolated
