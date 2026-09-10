# Core Flows Fixes Spec — Auth, Affiliate, Payments / Utilities / Invoices, Tables

Execution spec for the July 2026 fixes round. Every decision below has already been
approved by the owner — do not re-litigate choices, but DO flag anything you discover
that contradicts this spec before working around it.

**Ground rules for the executor:**
- Backend: Flask + SQLAlchemy in `server/`. Frontend: React + RTK Query in `client/src/`.
- No schema migrations are expected for any item here. If you find you need one, stop and say so.
- Part G (browser verification) is **mandatory, not optional**. The owner explicitly asked
  for every button on Payments, Utilities and Invoices to be clicked and every flow driven
  end-to-end in the real browser UI. Do not mark this spec done on green tests alone.
- Reuse the existing allocation engine (`server/services/allocation_service.py`). It is
  already correct: it allocates only to `open` line items on non-void invoices, and moves
  invoice status `open → partial → paid` as balances change. Nothing in this spec may
  bypass it or duplicate its logic.

---

## Part A — Global auth pages

### A1. Back-to-home button
`client/src/components/layout/AuthLayout.jsx` currently only has the logo linking home.
Add an explicit back control (left-arrow + "Back to home") at the top of the auth card,
linking to `PUBLIC_ROUTES.home`. Because Login, LandlordRegistration, forgot/change
password and the tenant OTP login all render through `AuthLayout`, one change covers all.

### A2. Password visibility toggle
No password field anywhere has a show/hide toggle. Add it to the shared
`client/src/components/ui/Input.jsx`: when `type="password"`, render an eye / eye-off
button (lucide `Eye` / `EyeOff`) inside the field that toggles the input between
`password` and `text`. The toggle is persistent (stays in whatever state the user set,
not press-and-hold). This automatically covers:
- `client/src/features/auth/Login.jsx` (password field, line ~79)
- `client/src/features/auth/LandlordRegistration.jsx` (password + confirm fields)
- change-password / team-member set-password screens.
Make sure the button does not submit the form (`type="button"`) and does not break the
error/hint layout of `Input`.

---

## Part B — Affiliate portal

### B1. Dash out plan info once the commission window is over
When a referral's status is `completed` (or `void`), the affiliate must no longer see the
referred landlord's plan details.

Backend — `server/routes/affiliate_routes.py` (~lines 160–165): when serialising a
referral whose `status` is not `active`/`pending`, return `null` for
`subscription_status`, `monthly_value`, **and** `package_name`. Keep `months_used /
months_total`, `earned_so_far`, and the referral `status` untouched (history stays).

Frontend — `client/src/features/affiliate/AffiliateReferrals.jsx` already renders `—`
for null package/monthly value; make the Subscription column also render `—` when
`subscription_status` is null instead of a StatusBadge.

### B2. Projected monthly = only landlords actively paying
`server/services/affiliate_service.py` lines 415–423: the loop checks the *referral*
status but not the landlord's *subscription* status, so trial landlords are counted.
Add: skip unless `sub.status == SubscriptionStatus.active.value`. Completed referrals
are already excluded. (In seed data this means Sunrise — trial — stops inflating the
projection.)

### B3. "Total withdrawals" card on the affiliate dashboard
The dashboard API already returns `total_withdrawn` (sum of **paid** withdrawals,
`affiliate_service.py` ~line 405). `client/src/features/affiliate/AffiliateDashboard.jsx`
(~lines 65–74) never renders it. Add a SummaryCard "Total withdrawn" with a wallet/bank
icon alongside the existing cards.

### B4. Seed-data consistency (the 350 vs 280 confusion)
Root cause, for the record: `server/seed.py` seeds Acme (7 units) with `"package":
"Growth"` and hardcoded 280.00 subscription transactions (Growth = 40/unit), but
Growth's band is 21–70 units, so the app correctly re-bands Acme into Starter
(50/unit → 350). Not an app bug — inconsistent demo data.

