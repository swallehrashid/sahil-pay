# Sahil Pay — Redeploy: end of September 2026 (thirteen-item release)

Receipts that print exactly as previewed, a month on every receipt line,
payments allocated once only, reports you can reconcile to the shilling and
export to Excel, search that understands spaces, letterhead sizes, third-party
SMS accounts, property pages, invoicing one property at a time, the month-end
move-in, and next of kin.

> **Deploying? Follow the checklist: [REDEPLOY_PLAN_THIRTEEN_ITEMS.md](REDEPLOY_PLAN_THIRTEEN_ITEMS.md)**
> (backup, deploy, browser checks, 1 October, rollback). §1 below is the short version.
>
> **Not yet deployed the eight-item release?** Its §1 (the 1st-of-month
> automation choice) still applies — read
> [REDEPLOY_2026-09_EIGHT_ITEMS.md](REDEPLOY_2026-09_EIGHT_ITEMS.md) §1 first.
> This release changes nothing about that choice.

---

## 0. What is in this release

| # | Change | VPS action? |
|---|---|---|
| 1 | **Next of kin** (name, relationship, phone) on Add / Edit tenant; shown on the tenant's page | Migration (automatic) |
| 2 | **Send receipt** opens a dialog: tick Email / SMS / In-app, then Send. Nothing goes until you press Send. Also on the tenant's ledger page | No |
| 3 | **Receipts print exactly as previewed.** Every A4 paper is now generated as a real A4 page with the receipt in place — the "A4 third — portrait" receipt fills the top third of an upright sheet with a dashed cut line. Bigger type, tight rows, big logo / company name / contacts. The settings preview draws the actual PDF | No |
| 4 | **A payment is allocated once, to one tenant.** Re-confirming, splitting an already-allocated payment, or recording/confirming the same M-Pesa code twice (Payments page vs Co-pilot) is refused with the reason. Success message says what was allocated to whom | No |
| 5 | **Receipts only for confirmed, allocated payments** — pending / suspense / declined / reversed payments have no Send or Download receipt, and the API refuses them (409) | No |
| 6 | **Payments Report rebuilt**: summary by category, by the month each charge is for, per tenant (with property and unit), the full allocation ledger (every payment → invoice line → month), and a cash reconciliation (cash received = allocated + advance credit). Excel export has one sheet per table with real numbers and filters. Reports refresh after any change and every 30 s while open | No |
| 7 | **Search with spaces** — "Alex Kirui", "Kirui Alex", "alex kir" all work, in every search box (landlord, team, admin, dropdowns) | No |
| 8 | **Letterhead size**: logo, company name and contact info each 50 %–250 %, plus title alignment — Settings → Receipts & colours | No |
| 9 | **Third-party SMS account**: a landlord can connect their own FluxSMS API key + sender ID. The key is checked live with FluxSMS on Connect, stored encrypted, and their provider bills them (nothing comes off their Sahil Pay SMS balance). "Send test SMS" proves the sender ID | No |
| 10 | **Property page**: click a property → Units and Tenants sub-pages, each saying "You are viewing … for property X" | No |
| 11 | **Invoice by property**: Invoices → *Invoice by property* — pick the month, see each property's tenants and exactly what they will be billed, generate & confirm, next | No |
| 12 | **Month-end move-in**: "Bill the move-in now" on Add tenant — deposit, lease fee and the first rent month (next month when joining on the 20th or later). See §4 | Migration (automatic) |
| 13 | **Every receipt line names its month** — "Rent — Aug 2026", "Water — Jul 2026"; a carried balance is split by month; the lease agreement fee is the one undated line. Receipts show what is still owed, by month | No |

Also fixed while testing:

- **The row menu (⋮) on the Payments page did not open** on a normal-width screen — the
  table's own horizontal scroll closed it the instant it opened, so Send / Download
  receipt, Edit and Delete there were unreachable. Menus now follow the page instead of
  closing.
- A long property name or receipt number no longer runs across into the charges column.
- The tenant ledger's running balance counted carried balances twice, subtracted pending
  and declined payments, and double-counted advance credit. Fixed.
