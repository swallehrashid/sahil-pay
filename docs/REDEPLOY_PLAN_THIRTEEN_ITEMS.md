# Redeployment plan — thirteen-item release (end of September 2026)

A step-by-step checklist to run yourself. Tick each box as you go. **Do the steps in
order**, and do not skip a check marked **STOP IF**.

- What is in the release, and the month-end move-in explanation: [REDEPLOY.md](REDEPLOY.md)
- Time needed: about **40 minutes**, including checks. The site is down for about
  **1 minute**, while the services restart.
- **When:** today or tomorrow, and **before 00:05 on 1 October**. That is when the
  automatic monthly invoicing runs; Part D covers it.
- Where the commands run:
  - **[laptop]** — your development machine, in `~/Projects/sahil-pay`.
  - **[VPS]** — the server over SSH, as the `sahilpay` user.

---

## Part A — [laptop] Prepare the code

### A1. Make sure it still passes (optional, 5 minutes)

```bash
cd ~/Projects/sahil-pay/server && source venv/bin/activate
python -m pytest tests/ -q -p no:warnings --ignore=tests/render_email_previews.py
cd ../client && npx vite build
```

- [ ] Tests end with `895 passed, 1 skipped` (or more passed), and `0 failed`.
- [ ] The build ends with `✓ built in …`.

**STOP IF** anything fails. Do not deploy, and send me the output.

### A2. Mark the version currently live, so you can roll back to it

The live server is on commit `64d9062` ("fixes drop downs and bulk delete").

```bash
cd ~/Projects/sahil-pay
git tag pre-thirteen-items 64d9062
git push origin pre-thirteen-items
```

- [ ] The tag was pushed with no error.

### A3. Commit and push the release

```bash
cd ~/Projects/sahil-pay
git add -A
git status --short          # review: no .env, no dump files, no private_backups/
git commit -m "Thirteen-item release: receipts print as previewed, months on receipts, allocate-once, reports + Excel, search with spaces, letterhead sizes, third-party SMS, property pages, invoice by property, month-end move-in, next of kin"
git push origin backend-set-up
```

- [ ] `git status --short` lists **no** `.env` file, `*.dump`, `private_backups/` or `.qa/`
      files. These are git-ignored; if one shows up, run `git restore --staged <file>`
      before committing.
- [ ] The push succeeded.

---

## Part B — [VPS] Deploy

### B1. Log in and go to the app

```bash
ssh sahilpay@<YOUR_VPS_IP>
cd /var/www/sahilpay/app
```

### B2. Pre-flight checks

Run these one at a time and compare each result with the box underneath it.

```bash
git status --short
```

- [ ] Prints **nothing**. Nobody has edited files directly on the server.
      **STOP IF** it lists files: send me the list, because `git pull` would refuse.

```bash
git branch --show-current
```

- [ ] Prints `backend-set-up`.

```bash
node -v
```

- [ ] Prints **v20.19 or higher**, or v22 or higher. The new PDF preview package needs it.
      **STOP IF** it is lower. Upgrade first, then run `node -v` again:

  ```bash
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt install -y nodejs
  ```

```bash
df -h /var/www
```

- [ ] At least **2 GB** free.

```bash
sudo systemctl is-active sahilpay sahilpay-celery sahilpay-celerybeat
```

- [ ] Prints `active` three times.

```bash
cd server && set -a && source .env && set +a && venv/bin/flask db current 2>/dev/null | tail -1; cd ..
```

Write down the revision it prints: ______________

- [ ] **`ai1b2c3d4e5f`** → the previous (eight-item) release is already live. Go to B3.
- [ ] **`ah1b2c3d4e5f`** → the eight-item release was **never deployed**. This deploy will
      apply it as well. Before continuing, do **§1** (the 1 October automation check) and
      **§3** (the `private_backups` folder) of
      [REDEPLOY_2026-09_EIGHT_ITEMS.md](REDEPLOY_2026-09_EIGHT_ITEMS.md).
      Its migration also removes tenants whose property was deleted and rewrites phone
      numbers to `254…`. That is intended, and the backup in B3 covers it.
- [ ] **Anything else** → **STOP** and send me the revision.

### B3. Back up the database and uploaded files

The production `DATABASE_URL` begins with `postgresql+psycopg2://`, which `pg_dump` does not
accept. The command strips the `+psycopg2` part.

```bash
cd /var/www/sahilpay/app/server
set -a && source .env && set +a
pg_dump "${DATABASE_URL/+psycopg2/}" -Fc -f ~/sahilpay-before-thirteen-items-$(date +%F-%H%M).dump
tar czf ~/sahilpay-uploads-before-thirteen-items-$(date +%F-%H%M).tgz uploads private_backups 2>/dev/null || tar czf ~/sahilpay-uploads-before-thirteen-items-$(date +%F-%H%M).tgz uploads
ls -lh ~/sahilpay-before-thirteen-items-*.dump ~/sahilpay-uploads-before-thirteen-items-*.tgz
```

