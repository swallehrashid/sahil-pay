# Deploying Sahil Pay

Merge `backend-set-up` into `main`, then deploy `main`. Every step below, in
order, with the reason for each — because the reason is what tells you whether a
failure matters.

> **Conventions.** `local` = your own machine. `server` = run it on the
> production box as the `sahilpay` user. Paths assume the standard layout:
> code at `/var/www/sahilpay/app`, published frontend at `/var/www/sahilpay/client`.

---

## What is in this deployment

Five reported faults, fixed and verified end-to-end in a browser from the
landlord, team-member and tenant portals.

| # | The report | What was actually wrong |
|---|---|---|
| 1 | Lease is sent but never reaches the tenant | Sending never retired earlier agreements, so a tenancy accumulated unsigned leases; after an approval the portal showed a stale one and hid the download for the lease just signed. Sending also sent **no notification at all**, and on a phone the Lease link was an unlabelled icon scrolled off the nav. |
| 2 | Tenant-side communications not working | The tenant↔landlord thread was fine. **Outbound SMS was blocked because the platform SMS pool is empty**, logged as a bare "Failed" while the sender was shown a green "Sent to 1 recipient". |
| 3 | Tenant maintenance photos never reach the office | The `File` was posted inside a JSON body. `JSON.stringify` turns a File into `{}`, so the photo was dropped **in the browser**; the API stored `image_url = NULL` and nothing errored on either side. The landlord form had the same bug, and the update route could not accept a photo at all. |
| 4 | Payout statement button does nothing | It called `window.open('/api/payouts/N/statement.pdf')` — the app's own origin, not the API, and a popup carries no auth header. It opened the SPA's 404 page. The endpoint itself was always fine. |
| 5 | No control over what "Collected" means | New: a charge-type picker (rent locked on, everything else optional) and a Rent-only / Total-collected commission toggle, both recorded on each payout and named on its statement. |

**Ships with:** 3 database migrations, no new dependencies, no nginx change, no
environment-variable change.

**Requires one manual action that no deploy can do for you:** topping up the SMS
pool (Step 8). Without it, fault #2 stays broken — you will simply get a clear
error instead of a silent one.

---

## Step 0 — Merge the branch into main

Do this locally, and verify before you merge rather than after.

```bash
# local
cd /home/swalleh/Projects/sahil-pay
git checkout backend-set-up
git pull origin backend-set-up

# The gate. All three must pass before the merge.
cd server && source venv/bin/activate
APP_ENV=testing python -m pytest tests/ -q --ignore=tests/render_email_previews.py
# expect: 715 passed

cd ../client
npx vite build            # must succeed
npx eslint src            # expect: 22 problems — see the note below
```

> **About those 22 lint problems.** They are pre-existing `set-state-in-effect`
> warnings in screens this work did not touch. The baseline was 24; two were
> fixed here. **Do not treat a non-zero count as a failed gate** — treat *more
> than 22* as one.

Then merge and push:

```bash
# local
git checkout main
git pull origin main
git merge backend-set-up
git push origin main
```

If the merge reports conflicts, stop and resolve them deliberately. `main` is
several releases behind this branch (see Step 2), so a clean fast-forward is the
expected outcome, and a conflict means something landed on `main` directly.

---

## Step 1 — Back up the database

Migration `ae1b2c3d4e5f` **rewrites existing rows**. That is deliberate and
correct, and a backup is what makes it reversible.

```bash
# server
pg_dump -Fc sahilpay > ~/sahilpay-before-$(date +%F-%H%M).dump
ls -lh ~/sahilpay-before-*.dump          # confirm a real size, not 0 bytes
```

**Do not continue until you see a file with a real size.** To restore:

```bash
pg_restore --clean --if-exists -d sahilpay ~/sahilpay-before-<stamp>.dump
```

---

## Step 2 — Find out what production is actually running

This decides how big the deployment is, and it takes ten seconds. Guessing here
is how people run twenty migrations expecting three.

```bash
# server
cd /var/www/sahilpay/app/server
source venv/bin/activate
APP_ENV=production flask db current      # WRITE THIS DOWN — it is your rollback point
```

