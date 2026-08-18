# Deploying this release

Everything you need to do, in the order to do it, with the reason for each step.

This release contains **12 database migrations**, a **build-step change**, **two
environment-variable changes**, and **one setting you must change in SendGrid** —
which is what was breaking every link in every email.

**Estimated time:** 20–30 minutes, plus DNS propagation if you choose Option B in
Step 1.

> Throughout: `sahilpay@server` means run it on the production server as the
> `sahilpay` user. `local` means your own machine.

---

## Step 0 — Before you touch anything: take a backup

The migrations change data, not just structure. Two of them rewrite existing
rows (marking accounts verified, and switching every landlord's report basis).
Those are safe and deliberate, but a backup is what makes them reversible.

```bash
# sahilpay@server
pg_dump -Fc sahilpay > ~/sahilpay-before-release-$(date +%F-%H%M).dump
ls -lh ~/sahilpay-before-release-*.dump    # confirm it is not 0 bytes
```

**Do not continue until you see a file with a real size.** If restoring is ever
needed:

```bash
pg_restore --clean --if-exists -d sahilpay ~/sahilpay-before-release-<stamp>.dump
```

---

## Step 1 — Fix the broken email links (do this first, it needs no deploy)

### What was wrong

A team member clicked **"Log in to Sahil Pay"** in their invitation and got:

```
url5446.sahilpay.co.ke
DNS_PROBE_FINISHED_NXDOMAIN
```

That hostname is not ours and never was. **SendGrid's click tracking** was
rewriting every link in every email onto a branded tracking subdomain
(`urlNNNN.sahilpay.co.ke`) so it could count clicks. The DNS record for that
subdomain was never created, so the browser could not resolve it.

Nothing was wrong with the application. The links simply never reached it.

It looked plausible because the rewritten host still ends in `sahilpay.co.ke`,
and because SendGrid reports the send as successful — so neither the screenshot
nor our logs pointed at the cause.

This affected **every link in every email**: verification, password reset, team
invitations, document links.

### Choose one option

**Option A — turn click tracking off (recommended).**

You lose click statistics on transactional mail, which is not worth anything:
nobody optimises the click-through rate of a password reset. You gain links that
always work, and that a recipient can visually verify point at `sahilpay.co.ke`
before clicking — which matters for mail that carries credentials.

1. Sign in to SendGrid.
2. Go to **Settings → Tracking**.
3. Switch **Click Tracking** to **OFF**.
4. Switch **Open Tracking** to **OFF** as well — it embeds an invisible remote
   image in every email, which makes receipts trigger "images blocked" warnings.

**Option B — keep click tracking and make the domain resolve.**

Only if you genuinely want click analytics.

1. SendGrid → **Settings → Sender Authentication → Link Branding**.
2. Start the setup for `sahilpay.co.ke`. SendGrid gives you 2–3 **CNAME**
   records.
3. Add every one of them at your DNS provider (Cloudflare, per
   `CLOUDFLARE_SETUP.md`). **Set them to "DNS only" / grey cloud — not proxied.**
   A proxied CNAME breaks SendGrid's verification.
4. Wait for propagation, then click **Verify** in SendGrid.
5. Confirm it resolves before trusting it:
   ```bash
   dig +short url5446.sahilpay.co.ke      # must return something
   ```

### The code side (already done, ships in this release)

Regardless of which option you pick, the app now tells SendGrid **per message**
not to rewrite links. This overrides the dashboard, so one accidental toggle
cannot silently break every login link again.

There was also a **second, unrelated broken-link bug** found while checking the
rest: document emails rendered a *relative* URL (`/uploads/leases/1/a.pdf`).
Email clients have no base URL, so that link could never work. Now absolute.

Both are covered by tests that name the exact failure, so neither can come back.

---

## Step 2 — Pull the code

```bash
# sahilpay@server
cd /var/www/sahilpay/app
git fetch origin
git checkout backend-set-up
git pull origin backend-set-up
git log --oneline -3          # confirm you have the release commits
```

---

## Step 3 — Backend dependencies

```bash
# sahilpay@server
cd /var/www/sahilpay/app/server
source venv/bin/activate
pip install -r requirements.txt
```

No new packages were added this release, but running it costs seconds and rules
out a stale environment.

---

## Step 4 — Environment variables

Edit `/var/www/sahilpay/app/server/.env`.

### 4a. Require email verification

```ini
ENFORCE_EMAIL_VERIFICATION=true
```

Landlords, property managers, **team members** and affiliates must now confirm
their email before their first sign-in. Tenants are exempt — they sign in with a
phone OTP, and most have no email on file.

**This will not lock anyone out.** Migration `v1a1b2c3d4e5` marks every existing
active account as verified, because they were all created under rules that never
required the click.

### 4b. Confirm the frontend URL

```bash
grep FRONTEND_URL /var/www/sahilpay/app/server/.env
# must be exactly:  FRONTEND_URL=https://sahilpay.co.ke
```

Every link in every email is built from this. If it is wrong or missing, the
links point somewhere that does not exist — the same symptom as Step 1, from a
different cause.

### 4c. Confirm real sending is on

```bash
grep COMMS_SIMULATION_MODE /var/www/sahilpay/app/server/.env
# production must be:  COMMS_SIMULATION_MODE=false
```

`true` means emails and SMS are only written to the log. Correct for staging,
silent failure in production.

---

## Step 5 — Run the migrations

```bash
# sahilpay@server
cd /var/www/sahilpay/app/server
source venv/bin/activate
APP_ENV=production flask db current      # note this down — your rollback point
APP_ENV=production flask db upgrade
APP_ENV=production flask db current      # should now read: ad1b2c3d4e5f (head)
```

### What each migration does

| Revision | What it does | Touches existing data? |
|---|---|---|
| `v1a1b2c3d4e5` | Password resets get their own token column; **marks existing active accounts verified** | **Yes** — see below |
| `w1a1b2c3d4e5` | Adds `receipt_emailed_at`; **backfills confirmed payments as already receipted** | **Yes** — see below |
| `x1a1b2c3d4e5` | Adds `notifications`, `leases`, `penalties` permission modules and backfills them | Yes, additive only |
| `y1a1b2c3d4e5` | **Switches every landlord's report "gross" to rent-only** | **Yes** — see below |
| `z1a1b2c3d4e5` | Grants existing caretakers `properties: view` | Yes, additive only |
| `aa1b2c3d4e5f` | New `maintenance_comments` table | No |
| `ab1b2c3d4e5f` | Per-report permissions; narrows **owner** logins to the property statement | Yes, owners only |
| `ac1b2c3d4e5f` | New `import_mappings` table | No |
| `ad1b2c3d4e5f` | New `queued_charges` table | No |

**Three of these deserve your attention:**

- **`v1a1b2c3d4e5`** marks existing accounts verified. Without it, turning on
  Step 4a would lock out your entire user base at once — including you.
- **`w1a1b2c3d4e5`** marks historical payments as already receipted, so no later
  process can email thousands of duplicate receipts for payments settled months
  ago.
- **`y1a1b2c3d4e5`** changes what "Gross" means on every property statement. See
  Step 9 — **this one changes numbers your clients read.**

---

## Step 6 — Build the frontend **with prerendering**

> **This is the step most likely to be got wrong.** The build command has
> changed.

```bash
# sahilpay@server
cd /var/www/sahilpay/app/client
npm ci
npm run build:seo            # NOT "npm run build"
```

`npm run build` produces the app but **skips the prerender**, and your public
pages stay invisible to every crawler that does not run JavaScript — including
WhatsApp, Facebook and LinkedIn link previews, which is how this product
spreads.

You should see, at the end:

```
prerendered 9/9 public pages
```

If it says fewer than 9, or fails, **stop and investigate** — a half-prerendered
site is worse than none, because nobody notices until a shared link looks wrong.

The prerender needs a headless browser on the server:

```bash
npx playwright install --with-deps chromium     # once, if it is not present
```

Then publish:

```bash
sudo rsync -a --delete /var/www/sahilpay/app/client/dist/ /var/www/sahilpay/client/
sudo chown -R www-data:www-data /var/www/sahilpay/client
```

---

## Step 7 — Update nginx

The config changed so that prerendered pages are not cached. Each one references
hashed asset filenames that change every deploy; a cached copy keeps asking for
files the new build deleted, which shows as a blank page for anyone who visited
before the release.

```bash
# sahilpay@server
sudo cp /var/www/sahilpay/app/deploy/nginx/sahilpay.conf /etc/nginx/sites-available/sahilpay.conf
sudo nginx -t                 # must say "syntax is ok" and "test is successful"
sudo systemctl reload nginx
```

**If `nginx -t` fails, do not reload.** Fix it first — a reload with a bad config
takes the site down.

---

## Step 8 — Restart the services

Restart **both**. The Celery worker sends every email and runs the monthly
billing; if it keeps running old code it will not consume the new invoice queue.

```bash
# sahilpay@server
sudo systemctl restart sahilpay
sudo systemctl restart sahilpay-celery
sudo systemctl restart sahilpay-celerybeat

sudo systemctl status sahilpay sahilpay-celery --no-pager | head -30
```

---

## Step 9 — Tell your clients about the one number that changed

**Do not skip this.** Migration `y1a1b2c3d4e5` changes a figure your clients
read.

**Before:** "Gross" on a property statement meant *every* income shilling
collected — rent plus water, garbage, security and penalties.

**After:** "Gross" means **rent collected** (current month + arrears paid).
Everything else appears on its own line beneath it.

Deposits were already excluded from both, and still are — a deposit is the
tenant's money, held and refundable, and is never income.

**Why:** on a property statement, "Gross" is the number an owner reads as *"what
my block earned in rent"*, and folding utility income into it overstates that.

**What an owner will notice:** their gross figure drops, and the difference now
appears as a separate line. The total collected is unchanged — only its
presentation.

**If a particular landlord wants the old behaviour**, they can set it themselves:
**Reports → gross basis → "All collections"**. The choice is saved per landlord.

I would send a short note to any client who reads these statements monthly,
before they notice it themselves.

---

## Step 10 — Verify the deployment

### 10a. The email links — the thing that was broken

```bash
# local, or any machine
# Trigger a real invitation: create a test team member in Settings → Team.
```

Then, in the email you receive:

1. **Hover over "Verify my email & log in" without clicking.**
2. The status bar must show `https://sahilpay.co.ke/verify-email/...`
3. It must **not** show `url5446.sahilpay.co.ke` or anything containing
   `sendgrid`.
4. Now click it. You should land on the app and be able to sign in.

**If you still see a `urlNNNN.` link**, Step 1 has not taken effect: either the
SendGrid dashboard setting was not saved, or the Celery worker was not restarted
(it is the process that sends mail).

### 10b. Everything else

```bash
# sahilpay@server
curl -s -o /dev/null -w "%{http_code}\n" https://sahilpay.co.ke/api/health   # 200
curl -s https://sahilpay.co.ke/pricing | grep -c "Pricing"                   # > 0
```

That second command is the prerender check: it fetches the page **without
running JavaScript**, exactly as a crawler does. A `0` means Step 6 did not take.

In a browser:

- Sign in as yourself → the dashboard loads.
- **Settings → Team** → open a member → the permission matrix shows plain-English
  labels and, under Reports, a list of individual report checkboxes.
- **Bulk import** appears in the sidebar.
- **Invoices** has a "Waiting to be billed" tab.
- **Owner payouts** is one entry with two tabs (Runs / Ledger).

---

## Rolling back

If something is badly wrong:

```bash
# sahilpay@server
cd /var/www/sahilpay/app
git checkout <previous-commit>
cd server && source venv/bin/activate
APP_ENV=production flask db downgrade <the revision you noted in Step 5>
cd ../client && npm run build:seo
sudo rsync -a --delete dist/ /var/www/sahilpay/client/
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
```

Two honest caveats about downgrading:

- **`v1a1b2c3d4e5` does not un-verify accounts on the way down.** Deliberate:
  un-verifying people who have since confirmed for real would lock them out,
  which is worse than leaving them verified.
- **Dropping `queued_charges` or `maintenance_comments` destroys their contents.**
  If anything real has been queued or any notes written, export those tables
  first.

For anything short of a disaster, prefer restoring the Step 0 dump over a
partial downgrade.

---

## Quick reference

```bash
# On the server, in order:
pg_dump -Fc sahilpay > ~/backup-$(date +%F).dump
cd /var/www/sahilpay/app && git pull origin backend-set-up
cd server && source venv/bin/activate && pip install -r requirements.txt
nano .env                                   # ENFORCE_EMAIL_VERIFICATION=true
APP_ENV=production flask db upgrade
cd ../client && npm ci && npm run build:seo # NOT npm run build
sudo rsync -a --delete dist/ /var/www/sahilpay/client/
sudo cp ../deploy/nginx/sahilpay.conf /etc/nginx/sites-available/sahilpay.conf
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
```

**And in SendGrid, separately:** Settings → Tracking → Click Tracking **OFF**.

---

## The five things that will bite you if skipped

1. **SendGrid click tracking still on** → every email link stays broken. This is
   a dashboard change; no deploy fixes it on its own.
2. **`npm run build` instead of `npm run build:seo`** → public pages invisible to
   crawlers and link previews.
3. **Celery not restarted** → old code keeps sending mail and running billing.
4. **No backup before migrating** → three migrations rewrite existing rows.
5. **Not telling clients about the gross change** → an owner spots a lower number
   on their statement and assumes money is missing.