- "Total received" on Payments now follows the search and filters.
- The payment form now says *why* a payment was refused ("M-Pesa code … was already
  allocated to …") instead of "Could not save the payment."
- Monthly billing checks "already invoiced this month" within that month only — generating
  a past month no longer skips everyone.
- Date pickers without an id are now properly labelled (screen readers, form tests).

New migration (runs in `update.sh`):

```
ai1b2c3d4e5f -> aj1b2c3d4e5f   next of kin on tenants, billing month on invoice lines
```

Both are **new nullable columns**; nothing existing is rewritten. New client package:
`pdfjs-dist` (installed by `npm ci` in `update.sh`).

---

## 1. Deploy

```bash
cd /var/www/sahilpay/app/server && set -a && source .env && set +a
# pg_dump does not accept the "+psycopg2" in DATABASE_URL — strip it
pg_dump "${DATABASE_URL/+psycopg2/}" -Fc -f ~/sahilpay-before-thirteen-items-$(date +%F).dump
cd /var/www/sahilpay/app && git pull && ./deploy/update.sh
```

No `.env` changes, no nginx changes (the PDF preview worker is emitted as a normal `.js`
file, so it needs no special MIME type).

## 2. After deploying — check these five things (five minutes)

1. **Settings → Receipts & colours** → choose *A4 third — portrait (top third of the page)* →
   Update preview. The preview is an upright A4 page with the receipt in the top third.
   Download any receipt and print it with the printer's defaults — it comes out the same.
2. **Payments** → ⋮ on a confirmed payment → *Send receipt* → the channel dialog appears.
   A *pending* payment's ⋮ menu has no receipt options.
3. **Reports → Statements → Payments** → the four cards at the top: the last one should read
   *Balances — nothing unexplained · KES 0.00*.
4. **Tenants** search: type a first name, a space, and a surname.
5. **Invoices → Invoice by property** opens with the month and the property list.

## 3. Existing data — what changes and what does not

- **Old receipts re-downloaded now show months** on every line and the balance *as it was
  on that payment* (a receipt is a record of one moment; it no longer changes when later
  payments come in).
- **Payments that were "confirmed" but never allocated** (no invoice line, no credit) have
  no receipt until someone allocates them. There should be none; if a landlord reports a
  missing receipt, that is the reason, and allocating the payment fixes it.
- **Saved receipt paper "A4 third — tall slip"** is now a true third of the page width
  (70 mm) on an A4 sheet. Accounts that saved the old "a4_third_portrait" key now get the
  top-third receipt, which is what owners mean by it.
- **Stored SMS API keys from before** (plain text, from the old flow where keys were
  ignored) **are still ignored**. Only a key saved and verified through the new third-party
  flow switches an account to its own FluxSMS account. No account's SMS billing changes on
  deploy.

---

## 4. The month-end move-in — how it works, and why

### The situation

A tenant takes a unit on **28 September**. That day they pay the deposit, the lease
agreement fee and **October's** rent. They want a receipt that says it is October's rent.
Nobody charges a full month for the last three days of September.

### Q1 — What happens when 1 October comes and invoices are generated automatically?

When the tenant is added, tick **Bill the move-in now** on the Add tenant form. The system
suggests the first rent month (the move-in month, or next month when the move-in date is
the 20th or later) and shows the bill before you save:

```
Move-in invoice, dated 28/09/2026 — first rent month October 2026
  Rent — October 2026            20,000
  Rent Deposit                   20,000
  Lease Agreement                 1,000      (no month — a one-off fee)
  (optional) Rent 28–30 Sep, 3 days, pro-rata
```

It also sets the lease start to **1 October**.

The payment on the 28th is allocated to that invoice like any other payment.

On **1 October** the automatic run:

- **does not bill October's rent again.** It sees an October rent line already exists for
  this tenant, whatever date its invoice was issued.
- still bills anything else that is due, such as a queued meter reading.
- does nothing else for this tenant if there is nothing else to bill.

**From November** the tenant is on the normal monthly cycle.

A run for **September** (for example, somebody generates September's invoices on the 29th)
does not bill this tenant any rent, because rent starts in the lease's first month.

**If the landlord skips "Bill the move-in now"** and simply records the payment, the extra
money becomes **advance credit**. The receipt shows it as advance credit. On 1 October the
October invoice is raised and the credit is applied to it automatically, and that
application has its own receipt saying "Rent — Oct 2026". This works, but the tenant does
not get an October receipt on the 28th. That is why the move-in bill is the recommended
way.

### Q2 — Do we put it in the queue?

**No.** The queue exists for charges that cannot be billed yet. Either the amount is not
known until month end (meter readings), or the charge is waiting for someone to approve it.
Queued charges are billed on the *next* invoice. October's rent is known on the 28th and is
paid on the 28th. Queueing it would leave the tenant with no invoice and no receipt for it
until 1 October, which is the opposite of what they asked for. It is billed straight away
on the move-in invoice, tagged with its month.

### Q3 — They paid in September but need a receipt for October's rent

The receipt is **dated the day the money was received** (28/09/2026). That date is a fact:
KRA/eTIMS and any audit expect it, and a receipt dated in the future is not a receipt.
What the tenant needs is the **month the money is for**, and every line now says it:

```
Date paid      28/09/2026          CHARGES — OCT 2026
                                   Rent — Oct 2026           20,000.00
                                   Rent Deposit — Oct 2026   20,000.00
                                   Lease Agreement            1,000.00
```

The same rule covers the opposite case. A tenant in September who pays August's arrears
gets "Rent — Aug 2026" on the receipt, and "Still owed after this payment: Rent — Sep 2026"
underneath.

---

## 5. How it was verified

- **Backend:** 892 tests pass, plus 11 new ones for this release
  (`tests/test_thirteen_items.py`). The receipt geometry tests were rewritten to check the
  rendered PDF: an A4 page, one page, all ink above the cut line, the full width used.
- **End to end:** `client/scripts/qa/thirteen-items.mjs` passes 53/53 checks on the scale
  estate: 100 properties, 1,000 units, 943 tenants, five months (May–September 2026) of
  billing, partial payments, advances and water readings driven through the production
  engine. Screenshots are in `.qa/2026-09-29-thirteen-items/`, one folder per item.
- **Report accuracy:** checked independently against the database. Cash received and
  "still owed" match to the shilling, and cash received = allocated + advance credit with a
  difference of KES 0.00.
- **Third-party SMS:** Sahil Pay's own FluxSMS key was connected *as a third-party account*.
  The live check returned the real balance. A wrong key was rejected by FluxSMS. The key is
  stored encrypted.