- [ ] Both files exist, and the `.dump` is **larger than 0 bytes**. It is usually several MB.
      **STOP IF** the dump is missing or 0 bytes.

Optionally, copy the backups off the server. Run this from your laptop:

```bash
scp sahilpay@<YOUR_VPS_IP>:~/sahilpay-before-thirteen-items-*.dump ~/Backups/
```

### B4. Run the deploy script

```bash
cd /var/www/sahilpay/app
./deploy/update.sh
```

It pulls the code, installs packages, runs the migration, builds the frontend, publishes
it, restarts the three services, and checks the API. Watch for:

- [ ] `Running upgrade ai1b2c3d4e5f -> aj1b2c3d4e5f, next of kin on tenants, billing month on invoice lines`.
      Two upgrade lines appear if the eight-item release was not yet live.
- [ ] `✓ built in …` from the frontend build.
- [ ] Last line: **`API healthy ✔ — deploy complete`**.

`SKIPPED — headless Chromium unavailable` during "SEO prerender" is harmless.

**STOP IF** it ends with `WARNING: health check failed`, or exits with an error. Go to B6
and send me the log lines.

### B5. Confirm the migration landed

```bash
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
venv/bin/flask db current 2>/dev/null | tail -1
psql "${DATABASE_URL/+psycopg2/}" -tAc "SELECT column_name FROM information_schema.columns WHERE table_name IN ('tenants','invoice_line_items') AND column_name IN ('next_of_kin_name','next_of_kin_relationship','next_of_kin_phone','period_month') ORDER BY 1"
```

- [ ] The first command prints `aj1b2c3d4e5f (head)`.
- [ ] The second prints four names: `next_of_kin_name`, `next_of_kin_phone`,
      `next_of_kin_relationship` and `period_month`.

### B6. Check the services and logs

```bash
sudo systemctl is-active sahilpay sahilpay-celery sahilpay-celerybeat
sudo journalctl -u sahilpay -n 40 --no-pager
sudo journalctl -u sahilpay-celery -n 20 --no-pager
```

- [ ] `active` three times.
- [ ] No `Traceback` and no `ERROR` in the last lines. A single `WARNING` about rate
      limits or deprecation is fine.

---

## Part C — Check it in the browser (15 minutes)

Log in at **https://sahilpay.co.ke** as a landlord account with real data, preferably your
own. Press **Ctrl + Shift + R** once, so the browser loads the new version.

| # | Do this | You should see | ✓ |
|---|---|---|---|
| C1 | Settings → **Receipts & colours** → pick **A4 third — portrait (top third of the page)** → **Update preview** | The preview is an **upright A4 page** with the receipt in the **top third** and a dashed line under it. Big logo, "OFFICIAL RECEIPT", company name, contacts on the right | ☐ |
| C2 | Same screen → **Letterhead size**: drag **Logo** to 150% → **Update preview** → **Save layout** | The logo gets bigger in the preview; "Saved" message | ☐ |
| C3 | **Payments** → ⋮ on a **confirmed** payment → **Download receipt**. Open the PDF and **print it with the printer's default settings** | The paper comes out **upright**, with the receipt in the **top third**, exactly like the preview. Every line says a month ("Rent — Sep 2026"); "Lease Agreement" has none | ☐ |
| C4 | Payments → ⋮ on the same payment → **Send receipt** | A dialog with **Email / SMS / In-app** checkboxes appears. **Nothing is sent** until you tick one and press **Send receipt** | ☐ |
| C5 | Payments → filter Status = **pending** (if any) → ⋮ | **No** Send receipt or Download receipt options | ☐ |
| C6 | Payments → **Review** on a pending payment → **Confirm payment** | Green message: "Payment … reviewed and allocated to <tenant>: KES … applied". Try confirming the same payment again: it is refused with "already been reviewed and allocated" | ☐ |
| C7 | **Tenants** → search box: type a first name, a **space**, and a surname | The tenant appears. The space is still in the box | ☐ |
| C8 | **Properties** → click a property row | Its page opens: **Units** tab, with the banner "You are viewing units for property …". Click **Tenants**: the banner changes to tenants | ☐ |
| C9 | **Invoices** → **Invoice by property** | Month picker, the property list with status, and the selected property's tenants with the amounts each will be billed. **Don't press Generate** unless you intend to invoice | ☐ |
| C10 | Tenants → **Add tenant**: pick a vacant unit, fill **Next of kin**, set Move-in date to the **28th**. Under **Move-in bill** tick **Bill the next month's move-in now** and **Include the first month's rent**, then add *Rent — Deposit* and *Lease Agreement — This month* | The Rent line is prefilled with the unit's rent. The preview reads "Rent — <next month>", "Rent Deposit — <next month>", "Lease Agreement" (no month). Untick the box: everything switches to this month. Press **Cancel** unless this is a real tenant | ☐ |
| C11 | Reports → Statements → **Payments** | The four cards at the top; the last reads **"Balances — nothing unexplained · KES 0.00"**. Tabs: Summary / By month / Per tenant / Allocation ledger | ☐ |
| C12 | Same page → **Download Excel** | A file `payments-report.xlsx` with sheets: Summary by category, By month, Per tenant, Allocation ledger, Reconciliation | ☐ |
| C13 | Settings → **SMS sender** | The page shows two choices: "Sender name on Sahil Pay" and "My own FluxSMS account (third party)". Change nothing unless a client asks | ☐ |
| C14 | On a **phone**: log in, then Settings → Receipts & colours → Update preview | The receipt preview draws on the phone too | ☐ |