**If it reads `ad1b2c3d4e5f`** — the previous release is already live. This is a
small deployment: 3 migrations, no new dependencies. Follow every step below as
written.

**If it reads anything older** — production is behind by more than this release.
Merging to `main` brings **23 migrations**, new Python packages (`pyotp`,
`cryptography`, `qrcode`), a changed frontend build command, and several
behaviour changes with client-visible consequences. **Stop and read
`DEPLOY_THIS_RELEASE.md` first** — it covers migrations `v1a1b2c3d4e5` through
`ad1b2c3d4e5f`, including the mandatory-email-verification switch and the report
"gross" change, neither of which is repeated here. Do that release's steps, then
come back to this one.

Also confirm which branch the working copy is on — the previous runbook checked
out `backend-set-up` directly:

```bash
# server
cd /var/www/sahilpay/app && git branch --show-current
```

---

## Step 3 — Pull main

```bash
# server
cd /var/www/sahilpay/app
git fetch origin
git checkout main            # from `backend-set-up`, if that is where it was
git pull origin main
git log --oneline -3         # confirm the merge commit is here
```

---

## Step 4 — Backend dependencies

```bash
# server
cd /var/www/sahilpay/app/server
source venv/bin/activate
pip install -r requirements.txt
```

This release adds none. Run it anyway — it costs seconds and rules out a stale
environment, and if you arrived here from the "older" branch of Step 2 it is
doing real work (`pyotp`, `cryptography`, `qrcode`).

---

## Step 5 — Run the migrations

```bash
# server
cd /var/www/sahilpay/app/server
source venv/bin/activate
APP_ENV=production flask db upgrade
APP_ENV=production flask db current      # should now read: ag1b2c3d4e5f (head)
```

### What each one does

| Revision | What it does | Rewrites existing rows? |
|---|---|---|
| `ae1b2c3d4e5f` | Retires lease agreements a newer one already replaced | **Yes — read below** |
| `af1b2c3d4e5f` | Adds `included_categories`, `commission_basis`, `commission_base` to `owner_payouts` | No — nullable, no backfill |
| `ag1b2c3d4e5f` | Adds `failure_reason` to `communication_logs` | No — nullable, no backfill |

**`ae1b2c3d4e5f` is the one to understand.** Preparing a lease looks, to a
landlord, like it did nothing — the next move belongs to the tenant, so the
screen just says "With the tenant". The natural response is to press Prepare
again, and every press left another agreement stuck in `sent` forever. The
tenant portal answers "what must I sign?" with the newest un-actioned lease, so
the moment anything was approved the tenant was shown a *different* blank
agreement and lost the download for the one they had just signed.

The migration marks those stale rows `superseded`. It is deliberately
conservative:

- the **newest** outstanding lease per tenancy is left alone — it is most likely
  the one genuinely awaiting a signature, and retiring it would take a real
  agreement off a tenant's screen;
- **nothing signed is touched.** `submitted` and `approved` rows are outside its
  reach entirely. A signature is evidence, not clutter.

To see what it will affect before you run it:

```bash
# server — read-only, safe to run any time
psql -d sahilpay -c "
SELECT stale.tenant_id, stale.id, stale.status, stale.created_at
  FROM lease_agreements stale
  JOIN lease_agreements newer
    ON newer.tenant_id = stale.tenant_id AND newer.id <> stale.id
   AND (newer.created_at, newer.id) > (stale.created_at, stale.id)
 WHERE stale.status IN ('draft','sent','rejected')
 ORDER BY stale.tenant_id, stale.created_at;"
```

Every row listed becomes `superseded`, and shows in the Leases list as
**"Replaced"**.

---

## Step 6 — Build and publish the frontend

```bash
# server
cd /var/www/sahilpay/app/client
npm ci
npm run build:seo            # NOT "npm run build"
```

`npm run build` produces the app but **skips the prerender**, leaving your public
pages invisible to every crawler that does not run JavaScript — including
WhatsApp, Facebook and LinkedIn link previews.

You should see `prerendered 9/9 public pages` at the end. Fewer than 9, or a
failure, means stop and investigate.

If the prerender cannot find a browser:

```bash
npx playwright install --with-deps chromium      # once, if not already present
```

