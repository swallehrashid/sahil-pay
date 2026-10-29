# Sahil Pay — Redeploy: end of October 2026 (three-fix release)

SMS credits that reconcile to the payments that were actually confirmed, an
admin whose decisions the billing engine obeys, and one hard rule under the
whole ledger: **no money is recorded that no invoice accounts for.**

> Google sign-in is in this release but **switched off and dormant** — see §6.
> Nothing to do for it now.

---

## 0. What is in this release

| # | Change | VPS action? |
|---|---|---|
| 1 | **SMS credits have a source of truth.** A landlord who bought 1,000 credits read 2,000, because one M-Pesa payment was confirmed twice (the STK callback *and* the C2B confirmation of the same money) and the balance counter was credited twice with no memory of it. Crediting is now idempotent per M-Pesa receipt, every send records the credits it burned, and the balance is rebuilt on deploy from confirmed payments − usage | **Migration rebuilds every balance (automatic)** |
| 2 | **The admin's word is final.** Status, trial, due date and portal access can be pinned by hand and the automation will not undo them. Extending a due date now actually keeps the account open. Bad input gets a precise message instead of "An unexpected error occurred. Our team has been notified." | Migration (automatic) |
| 3 | **No payment without an invoice.** A payment answers a charge, so it can never be bigger than what has been invoiced. The excess is no longer parked as "tenant credit" — which is exactly how the dashboard came to show more collected than was ever invoiced, and why receipts carried negative lines | No |

Also fixed while testing:

- **Every date field in the admin and landlord UI rendered blank.** `_serialise()`
  handled `datetime` but not a plain `date`, so Flask fell back to RFC-1123
  ("Thu, 05 Nov 2026 00:00:00 GMT"), which an `<input type="date">` cannot
  display. The **due date you were trying to extend was never actually shown to
  you** — the field looked unset every time you opened it. Dates are now ISO.
- **The status dropdown offered "cancelled", which is not a real status.** Before
  the server validated anything, picking it stored a status the billing engine
  did not recognise, and the next page load silently replaced it with "active".
- **The billing cycle was spelled three different ways** — the database enum said
  `monthly`/`yearly`, the pricing tables said `monthly`/`quarterly`/`annual`, and
  the admin dropdown said `monthly`/`yearly`. A landlord saved as "yearly" was
  charged monthly. Everything now normalises through one function; the picker
  offers the real cycles with their discounts.
- A non-ISO date typed anywhere in the admin billing form raised straight out of
  the request as an HTTP 500. Every field is now parsed and reported.

New migrations (run automatically by `update.sh`):

```
aj1b2c3d4e5f -> d1f2a3b4c5d6   communication_logs.sms_credits + backfill of past usage
d1f2a3b4c5d6 -> d2f3a4b5c6d7   REBUILD every landlord's sms_balance from confirmed payments
d2f3a4b5c6d7 -> d3f4a5b6c7d8   users.google_sub (dormant — see §6)
d3f4a5b6c7d8 -> d4f5a6b7c8d9   subscriptions: admin override columns
```

`d2f3a4b5c6d7` is the only one that **changes existing data**. Everything else
adds nullable columns or columns that default to today's behaviour.

---

## 1. Deploy

```bash
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
# pg_dump does not accept the "+psycopg2" in DATABASE_URL — strip it
pg_dump "${DATABASE_URL/+psycopg2/}" -Fc -f ~/sahilpay-before-three-fixes-$(date +%F).dump
cd /var/www/sahilpay/app && git pull && ./deploy/update.sh
```

**Take the backup.** §2 rewrites SMS balances.

---

## 2. What the SMS rebuild will do

For every real (non-demo) landlord it recomputes:

```
balance = confirmed-purchase credits   (one grant per M-Pesa receipt)
        + genuine admin manual credits (your own hand-credits)
        − credits used on charged sends
```

- Duplicate confirmations of one payment collapse to a single grant, so the
  client reading **2,000 drops back to the 1,000 they paid for**.
- Failed, pending-unconfirmed and reversed payments count for nothing.
- A clean account recomputes to the balance it already had and is left alone.
- Every balance that moves is written to that landlord's credit history with a
  `SYS-RECON:` reason, so you can see what changed and why.

**Check it before you deploy** (optional, read-only) — on the VPS:

```bash
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
psql "${DATABASE_URL/+psycopg2/}" -c "
SELECT l.id, l.company_name, l.sms_balance AS shows_now,
       COALESCE(p.c,0) AS confirmed_purchased
FROM landlords l
LEFT JOIN (
  SELECT landlord_id, SUM(sms_count) AS c FROM (
    SELECT DISTINCT ON (landlord_id, COALESCE(payment_reference,'txn:'||id::text))
           landlord_id, id, sms_count
    FROM billing_transactions
    WHERE type='sms_purchase' AND is_verified AND NOT is_reversed AND sms_count IS NOT NULL
    ORDER BY landlord_id, COALESCE(payment_reference,'txn:'||id::text), id
  ) d GROUP BY landlord_id
) p ON p.landlord_id = l.id
WHERE l.is_demo = false AND l.sms_balance > 0
ORDER BY l.sms_balance DESC;"
```

**After deploying**, the same figures are on screen per landlord:
`GET /api/admin/sms/landlords/<id>/balance-truth`, and
`POST /api/admin/sms/landlords/<id>/resync` re-runs the rebuild for one
landlord any time (idempotent — safe to press twice).

