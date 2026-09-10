# Sahil Pay — Redeploy: September 2026 release

Step by step, for the release that replaces SendGrid with Resend and adds the
receipt/branding, search and totals work.

**Read §1 first.** There is one environment change that will stop the app
booting if you skip it, and one that will silently stop all customer email if
you get it wrong.

---

## 0. What is in this release

| # | Change | Needs a VPS action? |
|---|---|---|
| 1 | **SendGrid → Resend** | **YES — §1.** The app will not start without `RESEND_API_KEY`. |
| 2 | Logo & signature uploads actually work (they never left the browser before) | No |
| 3 | Receipt paper sizes reflow properly; thermal no longer prints on A4 | No |
| 4 | Document theme colours (36-colour palette, receipts **and** reports) | Migration — automatic |
| 5 | Signature persists to Cloudinary and appears on receipts + reports | No |
| 6 | Account profile fields save | No |
| 7 | SMS per-landlord margin maths verified | No |
| 8 | Search bars on every list | No |
| 9 | Card totals read the whole dataset, not the current page | No |
| 10 | `number_of_units` derived from real units + **backfill of existing data** | Migration — automatic |
| 11 | Every dropdown searchable and scrollable | No |

Two new migrations run automatically as part of `deploy/update.sh`:

```
ag1b2c3d4e5f -> b4e2546695a4   landlord document theme colours
b4e2546695a4 -> 10aaeeb9b8d4   backfill derived property unit counts
```

`10aaeeb9b8d4` is a **data migration** — it corrects `properties.number_of_units`
for every property already in the database. This is what fixes the imported
properties that all read "0 units".

---

## 1. The `.env` changes on the VPS

SSH in and open the production env file:

```bash
ssh sahilpay@YOUR_SERVER_IP
cd /var/www/sahilpay/app/server
cp .env .env.backup-$(date +%F)     # do this first
nano .env
```

### 1a. REMOVE the SendGrid line

```diff
- SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxxx
```

Nothing reads it any more. Leaving it is harmless but misleading.

### 1b. ADD the Resend key — **required, the app will not boot without it**

```bash
RESEND_API_KEY=re_your_key_here

```

`config.py::ProductionConfig._validate` calls `_require("RESEND_API_KEY")`. If
it is missing, the service exits at startup with:

```
RuntimeError: [SahilPay] Required environment variable 'RESEND_API_KEY' is missing
```

> **🔑 Rotate this key.** It was pasted into a chat. After the deploy is
> verified, create a fresh key at **resend.com → API Keys**, put the new value
> in `.env`, `sudo systemctl restart sahilpay sahilpay-celery`, then revoke the
> old one in Resend.

### 1c. CHECK `EMAIL_TEST_ALLOWLIST` is absent or blank

```bash
grep EMAIL_TEST_ALLOWLIST .env
```

It must return **nothing**, or a line with **no value**:

```bash
EMAIL_TEST_ALLOWLIST=
```

**If this is set in production, every email to anyone not on the list is
silently dropped.** It is a development-only guard so a dev machine pointed at
a seeded database cannot mail a real person. It does not belong on the VPS.

### 1d. CONFIRM these are unchanged

```bash
MAIL_DEFAULT_SENDER=noreply@sahilpay.co.ke
MAIL_DEFAULT_SENDER_NAME=SahilPay
COMMS_SIMULATION_MODE=false          # MUST be false or nothing sends at all
ENFORCE_EMAIL_VERIFICATION=true
FIELD_ENCRYPTION_KEY=<already set>   # also required; app won't boot without it
```

### 1e. The full list of variables production refuses to start without

```
SECRET_KEY
DATABASE_URL
JWT_SECRET_KEY
REDIS_URL
RESEND_API_KEY                 <-- NEW in this release
FIELD_ENCRYPTION_KEY
PLATFORM_DARAJA_CONSUMER_KEY
PLATFORM_DARAJA_PASSKEY        (only when MPESA_SIMULATION_MODE=false)
```