**Approved fix:** reseed Acme's subscription transactions at **350.00** (the
`ACME-SUB-001` entry in `_landlord_specs` and the `SEED-VERIFIED-…` verified-payment
amounts for landlord Acme). Leave the package spec as the app resolves it (Starter).
After changing seed.py, note in your handoff that a reseed is required for the demo DB
to reflect it — do not silently wipe the owner's database; reseed only if the owner's
usual reseed flow is already part of verification.

---

## Part C — Payments page

### C1. Bank-statement upload → 3-step wizard (the big build)
Today only step 1 exists: `BankStatementReview.jsx` lists parsed transactions with
checkboxes and imports them — **unmatched and unallocated**. The backend import
(`payment_routes.py` `import_statement_transactions`) accepts `tenant_mappings` but the
UI never sends any, and imported payments are created `confirmed` **without any
allocation**, so they never reduce tenant balances. Replace the page with a 3-step
wizard (keep the route `LANDLORD_ROUTES.bankStatementReviewPath(id)`):

**Step 1 — Select.** Current table (date, description, reference, amount, imported).
Add select-all / clear-all. Only non-imported rows selectable. Next → step 2 with the
checked rows.

**Step 2 — Match.** One row per selected transaction: txn details + a tenant Select
(searchable if the existing Select supports it). Two actions:
- **Auto-match** button: for every unmatched row, look for a tenant whose
  `account_number` appears (case-insensitive substring) in the transaction's
  `reference` or `description`; fill the tenant select where exactly one tenant
  matches. Implement as a pure-frontend match over the already-loaded tenants list —
  no new backend endpoint needed (tenant list incl. `account_number` is already
  available via the tenants query).
- Manual: pick any tenant per row, or leave unmatched.
Show a per-row match state chip (Matched / Unmatched). Next → step 3.