Publish:

```bash
sudo rsync -a --delete /var/www/sahilpay/app/client/dist/ /var/www/sahilpay/client/
sudo chown -R www-data:www-data /var/www/sahilpay/client
```

nginx is unchanged this release. Leave it alone.

---

## Step 7 — Restart the services

Restart all three. Celery sends every email and runs the billing; left on old
code it keeps the old behaviour running beside the new.

```bash
# server
sudo systemctl restart sahilpay
sudo systemctl restart sahilpay-celery
sudo systemctl restart sahilpay-celerybeat

sudo systemctl status sahilpay sahilpay-celery --no-pager | head -30
```

---

## Step 8 — Top up the SMS pool  ⚠️ **the deploy does not fix fault #2 on its own**

**The shared SMS pool balance is 0.** Every landlord→tenant SMS is being blocked
before it reaches the provider. Until you top it up, no SMS goes out — this
release only changes the failure from silent to explicit.

Check it:

```bash
# server
cd /var/www/sahilpay/app/server && source venv/bin/activate
APP_ENV=production python -c "
from app import create_app; from models import SmsPricingConfig
app = create_app()
with app.app_context():
    print('pool balance:', SmsPricingConfig.get_singleton().pool_balance)"
```

Fix it as a **system admin**, in the app:

1. **Admin → SMS → Pool**.
2. **Sync from provider** — reconciles the recorded balance against the real
   FluxSMS account. Do this first: if the provider account has credits, the
   number here was simply stale and syncing is the whole fix.
3. If the provider account is genuinely empty, buy credits from FluxSMS, then
   **Top up the shared pool** with the number bought.

Both actions are audited. The equivalent API calls are
`POST /api/admin/sms/pool/sync` and `POST /api/admin/sms/pool/top-up`.

**Also confirm real sending is on** — `true` means messages are written to the
log and never sent, which is correct for staging and a silent failure in
production:

```bash
grep COMMS_SIMULATION_MODE /var/www/sahilpay/app/server/.env
# production must read:  COMMS_SIMULATION_MODE=false
```

---

## Step 9 — Verify each fix