Check them all in one go before deploying:

```bash
cd /var/www/sahilpay/app/server
for k in SECRET_KEY DATABASE_URL JWT_SECRET_KEY REDIS_URL RESEND_API_KEY \
         FIELD_ENCRYPTION_KEY PLATFORM_DARAJA_CONSUMER_KEY; do
  v=$(grep -E "^$k=" .env | cut -d= -f2-)
  [ -n "$v" ] && echo "OK      $k" || echo "MISSING $k"
done
echo "--- must be blank/absent ---"
grep -E "^EMAIL_TEST_ALLOWLIST=." .env && echo "PROBLEM: allowlist is set" \
  || echo "OK      EMAIL_TEST_ALLOWLIST is not set"
```

**No DNS changes are needed.** Resend's records are already live and verified:
`resend._domainkey` (DKIM), `send.sahilpay.co.ke` (SPF), `_dmarc`.

---

## 2. Deploy

```bash
cd /var/www/sahilpay/app
./deploy/update.sh
```

That script pulls, installs dependencies, **runs the migrations**, builds the
frontend, prerenders the public pages, publishes the build, and restarts
`sahilpay`, `sahilpay-celery` and `sahilpay-celerybeat`. It finishes with a
health check.

Watch for these lines:

```
==> Backend: dependencies + migrations
    Running upgrade ag1b2c3d4e5f -> b4e2546695a4, landlord document theme colours
    Running upgrade b4e2546695a4 -> 10aaeeb9b8d4, backfill derived property unit counts
==> Frontend: SEO prerender (optional)
    prerendered ✔            <-- if this says SKIPPED, see §6
==> Health check
API healthy ✔ — deploy complete
```

### If Cloudflare is in front of the site

After the deploy: **Cloudflare dashboard → Caching → Configuration → Purge
Everything.** Otherwise visitors keep getting the previous frontend build.

---

## 3. Verify email — do this before anything else

Email is the change with the widest blast radius: if it is broken, nobody can
register, reset a password, or receive a receipt, **and nothing in the logs
looks wrong**, because a failed send is deliberately swallowed so it cannot fail
the payment that triggered a receipt.

```bash
cd /var/www/sahilpay/app/server
source venv/bin/activate
python - <<'PY'
from app import app
from services import email_service as es
with app.app_context():
    print("tracking/domain:", es.assert_tracking_disabled())
    print("send:", es._send_email("swallehmtawazo@gmail.com",
                                  "Sahil Pay — production deploy check",
                                  "<p>Production is live on Resend.</p>"))
PY
```

Expected:

```
tracking/domain: {'ok': True, 'domains': [{'name': 'sahilpay.co.ke', 'status': 'verified',
                  'click_tracking': False, 'open_tracking': False}], 'error': None}
send: True
```

Then **open the email** and confirm three things:

1. It is in **Inbox**, not Spam.
2. The link in it points at `sahilpay.co.ke` — not `url1234.sahilpay.co.ke` or
   any other host.
3. It is not marked "via" some other domain.

If `click_tracking` or `open_tracking` comes back `True`, turn it off in the
Resend dashboard immediately (**Domains → sahilpay.co.ke → Settings**). Resend
has no per-message override, so this is the only thing standing between your
verification links and being rewritten onto a tracking host. That exact failure
has already happened once under SendGrid.

---

## 4. Verify the rest

Sign in as a real landlord account and check, in this order:

**Branding (items 2, 3, 4, 5)**
1. Settings → General → upload a logo → **Save**. The field should then show the
   stored image with *"Saved — this is what appears on your documents."*
   *(Logo must be wide, dark, 600–1200px — see `BRAND_ASSETS_REQUIREMENTS.md`.
   A white logo on transparency is flattened onto white and disappears.)*
2. Settings → Account → upload a signature → **Save account**.
3. Settings → Receipt layout & document colours → pick a paper and two colours →
   **Update preview**. The preview is a real PDF from the real renderer.
