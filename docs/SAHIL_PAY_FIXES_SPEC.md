# SahilPay — Remediation Spec (17 Features + Backbone)

> **Purpose.** This document is the implementation brief handed to Claude Code. It lists every issue found during testing, the **root cause in the actual code**, the **exact changes required** (backend + frontend), and **acceptance criteria** that must be verified before an item is considered done. Work items **one at a time**, top to bottom, and run the acceptance check for each before moving on.
>
> **Repo layout.** Backend = Flask + SQLAlchemy under `server/` (`models.py`, `routes/`, `services/`, `tasks/`). Frontend = React + RTK Query under `client/src/` (`features/**`, `components/**`, each feature has an `*ApiSlice.js`). Money is `Decimal`/`Numeric(12,2)`; SMS balance is an **integer credit count**.
>
> **Global rules for every change:**
> - Never break the transaction contract in services: allocation/audit helpers **flush, the route commits**.
> - Every create/update/delete must still write through `services/audit_service.record_audit(...)` (or `utils.audit`).
> - Add/adjust an Alembic migration under `server/migrations/versions/` for any schema change; do not hand-edit the DB.
> - After each backend change, exercise the real flow (see `verify` skill), not just unit tests.

---

## ★★★ THE BACKBONE — INVOICING → PAYMENTS → REPORTS (READ FIRST) ★★★

**This is the most important part of SahilPay. If invoicing, payment allocation, and reporting are not exactly correct, nothing else matters.** Features #5, #6, #7, #8, #13, #14 below are all facets of this backbone. The three branches and their contract:

1. **INVOICING** — a bill issued to a tenant, header + line items (`Invoice` + `InvoiceLineItem`, `server/models.py:1163` / `:1227`). Every charge is one line item with an `item` label and `amount`. Invoices carry a `total_amount`, `amount_paid`, `balance`, and `status` (`draft/void/open/partial/paid`, `InvoiceStatus` at `models.py:185`). **Rule: `balance = total_amount − amount_paid` always, and `status` is derived from that, never set by hand except `draft`/`void`.** Utilities are invoiced per **landlord-defined utility type** (see #6/#8), not the hard-coded 4-value enum.

2. **PAYMENTS** — money received (`Payment` at `models.py:1289`), linked to invoices through `PaymentAllocation` (`models.py:1361`). Allocation is the crux. It is done in `services/allocation_service.py` in one of two modes:
   - **Manual** — landlord passes explicit `[{invoice_id, amount_allocated}]` rows and can split one payment across many invoice items exactly how they choose.
   - **Automatic** — `auto_allocate()` spreads the amount across outstanding invoices in the landlord's configured **category priority order** (`Landlord.allocation_priority`, a CSV), oldest-first within a category.
   - **Rule: `sum(allocations) ≤ payment.amount`; any unallocated remainder becomes tenant advance/credit.** `apply_allocations()` (`allocation_service.py:123`) updates each invoice's `amount_paid/balance/status` and must be the **only** place invoice paid-state changes on payment.

3. **REPORTS** — everything in `server/services/report_generators.py` + `report_builder.py`, surfaced under `client/src/features/landlord/reports/**`. **Every figure in every report (amount invoiced, amount paid, amount due, per-tenant balance, running balance) must be recomputed from `Invoice` + `PaymentAllocation` rows — never from a cached/denormalized field that can drift.** The tenant statement and property statement are the two that testing flagged as wrong (#13, #14).

**Non-negotiable invariants (assert these in code and in tests):**
- `invoice.balance == invoice.total_amount − sum(alloc.amount_allocated for alloc in invoice.payment_allocations)` for every non-void invoice.
- `invoice.amount_paid == sum(alloc.amount_allocated ...)`.
- A tenant's outstanding balance == `sum(open/partial invoice balances) − tenant advance credit`.
- Reports agree with the ledger to the cent.

---

## Feature 1 — Tables must not overflow right; horizontal scrollbar always present

**Where:** `client/src/components/tables/ResponsiveTable.jsx` (the single table primitive; desktop path wraps `<table class="w-full">` in `<div class="glass max-h-[65vh] overflow-auto">`). Also any page that renders a raw `<table>` outside this component (grep `client/src` for `<table`).

**Root cause:** The desktop wrapper already has `overflow-auto`, but the table overflows the *page* instead of scrolling inside its box. This is the classic flex/grid `min-width:auto` trap — the table's ancestor containers (page `<main>`, feature page wrappers) don't have `min-w-0`, so the intrinsic width of a many-column, `whitespace-nowrap` table pushes the whole layout wider than the viewport rather than letting `overflow-auto` engage. On the tenant table (widest) this is where it's worst.

**Changes:**
1. In `ResponsiveTable.jsx` desktop branch, change the wrapper to force horizontal scroll and always show the bar:
   - Wrapper: `className="glass w-full max-w-full min-w-0 overflow-x-auto overflow-y-auto max-h-[65vh] table-scroll"`.
   - Keep `min-w-full` on the `<table>` (not just `w-full`) so it fills when narrow but can exceed the box when wide.
2. Add a `.table-scroll` utility (in the global stylesheet, e.g. `client/src/index.css` / Tailwind layer) that makes the horizontal scrollbar **always visible** (non-negotiable per requirement) and theme-styled:
   ```css
   .table-scroll { scrollbar-gutter: stable; }
   .table-scroll::-webkit-scrollbar { height: 10px; width: 10px; }
   .table-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,.25); border-radius: 9999px; }
   .table-scroll { scrollbar-width: thin; overflow-x: scroll; } /* scroll, not auto → bar always rendered */
   ```
   Use `overflow-x: scroll` (not `auto`) so the bar renders even when the table already fits — the requirement explicitly says the bar is always there, and if the table fills the space it simply won't move.
3. **Fix the ancestor chain.** Add `min-w-0` (and `max-w-full`) to the layout containers so the scroll box can actually shrink: audit `client/src/routes/AppRoutes.jsx` and `client/src/components/layout/DashboardLayout.jsx` main content wrapper (per memory, the real layout is `AppRoutes.jsx`), plus each feature page's top wrapper (`PaymentsPage.jsx`, tenants/units/properties list pages). The `<main>`/content column must be `min-w-0 overflow-x-hidden` at the page level so nothing but the table box scrolls sideways.

**Acceptance:**
- On a narrow laptop/mobile-emulated viewport, open Landlord → Tenants (widest table). The page body never scrolls horizontally; only the table box does, and its horizontal scrollbar is visible.
- Repeat for Payments, Units, Properties, Invoices, Admin tables, Tenant portal tables. No table pushes content off-screen right.

---

## Feature 2 — Landlord "SMSs left" pill must show the landlord's real SMS balance

**Where:** the pill/icon in the landlord chrome (grep `client/src/features/landlord` for `SMS` / `sms_balance` / the "SMSs left" element; likely `LandlordSidebar.jsx` or the dashboard header). It links to Communications → SMS. Backend truth: `Landlord.sms_balance` = `Column(Integer)` at `models.py:582` (a **credit count**, decremented per segment on send — see `CommunicationLog` note `models.py:1713`). Pricing lives in the admin-editable `SmsPricingConfig` singleton (`models.py:2323`: `default_price_per_sms` default `1.00`, `custom_price_per_sms` default `0.50`), read via `services/sms_billing.py:load_rates()`.

**Root cause:** the pill shows a stale/hard-coded/wrong number rather than the live `landlord.sms_balance` for the logged-in landlord.

**Changes:**
1. Ensure the landlord "me"/dashboard endpoint returns the current `sms_balance` and the landlord's **sender mode** (default `SahilPay` vs own Africa's Talking sender ID — see `SmsProviderSettings.jsx` / `smsProviderApiSlice.js`). Add to the landlord bootstrap payload if missing.
2. Bind the pill text to that value: `"{sms_balance} SMS left"`. Clicking still routes to Communications → SMS tab.
3. On the Communications/SMS screen, show: current balance (credits), sender mode, and the **fixed admin price per SMS** for this landlord — `custom_price_per_sms` if they've connected their own sender ID, else `default_price_per_sms`. **The price is fixed by admin (currently KES 1.00); the landlord never sets it.** Regardless of sender mode, cost = `segments × that fixed price`.
4. Verify every send path decrements `landlord.sms_balance` by the segment count (`sms_billing.count_segments`) and refuses to send when balance < required segments.

**Acceptance:** Set a landlord's `sms_balance` to 100 in the DB → pill reads "100 SMS left". Send a 1-segment SMS → pill reads 99. Connecting an own sender ID switches the displayed per-SMS price from default to custom, but the balance semantics stay integer credits.

---

## Feature 3 — Row-action ("options") menu must stay fully on screen and be scrollable

**Where:** `client/src/components/ui/Dropdown.jsx` — the portal menu used by **every** table's row actions (landlord tenants/units/properties/payments, admin, tenant, team members).

**Root cause:** `place()` (`Dropdown.jsx:28`) only flips the menu **upward** when it doesn't fit below *and* there's room above (`rect.top > menuHeight`). With a tall menu (Tenants row has ~6–7 actions: shift, delete, edit, view, view transactions, send SMS, remind) on a short viewport, **neither** direction fits, so it renders downward and runs off the bottom with **no internal scroll**. Additionally, the global capture-phase `window.addEventListener("scroll", close, true)` (`:56`) means even if we add internal scroll, scrolling inside the menu closes it.

**Changes (in `Dropdown.jsx`):**
1. Compute the menu height against the viewport and **clamp** it. Add a `maxHeight` to `coords`:
   - `const available = openUpward ? rect.top - 8 : window.innerHeight - rect.bottom - 8;`
   - `maxHeight = Math.min(menuHeight, Math.max(available, 160))` — never taller than the space available, floor ~160px so at least a few items show.
2. Clamp `top`/`left` into the viewport: `top = Math.max(8, Math.min(top, window.innerHeight - maxHeight - 8))`; `left = Math.max(8, Math.min(left, window.innerWidth - MENU_WIDTH - 8))`.
3. On the portal menu `<div>`, apply `style={{ ..., maxHeight }}` and class `overflow-y-auto overscroll-contain` so overflowing items scroll **inside** the menu.
4. Stop the internal scroll from closing the menu: in the capture scroll handler, ignore events originating inside the menu — `function onScroll(e){ if (menuRef.current?.contains(e.target)) return; close(); }` and register `onScroll` instead of `close`. (Ancestor/page scroll still closes it, as intended.)

**Acceptance:** On a short viewport, open the Tenants row menu on the last visible row — all actions are reachable, the menu is fully on-screen, and if it's taller than the space it scrolls internally without closing. Verify the same on Units, Properties, Payments, Invoices, Admin tables, Tenant portal, Team members.

---

## Feature 4 — "Send reminder / Send SMS" must prompt for channels before sending

**Where:** the row action on Landlord → Tenants and Landlord → Payments that reminds a tenant of their balance; send paths in `server/routes/communication_routes.py` + `services/communication_service.py` + `notification_service.py`. Channels available: **SMS, Email, In-app notification, WhatsApp** (`MessageChannel` enum `models.py:276` covers sms/whatsapp/email; in-app via `notification_service`).

**Root cause:** the action fires straight to the settings default channel with no confirmation step / channel picker.

**Changes:**
1. Add a **channel-selection modal** (new component, e.g. `client/src/features/landlord/communications/SendReminderModal.jsx`) opened by "Remind" / "Send SMS" from both the Tenants and Payments row menus. It shows the resolved message preview and four toggleable channels (SMS, Email, In-app, WhatsApp), **pre-checked from the landlord's settings default** but fully editable, plus a Confirm button.
2. Only the ticked channels are sent. Backend endpoint accepts `channels: ["sms","email","in_app","whatsapp"]` and fans out to each corresponding service; each send is audited and (for SMS) decrements `sms_balance`.
3. The default in Settings remains the pre-check source of truth, but the modal always appears — sending never bypasses it.

**Acceptance:** From a tenant with a balance, click Remind → modal appears pre-checked with the settings default → uncheck WhatsApp, keep SMS + In-app → Confirm → exactly an SMS and an in-app notification are created (verify `CommunicationLog` + notification rows), `sms_balance` drops by the SMS segment count. Repeat from the Payments page.

---

## Feature 5 — Record payment: "pay full" + choose manual vs automatic allocation

**Where:** `client/src/features/landlord/payments/RecordPaymentForm.jsx`, `ConfirmPaymentModal.jsx`, `paymentApiSlice.js`; backend `server/routes/payment_routes.py` (`create_payment`) → `services/allocation_service.py`.

**Root cause / required behaviour:**
- **"Pay full" on a line must allocate the whole payment amount to the selected invoice**, capped at that invoice's outstanding balance is fine, but the requirement is: if payment = 5,000 and the invoice due = 11,000, "pay full" puts the entire 5,000 on that invoice (partial-pays it). Today the button's semantics must be verified against `RecordPaymentForm.jsx:116` ("pay full") — make "pay full" set that row's allocation to `min(remaining_unallocated_payment, invoice_balance)`, i.e. dump the rest of the payment onto this invoice.
- **The record form must offer a mode toggle: "Allocate automatically" vs "Allocate manually"** — mirroring what's already possible when editing an unconfirmed payment.
  - *Automatic* → send no explicit allocations (or a flag `auto_allocate: true`); backend runs `auto_allocate()` using the landlord's `allocation_priority`.
  - *Manual* → landlord allocates per invoice item (select item, "pay full" or type an exact amount); backend applies the explicit rows.
- This mode toggle must exist **both when recording a new payment and when editing a pending/unconfirmed one** (the edit path already allows manual allocation — bring the create path to parity).

**Changes:**
1. Add an allocation-mode radio/segmented control to `RecordPaymentForm.jsx` (`Automatic` default = follow settings; `Manual` = show the per-invoice allocation editor that already exists at `:94`).
2. Fix "pay full" to allocate `min(payment − alreadyAllocatedElsewhere, invoiceBalance)`.
3. `create_payment` in `payment_routes.py`: when `auto_allocate` is set (or no allocations given and mode=auto), call `allocation_service.auto_allocate(tenant, amount, landlord)` then `apply_allocations(...)`; otherwise apply the explicit rows. Enforce `sum(allocations) ≤ amount`; remainder → tenant advance.
4. Editing a pending payment must let the user **re-allocate** (delete old `PaymentAllocation` rows, re-apply) with the same manual/auto choice.

**Acceptance:** Record a 5,000 payment against a tenant with an 11,000 invoice, Manual + pay-full → one allocation of 5,000, invoice becomes `partial` with balance 6,000. Record another with Automatic → it clears invoices in the settings priority order. Editing an unconfirmed payment lets you move the money between line items and re-save.

---

## Feature 6 — Landlord-defined utilities + detailed 3-category auto-allocation

**This is the biggest data-model change and underpins #5, #8, #14.**

**Where:** `UtilityItem` enum (`models.py:244`) is hard-coded to `water/electricity/garbage/security`. `UtilityReading` (`models.py:1577`) references it. Auto-allocation categories are only 5 coarse buckets in `services/allocation_service.py:33` and `client/src/features/landlord/settings/AllocationPriorityEditor.jsx`.

**Required model:** The landlord must be able to **create their own utilities**, and every chargeable thing falls into **three categories** for allocation and tracking:
- **Deposits** — e.g. rent deposit, water deposit, electricity deposit, security deposit.
- **Balances** (arrears carried forward) — e.g. rental balance, electricity balance, security balance.
- **Current-month utilities** — this month's water, electricity, garbage, security, and any custom ones.

**Changes (backend):**
1. New table `LandlordUtilityType` (per-landlord catalogue): `id, landlord_id, name, category (enum: deposit|balance|current_utility), is_metered (bool), default_rate (Numeric, nullable), is_active`. Seed each existing landlord with their current utilities (water/electricity/garbage/security as `current_utility`) on migration.
2. Replace the hard-coded `UtilityItem` usage: `UtilityReading.utility_item` and invoice line-item categorisation should reference a `landlord_utility_type_id` (keep the string label for display/back-compat). Metered utilities use readings; non-metered (garbage, security) are flat charges (ties into #8).
3. Rework allocation categories in `allocation_service.py` to be driven by these three categories **per utility type**, not the 5 fixed strings. `categorize_invoice()` maps an invoice/line to `(category, utility_type)`; `auto_allocate()` walks the landlord's configured order which now includes each utility type within each of the 3 categories.

**Changes (frontend):**
1. New Settings screen "Utilities" (or extend `client/src/features/landlord/utilities/`) to **create/edit/deactivate** utility types, each tagged deposit / balance / current-utility and metered or flat.
2. Rework `AllocationPriorityEditor.jsx`: instead of 5 fixed rows, render the three category columns (Deposits, Balances, Current utilities) and let the landlord order **how each utility/category is cleared** when auto-allocating. Persist an expanded priority structure (extend `Landlord.allocation_priority`, or add a JSON `allocation_priority_json`).
3. Invoice/utility recording forms populate their utility dropdowns from the landlord's utility catalogue.

**Acceptance:** A landlord creates a custom "Parking" current-utility and a "Security deposit". Recording a payment with Automatic allocation clears charges in exactly the configured deposit/balance/current order. Reports (#14) show each utility tracked separately.

---

## Feature 7 — Invoice auto-confirms when fully paid; manual status override on edit

**Where:** `services/allocation_service.py:144` already sets `status = paid` when `balance <= 0`, `partial` when partially paid. Invoice edit UI in `client/src/features/landlord/invoices/InvoiceForm.jsx`.

**Root cause / required:** Confirm the automatic transition fires on **every** allocation path (manual create, auto create, edit re-allocation, tenant-submitted payment confirmation) — not just some. And the terminology the UI shows for a cleared invoice should read as **confirmed/approved** (map `paid` → "Confirmed/Approved" label). Also add a manual status control on the invoice edit form so a landlord can force `confirmed/approved` (and back) when needed — but the automatic transition must remain the default.

**Changes:**
1. Ensure `apply_allocations()` is the sole writer of invoice paid-state and is called from all confirm paths (check `payment_routes.py` confirm endpoint + tenant-submitted confirmation). When `balance <= 0` → `paid` (labelled Confirmed/Approved in UI).
2. Add a status selector to `InvoiceForm.jsx` edit mode (allowed transitions only; audited).
3. Wherever invoice status is rendered (`StatusBadge`/`Badge`), map `paid` → "Confirmed" so a fully-cleared invoice reads as confirmed automatically.

**Acceptance:** Fully allocate a payment to an invoice → its status flips to paid/"Confirmed" with no manual action. Partially pay → "partial". On edit, a landlord can manually set the status and it's audited.

---

## Feature 8 — Utility recording: previous & current reading fields must be optional

**Where:** `client/src/features/landlord/utilities/RecordUtilityForm.jsx`; model `UtilityReading` (`models.py:1577`) — `previous_reading` is already `nullable=True`, `current_reading` is `nullable=False` with a check `current >= previous when previous not null`.

**Root cause / required:** Non-metered utilities (garbage, security, and custom flat charges) have no meter readings, yet the form forces previous/current readings. Both reading fields must be **optional** so flat utilities can be recorded as a straight amount.

**Changes:**
1. Tie this to #6's `is_metered` flag: metered types → show previous/current reading + consumption; non-metered → show a single flat **amount** field, no readings.
2. Backend: allow a `UtilityReading` (or a direct utility charge) with null readings and an explicit amount for non-metered types. Relax the frontend validation so previous/current are only required when metered.
3. Ensure each recorded utility is stored so it can be reported separately across all reports (#14).

**Acceptance:** Record "Garbage — KES 500" for a unit with no readings → saves. Record "Water" metered with previous/current → consumption computes. Both appear as separate line items on the invoice and separately in reports.

---

## Feature 9 — Remove number-input spinners / scroll-to-increment everywhere

**Where:** ~22 `type="number"` inputs across `client/src` (grep confirmed). Base component `client/src/components/ui/Input.jsx` (a passthrough `<input>`). The spinner arrows and mouse-wheel increment (the "0.001" nudge) are native `type="number"` behaviour.

**Root cause:** native number inputs render step spinners and change value on wheel scroll/focus.

**Changes (do it once, globally):**
1. Add a global CSS rule to kill spinners:
   ```css
   input[type="number"]::-webkit-outer-spin-button,
   input[type="number"]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
   input[type="number"] { -moz-appearance: textfield; }
   ```
2. In `Input.jsx`, when `type === "number"`, attach `onWheel={(e) => e.currentTarget.blur()}` so wheel scrolling never changes the value. **Preferred:** introduce a `MoneyInput`/`NumberField` that renders `type="text"` with `inputMode="decimal"` and a digit/decimal filter, and migrate money/quantity fields to it. Users type the figure manually; no increment/decrement affordance remains.
3. Sweep every money/quantity/reading input (payments, invoices, utilities, expenses, pricing/admin, tenant portal amounts) to the spinner-free control.

**Acceptance:** No number field shows up/down arrows; scrolling the wheel over a focused amount field never changes it; values are typed freely.

---

## Feature 10 — Balance sign convention (owed = positive/neutral; advance = negative)

**Where:** everywhere a balance is rendered — tenant dashboard, statements, tenants table, reports. Currency formatting `client/src/utils/currencyFormatter.js`; per-tenant balance derives from invoice balances minus advance credit.

**Required semantics:**
- **Balance = what the tenant owes, shown as a plain positive number with no sign.** Owes 5,000 → balance reads **5,000**.
- **Overpayment/advance → shown negative.** If they owed 5,000 and paid 6,000, net is 1,000 in their favour → balance reads **−1,000** (or label it "Advance 1,000"); the negative sign signals credit.
- Rationale from the requirement: "balance" is inherently the amount owed, so it needs no sign; only credit gets the minus.

**Changes:**
1. Centralise a `formatBalance(amount)` helper: `amount > 0` → `formatCurrency(amount)` (no sign); `amount < 0` → prefix `−` and optionally label "Advance"; `0` → `0`.
2. Replace ad-hoc balance rendering with it across tenant/landlord/reports so the convention is uniform. Make sure the underlying number's sign is consistent first (owed positive, credit negative) — audit the computation, not just the display.

**Acceptance:** Tenant owing 5,000 shows "5,000"; after overpaying to a 1,000 credit shows "−1,000" (or "Advance 1,000"), consistently on dashboard, statement, and tenants table.

---

## Feature 11 — Landlord notification templates must be relevant to tenants/team only

**Where:** landlord Notifications/Communications templates — `client/src/features/landlord/communications/MessageTemplates.jsx`, `communicationApiSlice.js`; model `MessageTemplate` (`models.py:1684`) + `MessageTemplateType` (`models.py:282`). Notifications feature under `client/src/features/notifications/`.

**Root cause:** the landlord's template list surfaces platform/admin→landlord items (e.g. "SMS balance low") that a landlord would never send to a tenant/team member. Those belong to the admin→landlord channel.

**Changes:**
1. Filter the landlord-facing template catalogue to **only landlord→tenant and landlord→team** templates. Valid examples: Balance reminder, Payment received/updated, Reminder to update utilities, Reminder to add units (team), Lease-expiry reminder, Custom.
2. Move platform alerts (low SMS balance, etc.) out of the landlord's send list — those are `Alert`/admin-originated and should only appear as *received* notifications, not as things the landlord composes.
3. Tag templates by audience (`RecipientType` tenant/team_member) and gate the picker by audience so the landlord only ever sees sendable-to-tenant/team options.

**Acceptance:** Landlord → Templates shows only tenant/team-relevant options; "SMS balance low" and similar platform alerts no longer appear as sendable templates.

---

## Feature 12 — Unify in-app messages ↔ notifications (tenant ⇄ landlord ⇄ admin)

**Where:** `TenantMessage` model (`models.py:1765`), `routes/tenant_message_routes.py`, `client/src/features/landlord/messages/`, `client/src/features/notifications/`, tenant portal messages.

**Required behaviour (confirm current + extend):**
- The **tenant messages page is in-app messaging**: a tenant sends a message to the landlord, landlord replies (a normal 2-way thread). **Confirm** it currently activates on a tenant-sent message (read `tenant_message_routes.py` + tenant portal send).
- The **landlord must also be able to initiate** messages from the messages portal, selecting **team members or tenants** as recipients.
- **Notifications are in-app only.** Messages/SMS are outbound SMS (render like WhatsApp threads). Emails are emails. Keep these channels conceptually distinct but **link them**: an in-app message should also surface as a notification, and a notification/template can be sent from the messages tab. Bi-directional across tenant⇄landlord and admin⇄(landlords/tenants).

**Changes:**
1. Add landlord-initiated compose to the messages portal (recipient = tenant or team member), reusing templates from #11.
2. Bridge messages ↔ notifications: creating an in-app message emits a notification to the recipient; the notifications UI can open/reply the underlying message thread.
3. Ensure admin can message landlords/tenants through the same primitive.
4. Verify SMS threads render WhatsApp-style (outbound bubbles) in the messages view.

**Acceptance:** Tenant sends a message → landlord sees it in messages **and** as a notification, can reply. Landlord composes a new message to a chosen tenant/team member → recipient receives it in-app + notification. Admin can message a landlord.

---

## Feature 13 — Tenant statement: chronological running balance (both sides)

**Where:** `client/src/features/landlord/reports/TenantStatement.jsx` and the tenant-portal statement; backend `server/services/report_generators.py` / `report_builder.py`, `routes/report_routes.py`, tenant side `routes/tenant_portal_routes.py`.

**Root cause / required:** The statement currently batches by type (all invoices, then all payments/utilities). It must instead be a **single chronological ledger**: every invoice and every payment as a dated row **in the order they occurred**, with a **running outstanding balance** recomputed after each row. Example: invoice → payment → invoice → payment → payment → invoice, each line moving the running balance. This applies to **both** the landlord-side statement and the tenant-side statement (same data source).

**Changes:**
1. Build the statement as a merged, time-ordered event stream: `debit` events (invoices, by `issue_date`/`created_at`) and `credit` events (payments/allocations, by `payment_date`/`created_at`). Sort by effective date then id.
2. Compute `running_balance` cumulatively down the list (debits increase owed, credits decrease). Follow the #10 sign convention for the final/any credit position.
3. Return one ordered array from the backend; render one table (date, description, charge, payment, running balance). Reuse the exact same builder for tenant portal and landlord views so they never diverge.

**Acceptance:** For a tenant with interleaved invoices and payments, the statement lists them in true chronological order with a running balance that ties out to the current outstanding at the bottom, identical on landlord and tenant views.

---

## Feature 14 — Property statement report accuracy (per-tenant, to the cent)

**Where:** `client/src/features/landlord/reports/PropertyStatement.jsx`; backend generators in `services/report_generators.py`.

**Root cause / required:** Per-tenant figures (amount invoiced, amount paid, **amount due / balance left**, and how a payment was allocated) must be **recomputed from `Invoice` + `PaymentAllocation`** honouring the actual manual/automatic allocation order — not from any drifting cached field. Statistics (totals, amount due per tenant) must match the ledger and the statement (#13).

**Changes:**
1. Rewrite the property-statement aggregation to derive per tenant: `invoiced = Σ invoice.total_amount`, `paid = Σ allocation.amount_allocated (+ advances)`, `due = Σ open/partial invoice balance`. Break utilities out by the #6 utility types.
2. Cross-check against the tenant statement builder (#13) — same numbers.
3. Add an assertion/test that report totals equal the sum of the ledger.

**Acceptance:** For a known property, every per-tenant due/paid/invoiced figure in the property statement equals what the tenant statement and the tenants table show; totals reconcile exactly.

---

## Feature 15 — Billing page: show plan name + correct next-billing date

**Where:** `client/src/features/landlord/settings/BillingSettings.jsx`, `billingApiSlice.js`; backend `routes/billing_routes.py`, `services/billing_service.py`, `services/trial_service.py`; models `Subscription` (`models.py:1923`), `Package` (`:1847`), `TrialConfig` (`:1990`).

**Required:**
- Show the **billing plan/package name** on the billing page (the landlord's `Package.name` and/or `Subscription.plan`).
- **Next billing date must start the day the trial ends** — for a landlord who registered with a trial, `next_billing_date` = trial end date; that's the first billing cycle.
- All of this must be **admin-editable in the backend** (ties into #16).

**Changes:**
1. Billing endpoint returns `package.name`, `subscription.plan`, `amount_due`, `next_billing_date`, trial status/end. Render the plan name prominently in `BillingSettings.jsx`.
2. On registration/trial start (`trial_service`), set `Subscription.next_billing_date` = trial end date. Verify existing landlords are backfilled.

**Acceptance:** Billing page shows e.g. "Plan: Growth (Package)" and a next-billing date equal to the trial-end date for a trialing landlord. Admin edits (from #16) reflect here.

---

## Feature 16 — Admin: view & edit a landlord's billing details from a package

**Where:** `client/src/features/admin/PricingPackages.jsx`, `adminPricingApiSlice.js`, `adminTrialApiSlice.js`; backend `routes/admin_pricing_routes.py`, `admin_trial_routes.py`; models `Subscription`, `TrialConfig`.

**Required:** Clicking a landlord inside a package (under Pricing) must show that landlord's **billing cycle, amount due, trial active?, trial end date**, and the admin must be able to **manually change** trial active status, amount due, and next-billing-date — with changes reflected to the landlord (#15).

**Changes:**
1. Admin landlord-detail drawer/endpoint returns `subscription.billing_cycle`, `amount_due`, `next_billing_date`, `status`, plus trial `is_active` + computed end date.
2. Add admin mutations to patch `Subscription.amount_due`, `Subscription.next_billing_date`, `Subscription.status`, and the per-landlord `TrialConfig` (`is_active`, duration/end). Audit each change.
3. Frontend: editable fields in the landlord detail view under the package; on save, invalidate the landlord's billing cache so `BillingSettings.jsx` shows the new values.

**Acceptance:** Admin opens a landlord under a package, sees billing cycle + amount due + trial status/end, edits amount due and next billing date, saves → the landlord's billing page reflects the change; edits are audited.

---

## Feature 17 — Default "Custom" package (admin-only, per-landlord unit price)

**Where:** `Package` model (`models.py:1847`, global table, has `is_featured/is_recommended/is_active`), `routes/admin_pricing_routes.py`, `PricingPackages.jsx`; per-landlord price via `Subscription`/`Landlord`.

**Required:** A **Custom** package exists by default. It behaves like other packages for the landlords assigned to it (they see it's Custom, their per-unit price, amount due, next due), **but**:
- It is **never featured, recommended, or shown publicly** (excluded from the storefront `to_public_dict` list).
- Landlords are **added manually by the admin**, and the admin sets a **per-unit price for that landlord** (for big-unit / negotiated deals).

**Changes:**
1. Add `is_custom` (Boolean, default false) to `Package`; seed one `is_custom=True` package named "Custom" (`is_featured/is_recommended/is_popular=False`). Exclude `is_custom` packages from the public pricing endpoint (`public_routes.py` storefront query) — even if flags were toggled.
2. Support a **per-landlord price override**: store the negotiated `price_per_unit` on the landlord's `Subscription` (use `subscription_cost`/a new `custom_price_per_unit` field) rather than on the shared `Package`. Amount due = `unit_count × custom_price_per_unit`.
3. Admin UI: an "Add landlord to Custom" action (next to landlords), then set that landlord's per-unit price. Landlord's billing page (#15) shows "Custom" + their per-unit price + amount due + next due.

**Acceptance:** Admin adds a 100-unit landlord to Custom at KES X/unit → landlord's billing shows Custom, X/unit, amount due = 100·X, next due date. The Custom package never appears on the public pricing page and cannot be featured/recommended.

---

## Feature 18 (bug) — Audit log records the WRONG tenant on payment submission

**Symptom:** Fay Tester (fayfay1999@gmail.com) submitted a payment to Russell Company, but landlord + admin audit logs show **Ruth Akinyi** as the submitter.

**Root cause (confirmed in code):** `routes/tenant_portal_routes.py:submit_payment` (`:355`) calls `record_audit(actor_user_id=int(get_jwt_identity()), ...)`. In `services/audit_service.py` (`:63–75`), `actor_full_name` is resolved by walking the **User's** profile relationships and taking the **first** match:
```python
for profile_attr in ("landlord_profile", "team_member_profile", "admin_profile", "tenant_profile"):
    profile = getattr(user, profile_attr, None)
    if profile: actor_full_name = f"{first} {last}"; break
```
A single login `User` can own **multiple `Tenant` profiles** (the same person/phone/email is a tenant under more than one landlord). `user.tenant_profile` therefore resolves to *some* tenant record — not necessarily the one who submitted **for this landlord**. So the description says "Fay Tester" (built from the correct `tenant` in the route) while `actor_full_name` (what the UI shows) resolves to a different tenant profile ("Ruth Akinyi"). The submit route already has the **correct** `tenant` object in hand but doesn't pass its identity to the audit record.

**Changes:**
1. Let `record_audit(...)` accept an explicit `actor_full_name` (and optional `actor_username`) override; when provided, skip the profile-walk guesswork.
2. In `submit_payment` (and any tenant-portal audit call that already knows the `tenant`), pass `actor_full_name=tenant_name` and `actor_username=tenant.email or tenant.phone`.
3. **Robust fix:** when resolving a tenant actor by profile, scope by `landlord_id` — pick the `Tenant` profile whose `landlord_id == landlord_id`, not the first relationship. Apply this wherever a multi-tenant user could be mis-resolved.
4. Backfill note: past mislabeled rows can't be trusted; new rows will be correct. (Do **not** rewrite immutable historical audit rows.)

**Acceptance:** Log in as a user who is a tenant under two landlords, submit a payment under landlord A → the audit log (landlord A and admin views) shows **that** tenant's name/email, matching the description string. No cross-landlord bleed.

---

## Suggested execution order

1. **#18** (audit bug — small, high-trust) and **#9** (spinners — global, low-risk) first.
2. **#1** + **#3** (table + dropdown UX — shared primitives, unblock all tables).
3. **Backbone data model: #6** (utilities + 3 categories), then **#8, #5, #7** (recording/allocation/status), then **#13, #14, #10** (statements/reports/sign).
4. **#2, #4, #11, #12** (SMS balance + reminders + templates + messaging).
5. **#15, #16, #17** (billing + admin pricing + custom package).

Verify each with the real app flow before moving on. The backbone group (#5–#8, #13, #14) is the priority — get the invariants in "The Backbone" section passing first.
