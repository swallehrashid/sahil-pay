# Sahil Pay — Redeploy: late September 2026 (eight-item release)

Dropdowns that list everything, Backup & Delete, cascading deletes, SMS billed
to the account, one phone format, tutorials for team members, audit trail in
Nairobi time, and the team / queued-invoice workflow.

> **Read §1 before 1 October.** From this release the 1st-of-month invoicing
> only runs for accounts that ticked it. Until now it ran for every account.

---

## 0. What is in this release

| # | Change | VPS action? |
|---|---|---|
| 1 | Every form dropdown lists **all** properties / units / tenants (was: the first 20) and searches all of them | No |
| 2 | Settings → Backup & export → **Back up and delete everything** (owner only; confirm → password → type `DELETE ACCOUNT SP-xxxxx` → final warning) | Folder, §3 |
| 3 | Deleting a property removes its units and their tenants; deleting a unit removes its tenant. **Existing headless units/tenants are removed by the migration** | Migration (automatic) |
| 4 | Every SMS on an account is charged to that account (only the tenant login code is on Sahil). Fixed two free-SMS leaks (see below) | No |
| 5 | Phones saved as `2547XXXXXXXX`; tenants sign in with 07…, 7…, 254… or +254…; SMS always sent as 254… | Migration rewrites stored numbers |
| 6 | Tutorials run for team members; a member only sees tutorials for modules they can **edit**; view-only members get no Help | No |
| 7 | Audit trail (and every other timestamp) shows Nairobi time on any device | No |
| 8 | "Full access" team preset; caretaker → submit for review → office approves → one monthly invoice with rent + approved charges + balance b/f; two automation ticks | Migration + **§1** |

Also fixed while testing:

- **Free SMS leak #1** — "Send balance reminder" and "Send invoice" sent the SMS but never
  saved, so the charge and the message log were rolled back. Every SMS charge is now also
  committed at the end of the request as a safety net.
- **Free SMS leak #2** — when FluxSMS accepted a message but returned no message id (a
  "scheduled" send) it was treated as failed and not charged, although FluxSMS still bills
  Sahil Pay for it. It is now charged and logged as *pending*.