4. Download a tenant receipt and any report. Both must carry the logo, the
   signature and both colours.

**Scale (items 8, 9, 10, 11)**

5. Properties / Units / Tenants / Expenses / Payments — each has a search box;
   typing filters and the cards above the table follow the filter.
6. Properties — the unit counts are real numbers, not 0.
7. Open any dropdown — it has a search box and scrolls.

**SMS (item 7)**

8. Admin → SMS Management → a landlord's row → set a rate per credit. The margin
   updates live. Setting one below cost requires ticking the confirmation.

---

## 5. Rollback

The migrations are reversible, but note that `10aaeeb9b8d4`'s downgrade is a
**no-op on purpose** — the old `number_of_units` values were drift, not a state
worth restoring.

```bash
cd /var/www/sahilpay/app

# Code
git log --oneline -5
git reset --hard <previous-commit-sha>

# Database — only if you must go back past the schema change
(cd server && set -a && source .env && set +a && venv/bin/flask db downgrade ag1b2c3d4e5f)

# Frontend — update.sh keeps the previous build
sudo rm -rf /var/www/sahilpay/client
sudo mv /var/www/sahilpay/client.bak /var/www/sahilpay/client

sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
```

Restore `.env` from the backup made in §1 and put `SENDGRID_API_KEY` back if you
roll back past this release — the old code requires it.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Service won't start, `RESEND_API_KEY is missing` | §1b skipped | Add the key, `sudo systemctl restart sahilpay` |
| Service won't start, `FIELD_ENCRYPTION_KEY is missing` | Pre-existing gap | Add it; it must be a Fernet key |
| **No emails arrive at all, no errors in the log** | Missing `User-Agent` on the Resend call, or `EMAIL_TEST_ALLOWLIST` set | See below |
| Emails land in Spam | Tracking turned on in the Resend dashboard | Turn it off; re-run §3 |
| Frontend looks unchanged | Cloudflare cache | Purge Everything |
| `prerendered SKIPPED` | Headless Chromium not installed | `cd client && npx playwright install --with-deps chromium` |
| Receipt prints small with white margins | Printer set to "Fit to page" | Print at **Actual size / 100%** |
| Logo uploads but doesn't appear | White/pale logo flattened onto white | Upload the dark version |

### The silent-email trap, in detail

Resend sits behind Cloudflare, which **rejects Python's default `urllib`
User-Agent** with `403 / error code: 1010` before the request ever reaches
Resend. The API key is irrelevant; every call fails identically, and because
`_send_email` swallows errors by design, it fails **silently**.

`services/email_service.py` sends an explicit `User-Agent` for exactly this
reason, pinned by `test_a_custom_user_agent_is_sent`. **Do not remove it**, and
do not swap `urllib` for anything that sets a default Python User-Agent.

To tell the two silent causes apart:

```bash
sudo journalctl -u sahilpay -u sahilpay-celery -n 200 | grep -i "EMAIL\|resend\|403"
```

* `EMAIL [blocked by EMAIL_TEST_ALLOWLIST]` → §1c, remove the allowlist.
* `_send_email failed ... HTTP 403 ... 1010` → the User-Agent header is gone.
* `EMAIL [simulated — not sent]` → `COMMS_SIMULATION_MODE` is not `false`.

---

## 7. Related documents

| Document | What it covers |
|---|---|
| `EMAIL_RESEND_SETUP.md` | Resend in full — DNS, deliverability, the tracking check |
| `BRAND_ASSETS_REQUIREMENTS.md` | Logo/signature specs, receipt sizes, theme colours |
| `SCALE_AND_SEARCH_NOTES.md` | Search, card totals, unit counts, dropdowns, SMS margins |
| `DEPLOYMENT_GUIDE.md` | First-time VPS setup from scratch |
| `DEPLOY_RUNBOOK.md` | The general (non-release-specific) runbook |
| `CLOUDFLARE_SETUP.md` | Cloudflare settings |