**Step 3 — Allocate.** Only matched rows participate; unmatched rows are listed in a
separate "will import as pending review" note (approved behaviour: they import as
`pending` unmatched payments and get resolved later via the review modal, see C2).
Per matched row, default mode **Auto** (badge: "allocated by your priority order");
the landlord can expand a row to switch it to **Manual** and edit per-line amounts —
fetch lines from the existing `GET /api/payments/tenants/<id>/outstanding-items`.
Bulk controls: "Auto-allocate all checked". Over-allocation per row blocks Save
(same guard as ConfirmPaymentModal). Unallocated remainder becomes advance credit
(existing engine behaviour — surface it, don't reimplement it).

**Save.** Extend `POST /api/payments/bank-statement/<id>/import` to accept:
```json
{
  "transaction_ids": [..],
  "tenant_mappings": {"<txn_id>": tenant_id},
  "allocations": {"<txn_id>": {"mode": "auto"} | {"mode": "manual", "lines": [{"line_item_id": n, "amount": x}]}}
}
```
For each matched txn: create the Payment (source `bank_statement`, status `confirmed`)
then run the allocation through `allocation_service` (auto via `auto_allocate` with the
landlord's priority settings, manual via the same path ConfirmPaymentModal's confirm
uses). For unmatched txns: create the Payment with `tenant_id=None` and status
**`pending`** (not confirmed) so it shows the amber Review button on the payments page.
Keep the endpoint backward compatible (missing `allocations` ⇒ old behaviour is
acceptable only for unmatched rows; matched rows must allocate).

After save: toast + navigate back to Payments.

### C2. Co-pilot / pending payment review modal — add tenant matching
`client/src/features/landlord/payments/ConfirmPaymentModal.jsx` already shows the
auto-allocation preview pre-seeded into an editable manual table, with Auto/Manual
toggle and Confirm/Decline — that matches the owner's intent. Two gaps:

1. **Unmatched payments break it.** `GET /api/payments/<id>/allocation-preview`
   (`payment_routes.py` ~line 365) calls `auto_allocate(pay.tenant, …)` with a null
   tenant and dies. Fix the endpoint to return a clean shape for tenant-less payments
   (e.g. `{"amount": .., "unmatched": true, "outstanding": []}`) instead of 500.
2. **No tenant picker in the modal.** Add a tenant Select at the top: required when the
   payment has no tenant (shows "Match this payment to a tenant first"), editable when
   it has one (re-match). Changing it re-fetches the preview for that tenant (add a
   `?tenant_id=` override param to the preview endpoint) and the confirm mutation must
   send the chosen `tenant_id` so the backend assigns it before allocating.
Confirm stays disabled until a tenant is chosen. Behaviour after confirm is unchanged:
allocations recorded, statuses updated, balance running.

This modal is the single review surface for BOTH co-pilot payments (when the landlord's
setting is "review before allocation") and pending unmatched bank-statement imports
from C1.

### C3. Allocation rules — verify, don't rebuild
`allocation_service.py` already enforces: only `open` line items on non-deleted,
non-void invoices are allocatable; a fully-covered line/invoice goes `paid`
("complete"), a partially-covered invoice goes `partial`, an untouched one stays
`open`; `rolled` lines are excluded everywhere. Do not change the engine. In Part G,
prove each of these transitions in the browser.

---

## Part D — Invoices page

### D1. Invoice form: multi-select name builder drives the lines (approved design)
`client/src/features/landlord/invoices/InvoiceForm.jsx`:
- **Remove** the "Invoice type" Select (hardcoded `INVOICE_TYPES`).
- Add a **multi-select** at the top listing every charge item the categories produce —
  the same option set `chargeOptions` already builds (`"Rent — Deposit"`, `"Rent —
  Balance"`, `"Rent — This month"`, `"Water — Deposit"` … for every active invoice-kind
  ChargeCategory), plus **"Other (custom)"** which prompts for a free-text name. Any
  number of selections (1..n). Render selections as removable chips.
- **Selection ⇄ lines sync:** each selected item adds one line below with a fixed label
  (no per-line dropdown anymore) and editable amount + description; removing a chip
  removes its line; a custom chip's line uses the typed name. Editing an existing
  invoice seeds chips from its line items.
- **Invoice name:** `title` = the selected item names joined with ", " (e.g.
  `Rent, Electricity, Water`). Send it as `title`; keep sending `invoice_type:
  "custom"` for backend compatibility (the field, filters and generators stay).
- Keep tenant, dates, status-on-edit, and the "combine into this month's open invoice"
  checkbox exactly as they are.

### D2. Table "Item" column shows the name
`InvoicesPage.jsx` column `item` currently renders `row.invoice_type`. Render
`row.title || row.invoice_type` (older invoices without a title keep showing type).
Backend already stores/serialises `title` — check the list serializer includes it.

### D3. Generate menu becomes dynamic — one entry per category
`InvoicesPage.jsx` Generate dropdown keeps its five fixed entries (rent / recurring
bills / penalty / custom / bulk add) and **appends one entry per active invoice-kind
ChargeCategory** (e.g. "Generate Agreement invoices", "Generate Penalty invoices",
"Generate Garbage invoices" — whatever the landlord created). Fetch via the existing
`useGetChargeCategoriesQuery`. Clicking a category entry opens a generator modal
prefilled for that category: filter tenants (property / group / all), set amount
(default from category if it has one), issue+due dates, subcategory (default
"current"), then bulk-create one invoice per selected tenant through the existing bulk
endpoint (`POST /api/invoices/bulk` or the generator endpoint the fixed modals use —
reuse `GenerateCustomInvoices.jsx` as the base, parameterised by category, rather than
writing a new modal from scratch). New categories must appear in the menu with no code
change. De-duplicate: if a category duplicates a fixed generator (e.g. "Rent"), the
fixed entry wins — skip the dynamic one.

Everything else on the page (Categories manager, Download all, Add invoice) already
exists — verify in Part G.

---

## Part E — Utilities page

### E1. Bulk upload must use created utility categories
`client/src/features/landlord/utilities/BulkUploadUtilities.jsx` uses hardcoded
`UTILITY_ITEMS` (`constants.js:60`). Replace with `useGetChargeCategoriesQuery({ kind:
"utility" })` (same source `RecordUtilityForm.jsx` already uses), sending
`category_id` and letting the server derive the item name (the create endpoint already
resolves categories). Metered categories show previous/current reading columns;
non-metered show a flat amount column. Remove `UTILITY_ITEMS` if nothing else uses it.
Same for the `RATED_ITEMS` special-casing in `UtilitiesPage.jsx` — drive "has a rate"
off the category (`is_metered` + whether a rate resolves) rather than hardcoded names
where feasible; where only water/electricity have property rates, keep the amount
override input for other metered categories (current backend behaviour: no rate ⇒
explicit amount required — keep it and surface a clear hint).

### E2. Invoicing a utility — naming rules
The "Add to invoice" modal already offers **Create new invoice** vs **Add to this
month's invoice** — keep it. Fix the naming in `utility_routes.py`
`add_reading_to_invoice` (and the bulk-generate path):
- New invoice: `title` = the utility's category name (e.g. "Electricity").
- Combine into existing: **append** the utility name to the invoice's `title` if not
  already present — `"Rent"` becomes `"Rent, Electricity"`. (Comma-joined, matching D1's
  name format.)

### E3. Per-category "Generate invoices" on the Utilities page
Add a **Generate invoices** dropdown to the Utilities page header listing every utility
category. Choosing one opens a modal: property, reading month, then bill **all
uninvoiced readings** of that category/month through the existing
`bulk_generate_utility_invoices` endpoint (`utility_routes.py` ~line 363), with the
same new-vs-combine choice. (This is the "for utilities you bulk-feed readings first,
then generate" flow — a category with no readings for the month gets a clear empty
message, not a silent no-op.) The billing step that already exists at the end of
BulkUploadUtilities stays; this adds the standalone path for readings recorded earlier.

### E4. Record utility — already compliant, verify only
`RecordUtilityForm.jsx` already selects from utility categories, switches
metered/non-metered fields, validates readings, and the row action offers invoicing.
No redesign — verify in Part G.

---

## Part F — Tables cut off on landlord pages

Every table renders through `client/src/components/tables/ResponsiveTable.jsx`, which
already has its own `.table-scroll` horizontal scrollbar and `min-w-0` on its own
wrapper. The cutoff happens on pages that put the table inside a **`flex-1` wrapper
without `min-w-0`** next to a `FilterPanel` (e.g. `PaymentsPage.jsx` line ~198,
`InvoicesPage.jsx` line ~184): `min-width: auto` on the flex item lets the table's
intrinsic width push past the viewport, and the inner scrollbar never engages — the
page just clips.

Fix: add `min-w-0` to that `flex-1` table wrapper on **every** landlord page using the
FilterPanel+table layout (payments, invoices, tenants, units, properties, utilities,
expenses, communications, statements, audit trail… grep for `className="flex-1"`
siblings of `FilterPanel` and for `lg:flex-row` layouts). Then sweep: if any other
ancestor still prevents shrinking (grids need `min-w-0` on their cells too), fix it at
that ancestor. Acceptance (verify in Part G): at **every** viewport width — phone
(~375px), tablet, laptop (~1280px), desktop — no landlord page scrolls horizontally at
the page level, and any table wider than its box shows ResponsiveTable's own
horizontal scrollbar that actually scrolls to the last column. Desktop-width table
mode matters most (mobile stacks into cards already).

---

## Part G — MANDATORY browser verification (do all of it, in the UI)

Environment: see memory `sahil-pay-env-setup` for running server + client locally.
Log in as the seeded landlord (`landlord@sahilpay.test` / `Landlord@123`) unless noted.

**Auth:** Log out. On Login and Register: back button returns to home; eye toggle
reveals/hides the password and stays toggled. Register page: both password fields.

**Affiliate portal** (seeded affiliate account): dashboard shows the new Total
withdrawn card with a correct sum; Projected monthly counts ONLY active-subscription
landlords still in-window (with seed data: Acme completed ⇒ excluded, Sunrise trial ⇒
excluded — check the number matches expectation); referrals table: completed referral
rows show "—" for Package, Subscription and Monthly value; horizontal scrollbar present.

**Payments page — click every button:**
1. **Report** → PDF downloads and opens.
2. **Record payment** → create for a tenant with open invoices; verify auto-allocation
   reduces the right invoice (open → partial when partly covered, → paid when fully
   covered); record another that overpays and confirm the excess lands as advance credit.
3. **Upload statement** → upload a CSV/PDF statement (craft a test CSV whose rows
   include tenant account numbers like `ACME-T002` in the description); wait for parse;
   walk the wizard: select all, deselect one; step 2: Auto-match fills tenants whose
   account numbers appear, match one manually, leave one unmatched; step 3:
   auto-allocate all, switch one row to manual and edit amounts, save. Verify: matched
   payments are confirmed AND allocated (tenant balances moved, invoice statuses
   updated); the unmatched one appears as pending with the amber Review chip.
4. **Review modal:** open the pending unmatched payment → match it to a tenant in the
   modal → preview loads → adjust manually → confirm → allocation applied. Also review
   a co-pilot pending payment if one exists/can be simulated.
5. Row actions: Edit, Send receipt, Download receipt, Change tenant, Remind tenant,
   Delete — each works.
6. Filters apply and reset; pagination works; table scrolls horizontally at narrow widths.

**Utilities page — click every button:**
1. **Utility categories** → create a new metered category (e.g. "Gas") and a
   non-metered one; both immediately appear in Record reading, Bulk upload, and the
   new Generate invoices dropdowns.
2. **Record reading** → metered (property, unit, previous/current, month) and
   non-metered (flat amount); saved rows appear in the table.
3. Row action **Add to invoice** → "Create new invoice": invoice title = utility name;
   → "Add to this month's invoice" on a tenant with an open invoice: utility appended
   to invoice title ("Rent, Electricity") and line added.
4. **Bulk upload** → select property, utility (from categories!), month; fill readings
   for several units; save; then bill them via the flow's billing step.
5. **Generate invoices** (new) → pick a category + month with uninvoiced readings →
   invoices created/combined correctly; empty month gives a clear message.

**Invoices page — click every button:**
1. **Add invoice** → multi-select 3 items (e.g. Rent — This month, Water — This month,
   custom "Key replacement") → three lines appear with fixed labels → fill amounts →
   save → table Item column shows "Rent, Water, Key replacement"; open the PDF.
2. Edit that invoice → chips seeded from lines; remove one; save; name updates.
3. **Generate** menu: run ALL of — Generate rent invoices, Generate recurring bills,
   Generate penalty invoices, Generate custom invoices, Bulk add invoices — end to end
   (pick tenants/properties, generate, verify created invoices' names, amounts, dates,
   units).
4. Dynamic entries: after creating a new invoice category in step "Categories", it
   appears in Generate; run it for ≥2 tenants and verify the resulting invoices.
5. **Categories** manager: add, edit, deactivate; deactivated ones leave the dropdowns.
6. **Download all** → zip downloads. Row actions: Edit / Send / Download / Delete.
7. Allocation cross-check: with an invoice **closed (paid)** and one **open**, record a
   payment — only the open one receives allocation.

**Responsive sweep (Part F):** for EVERY landlord page (dashboard, properties, units,
tenants, payments, invoices, utilities, expenses, communications, reports/statements,
settings incl. audit trail): at 375px, 768px, 1280px, 1920px — no page-level horizontal
scroll; wide tables get a working inner scrollbar reaching the last column and the
row-actions menu stays clickable.

Record any failure found during Part G, fix it, and re-verify before finishing.