---

## 3. Admin control — how to use it

Admin → Pricing → a landlord → **Landlord billing**. New *Admin control* panel:

| Control | Effect |
|---|---|
| **Portal access: System decides** | Default. Locks on an unpaid balance past the grace days, as before |
| **Portal access: Force OPEN** | The portal is never locked — whatever the balance, status or trial says |
| **Portal access: Force CLOSED** | The portal is always locked |
| **Pin status** | The automation never rewrites `status` again. Set automatically whenever you choose a status by hand |
| **Freeze billing** | No charge is ever auto-added, and the next billing date never moves on its own |
| **Reason** | Required for Force OPEN / Force CLOSED; kept on the audit trail |

**Extending a due date now works the way you expect.** Set *Next billing date*
to, say, 5 November and save: the account opens, and the overdue clock is
cleared so it does **not** lock itself again a few days later. Previously the
clock was re-armed to today on every save, which is why accounts you had just
opened closed again.

To hand an account back to the automation, set Portal access to *System decides*
and untick Pin status / Freeze billing.

---

## 4. The invoice rule — read this before deploying

> **You invoice first, then a payment is allocated to that invoice.**
> A payment that is bigger than what has been invoiced is refused, with a
> message saying how much is uncovered and what to do.

This is the behaviour change your team will notice, so it is worth saying out
loud:

- **Recording a payment for a tenant with nothing invoiced is refused.** Generate
  that month's invoices first, then record the payment.
- **A manual split must account for every shilling** of the payment.
- **An advance is recorded month by month.** If a tenant pays January→December in
  January, only January is recorded, because only January is invoiced. The money
  is not lost — it is in your M-Pesa account, and each month is recorded as that
  month is invoiced. This is why receipts will stop showing negative lines.
- **Money that arrives by itself is never thrown away.** An M-Pesa, Co-pilot or
  bank-statement payment bigger than the tenant's invoiced total is still
  recorded, as **pending**, and waits in the review queue. Pending money counts
  nowhere — not in reports, not on the dashboard, not on a receipt — until you
  raise the invoice and confirm it. Nothing is lost and nothing is overstated.
- **Expect more items in the review queue early in the month** if you have not
  generated that month's invoices yet. Generate the month's invoices, then
  confirm the waiting payments.
- **History is left exactly as it is.** Credit already on a tenant's account from
  before this release still drains normally against new invoices. Only *new*
  over-invoice recording is refused.

The result is the invariant you asked for: **amount recorded can never exceed
amount invoiced**, on the dashboard and in every report.

One thing that is *not* a violation, so you know it when you see it: the
dashboard compares **this month's** payments with **this month's** invoices, so a
month in which tenants clear old arrears can still show collected higher than
invoiced for that month. That money is invoiced — just in an earlier month. The
rule being enforced is per tenant and across all time: nothing is recorded that
no invoice accounts for. The **Payments Report** reconciliation is the figure to
read for the strict check, and it now always balances to zero difference with
nothing in "advance to credit".

---

## 5. Browser checks after deploying

1. **Admin → Pricing → a landlord → Landlord billing**
   - The *Next billing date* and *Trial ends* fields now **show the current
     dates** instead of being blank.
   - Change *Next billing date* to a date next week → Save → the badge reads
     **Open**, and the toast says the settings are pinned.
   - Type `05/11/2026` into a date field → Save → a clear field-level message,
     **no** "unexpected error".
   - Set *Portal access* to **Force OPEN** without a reason → it asks for one.
2. **Admin → SMS → a landlord** — balance matches the confirmed purchases; the
   credit history shows a `SYS-RECON:` line for any landlord whose balance moved.
3. **Landlord → Payments → Record payment**
   - Pick a tenant with nothing invoiced → the panel explains that nothing is
     invoiced yet and the amount is refused.
   - Pick a tenant with an open invoice → pay exactly the balance → recorded,
     receipt is clean, no advance/credit line.
   - Try to pay more than the balance → refused, naming the invoiced total.
4. **Landlord → Payments → a pending Co-pilot/M-Pesa item** → *Confirm* is
   blocked while any of it is uncovered, with the reason shown.

---

## 6. Google sign-in — paused, nothing to do

The "Continue with Google" work is in this release but **inert**: it is gated on
`GOOGLE_CLIENT_ID` (server) and `VITE_GOOGLE_CLIENT_ID` (frontend). Both are
unset, so the buttons do not render and the endpoint refuses with a clear
message. Migration `d3f4a5b6c7d8` only adds a nullable `users.google_sub` column
and widens one check constraint; it changes no existing row.

To switch it on later, set both variables to the same OAuth Web client ID and
redeploy — the full steps are in
[SMS_BALANCE_AND_GOOGLE_SIGNIN.md](SMS_BALANCE_AND_GOOGLE_SIGNIN.md).

---

## 7. Rollback

```bash
sudo systemctl stop sahilpay sahilpay-celery sahilpay-celerybeat
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
pg_restore -c -d "${DATABASE_URL/+psycopg2/}" ~/sahilpay-before-three-fixes-<date>.dump
cd /var/www/sahilpay/app && git checkout <previous-commit> && ./deploy/update.sh
```

The SMS rebuild has no down-migration on purpose — the pre-fix balances were
inflated drift, not a state worth restoring. Roll back from the dump if you need
them back.