- The welcome message now reports what really happened (e.g. "SMS not sent — Insufficient SMS
  balance") instead of always saying "sent".
- Alert SMS to the landlord are charged to the account; with no credits they go by email/in-app.
- Team members get Review queue and Owner payouts (with Payments permission), and links on
  shared pages no longer bounce them to the landlord portal.
- The test suite can no longer send real SMS: testing config forces simulation.
- **View-only team members no longer see write buttons** (Add / Edit / Delete / Record /
  Send) on Properties, Units, Tenants, Invoices, Payments, Expenses, Maintenance, Groups,
  Communications and the tenant inbox. The server already refused the change; now the button
  is not offered.
- The dashboard's money figures (`/api/dashboard/summary`, unpaid tenants, performance graph)
  need Payments → View. A caretaker could read the account's collections and arrears before.
- The team dashboard shows the owner's money cards (with Payments access), a shortcut to every
  page the member can open, and "N charges waiting for your review" for invoice editors.
- Tutorial highlights follow the page when the sidebar expands, so the highlight is on the item
  the tooltip names.
- Tutorials added: *Record meter readings and send them for billing* (Utilities editors) and
  *Approve queued charges and invoice the month* (Invoices editors).

New migration (runs in `update.sh`):

```
ah1b2c3d4e5f -> ai1b2c3d4e5f   cascade clean-up, one phone format, queued-charge review, queued auto-invoicing
```

No new Python packages.

---

## 1. Automatic invoicing on the 1st — decide BEFORE 1 October

Settings → Company → **Automated tasks** now has two ticks under *On the 1st of every month*:

- **Automatically invoice rent (and other fixed monthly charges)** — the existing
  `auto_generate_recurring_invoices` setting; whatever an account had is kept.
- **Automatically invoice approved queued charges (utilities etc.)** — new, **OFF for everyone**.

The Celery job at 00:05 on the 1st now skips any account with both ticks off. Before this
release it invoiced **every** account regardless of the first tick. So an account that relied on
that without ticking the box will **not** be invoiced on 1 October.

See who is affected (accounts with tenants but the rent tick off):

```sql
SELECT l.id, l.company_name, count(t.id) AS tenants
FROM landlords l
JOIN automation_settings a ON a.landlord_id = l.id
JOIN tenants t ON t.landlord_id = l.id AND NOT t.is_deleted
WHERE NOT l.is_demo AND NOT a.auto_generate_recurring_invoices
GROUP BY l.id, l.company_name ORDER BY tenants DESC;
```

Either ask those clients to tick it, or tick it for them:

```sql
UPDATE automation_settings SET auto_generate_recurring_invoices = true WHERE landlord_id IN (...);
```

Anyone can also raise the month's invoices by hand: Invoices → Queued charges →
**Create this month's invoices now** (rent and/or approved charges; safe to run twice).

## 2. Back up the database

```bash
pg_dump "$DATABASE_URL" -Fc -f ~/sahilpay-before-eight-items-$(date +%F).dump
```

The migration **soft-deletes** every tenant and unit whose property (or unit) is already
deleted, and **rewrites phone numbers**. Both are what we want, and both are hard to reverse
without this dump.

## 3. Backup & Delete folder

Full-account backups are written to `server/private_backups/<account id>/` — **not** under
`uploads/`, which nginx serves publicly. Make sure the app user can create it:

```bash
cd /var/www/sahilpay/app/server && mkdir -p private_backups && chown "$(stat -c %U uploads)" private_backups
```

It is in `.gitignore`. Include it in whatever backs up the server.

## 4. Deploy

```bash
cd /var/www/sahilpay/app && ./deploy/update.sh
```

## 5. Verify (10 minutes)

1. **Headless tenants gone** — for the account whose properties were all deleted:
   ```sql
   SELECT count(*) FROM tenants t JOIN units u ON u.id=t.unit_id JOIN properties p ON p.id=u.property_id
   WHERE NOT t.is_deleted AND (u.is_deleted OR p.is_deleted);   -- expect 0
   ```
   Its Tenants page should read 0.
2. **Phones** — `SELECT phone FROM tenants WHERE phone !~ '^254[17][0-9]{8}$' LIMIT 20;` lists only
   numbers that are not Kenyan mobiles (left untouched on purpose).
3. **Dropdowns** — Tenants → Add tenant → Property: the footer reads "N of N" for all properties.
4. **SMS** — add a tenant with "Send a welcome message": the "SMS left" counter in the top bar
   drops immediately; Communications shows the message with its charge.
5. **Tenant sign-in** — sign in on a phone typing the number as 07… and again as 254….
6. **Audit trail** — do something, open Settings → Audit trail: the time matches the clock in Nairobi.
7. **Team** — add a member with the *Full access* preset: they see everything except Settings;
   Help → Tutorials → Start runs a tour.

## 6. Phone numbers — what to tell clients

Any of these work everywhere (adding a tenant, sign-in, reminders):
`0712 345 678`, `0712345678`, `712345678`, `254712345678`, `+254 712 345 678`, and the same for `01…`.
They are saved as `254712345678`. **Only Kenyan mobile numbers are accepted**; anything else is
refused with the message *"Enter a Kenyan mobile number, e.g. 0712 345 678 or 254712345678."*

## 7. Rollback

```bash
cd /var/www/sahilpay/app && git checkout <previous-tag> && ./deploy/update.sh
cd server && venv/bin/flask db downgrade ah1b2c3d4e5f
```

The downgrade drops the new columns only. It does **not** un-delete the headless tenants/units or
restore the old phone formats — restore the §2 dump if you need those back.