Health and prerender first:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://sahilpay.co.ke/api/health   # 200
curl -s https://sahilpay.co.ke/pricing | grep -c "Pricing"                   # > 0
```

A `0` on the second means Step 6 did not take — it fetches the page *without*
running JavaScript, exactly as a crawler does.

Then, in a browser. Each check corresponds to one reported fault.

**1 — Lease reaches the tenant.** As a landlord: **Leases → Prepare a lease**,
pick a test tenant, leave "Send it to the tenant" ticked, Prepare. Then sign in
to that tenant's portal:

- the notification bell carries **"Your tenancy agreement is ready to sign"**
  (this is new — sending used to notify nobody);
- the nav shows a labelled **Lease** link, on a phone as well as a desktop;
- the agreement is on screen with a signing form.

Sign it, approve it as the landlord, then reload the tenant portal: it must say
**approved** and offer **Download my copy**, and the download must produce a PDF.
Back in the Leases list, older agreements for that tenant now read **Replaced**.

**2 — Communications.** After Step 8, send an SMS from **Communications → Send
message**. The toast must report what actually happened. If anything fails, the
log's Status column now carries the reason underneath it — *"Sahil Pay SMS pool
is exhausted"*, *"No phone number is recorded for this recipient"* — rather than
a bare "Failed". Confirm the tenant↔landlord thread still works both ways at
**Tenant Messages**.

**3 — Maintenance photo.** From the tenant portal: **Maintenance → New request**,
attach a photo, submit. The tenant's own list shows a thumbnail. Open the same
request from **Maintenance** in the landlord portal — the photo is under the
**Photo** heading, not "No photo was attached".

**4 — Payout statement.** **Owner payouts → Payout runs**, and on any recorded
payout press **Statement**. A PDF must download. It must *not* open a new tab
showing the app's 404 page.

**5 — Collected picker.** On the same screen, above Generate:

- **Rent** is ticked and marked *Always included*, and cannot be unticked;
- every other charge type that produced money in the period is an optional
  checkbox showing its amount;
- the **Collected** figure changes as you tick and untick;
- the **Rent only / Total collected** toggle changes the Commission column, and
  the preview label reads *Commission (on rent)* or *Commission (on total)*
  accordingly;
- **Rent (tax base)** does not move when you change the commission basis.

Generate a run and open its statement: it names which base the commission used.

---

## Step 10 — Tell your clients about the payout default

**Do not skip this.** It changes a number people read.

**Before:** "Collected" on a payout run meant every shilling that arrived — rent,
deposits, utilities, penalties, the lot.

**After:** you choose. The screen opens with **rent only** ticked, so a run
generated without touching the checkboxes produces a **lower Collected figure
than the same period would have produced before**, and a lower net payable.

This is the requested behaviour, not a regression: which charges an agent
actually remits is a commercial arrangement, and it was previously being decided
by arithmetic. But it means **anyone who generates a payout run on autopilot will
see different numbers**, so say so first.

Two things that did *not* change, and are worth stating because owners ask:

- **Commission still defaults to rent only** — ordinary Kenyan practice, and the
  conservative reading. Charging it on the total is now possible, but only by
  deliberately switching the toggle.
- **Tax is still computed on rent**, whatever commission was charged on. MRI is a
  tax on rental income; folding a water float into it would overstate what the
  owner owes KRA.

Existing payouts are untouched and their statements render exactly as before —
the new columns are NULL on old rows and read as "everything collected,
commission on rent", which is what those runs actually did.

---

## Rolling back

```bash
# server
cd /var/www/sahilpay/app
git checkout <the commit before the merge>
cd server && source venv/bin/activate
APP_ENV=production flask db downgrade <the revision you noted in Step 2>
cd ../client && npm ci && npm run build:seo
sudo rsync -a --delete dist/ /var/www/sahilpay/client/
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
```

Three honest caveats:

- **`ae1b2c3d4e5f` cannot restore the original statuses.** Its downgrade puts
  every `superseded` lease back to `sent`, because that is what the
  overwhelming majority were — but a row that was a `draft` or `rejected`
  before comes back as `sent`. The distinction is not recoverable from the data.
- **Dropping the payout columns discards them.** Any run generated since the
  deploy loses the record of which charge types it counted and which base it
  commissioned. The money figures survive; the explanation does not.
- **`failure_reason` is likewise dropped**, taking the diagnosis of any failed
  message with it.

For anything short of a genuine emergency, restoring the Step 1 dump is cleaner
than a partial downgrade.

---

## Quick reference

```bash
# local — merge, after the gate passes
git checkout main && git pull origin main
git merge backend-set-up && git push origin main

# server — deploy
pg_dump -Fc sahilpay > ~/sahilpay-before-$(date +%F-%H%M).dump
cd /var/www/sahilpay/app/server && source venv/bin/activate
APP_ENV=production flask db current                 # note it down
cd /var/www/sahilpay/app && git fetch origin && git checkout main && git pull origin main
cd server && source venv/bin/activate && pip install -r requirements.txt
APP_ENV=production flask db upgrade                 # → ag1b2c3d4e5f
cd ../client && npm ci && npm run build:seo         # NOT npm run build
sudo rsync -a --delete dist/ /var/www/sahilpay/client/
sudo chown -R www-data:www-data /var/www/sahilpay/client
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
```

**Then, in the app as system admin:** Admin → SMS → Pool → **Sync from provider**
(and top up if the provider account is genuinely empty).

---

## The five things that will bite you if skipped

1. **Not running Step 2.** If production is older than `ad1b2c3d4e5f` this is a
   23-migration release with new dependencies and a mandatory-verification
   switch, and `DEPLOY_THIS_RELEASE.md` is the document you need first.
2. **Not topping up the SMS pool.** Fault #2 stays broken. The deploy makes the
   failure legible; it cannot make it go away.
3. **`npm run build` instead of `npm run build:seo`.** Public pages go invisible
   to crawlers and link previews.
4. **Celery not restarted.** Old code keeps sending mail and running billing
   alongside the new.
5. **Not warning clients about the payout default.** Someone generates a run,
   sees a lower Collected figure, and concludes money has gone missing.