If C1 or C3 fails, check that you pressed Ctrl + Shift + R, then send me a photo of the
printout next to a screenshot of the preview.

---

## Part D — [VPS] Before 00:05 on 1 October

The monthly run at 00:05 on the 1st invoices only the accounts that ticked **Settings →
Company → Automated tasks → "Automatically invoice rent"**. See which accounts have
tenants but the tick **off**:

```bash
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
psql "${DATABASE_URL/+psycopg2/}" -c "
SELECT l.id, l.company_name, count(t.id) AS tenants
FROM landlords l
JOIN automation_settings a ON a.landlord_id = l.id
JOIN tenants t ON t.landlord_id = l.id AND NOT t.is_deleted
WHERE NOT l.is_demo AND NOT a.auto_generate_recurring_invoices
GROUP BY l.id, l.company_name ORDER BY tenants DESC;"
```

- [ ] You have decided, for each account listed, whether it should be invoiced on 1
      October. Either ask the client to tick the box, or turn it on for them:

  ```bash
  psql "${DATABASE_URL/+psycopg2/}" -c "UPDATE automation_settings SET auto_generate_recurring_invoices = true WHERE landlord_id IN (<ids>);"
  ```

What is new about 1 October: a tenant who joined late in September and was billed with
**"Bill the next month's move-in now"** will **not** be billed October's rent a second time,
and a tenant billed a part month in September will be billed October in full. Anyone can
still invoice by hand afterwards with **Invoices → Invoice by property**; it never bills a
tenant twice for the same month.

---

## Part E — Rollback (only if something is badly wrong)

Do this **in this order**. The database step has to run while the new code is still in
place, because the new code contains the migration's "undo".

```bash
# 1. Undo the database change (drops the next-of-kin columns and period_month only)
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
venv/bin/flask db downgrade ai1b2c3d4e5f

# 2. Go back to the previous code
cd /var/www/sahilpay/app
git fetch --tags
git checkout pre-thirteen-items

# 3. Rebuild and restart (update.sh is not used here: it runs `git pull`, which does
#    not work on a checked-out tag)
server/venv/bin/pip install -r server/requirements.txt --quiet
(cd client && npm ci --silent && npm run build)
rm -rf /var/www/sahilpay/client.bak && mv /var/www/sahilpay/client /var/www/sahilpay/client.bak
cp -r client/dist /var/www/sahilpay/client
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
curl -sf https://sahilpay.co.ke/api/health && echo "rolled back OK"
```

**If this deploy also applied the eight-item release** (B2 printed `ah1b2c3d4e5f`), also
run `venv/bin/flask db downgrade ah1b2c3d4e5f` in step 1, straight after the first
downgrade. Removed tenants and rewritten phone numbers only come back from the B3 backup:

```bash
pg_restore --clean --if-exists -d "${DATABASE_URL/+psycopg2/}" ~/sahilpay-before-thirteen-items-<date>.dump
```

Afterwards, put the server back on the branch for the next deploy:
`git checkout backend-set-up`.

What a rollback loses: next-of-kin details entered since the deploy, and the month tags on
move-in invoices raised since the deploy. The invoices and payments themselves stay.

---

## Part F — After the deploy

- [ ] Tell clients who print receipts: choose **A4 third — portrait (top third of the page)**
      in Settings → Receipts & colours, print normally, and cut along the dashed line. No
      special print settings are needed any more.
- [ ] Tell property managers about **Invoices → Invoice by property**, and the **Move-in bill**
      on Add tenant: before the 20th, bill the part month as "Rent — This month". From the
      20th, tick **Bill the next month's move-in now**.
- [ ] Keep the B3 backup files for at least **two weeks**, then delete them:
      `rm ~/sahilpay-before-thirteen-items-*.dump ~/sahilpay-uploads-before-thirteen-items-*.tgz`

| Step | Done | Time | Notes |
|---|---|---|---|
| A — code pushed | ☐ | | |
| B — deployed, health OK | ☐ | | |
| C — browser checks | ☐ | | |
| D — 1 October accounts decided | ☐ | | |
