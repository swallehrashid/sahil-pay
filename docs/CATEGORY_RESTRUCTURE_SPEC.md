# SAHIL PAY — Charge Category Restructure & Allocation Engine Spec

**Branch:** `backend-set-up` · **Date:** 2026-07-07 · **Status:** APPROVED — ready for implementation

This is the backbone rework of Sahil Pay's billing engine. It unifies utilities and
invoice charges into one **Charge Category** concept, moves payment allocation down to
the **invoice line item** level, introduces the **month-end balance rollover**, a
**tenant credit (advance) balance**, a rebuilt **allocation-priority setting**, and a
new **Payments Report**. Every design decision below was confirmed with the owner on
2026-07-07.

---

## 0. The core concept (read this first)

Every chargeable thing is a **ChargeCategory** belonging to a landlord. A category is
either `utility` kind (managed on the Utilities page) or `invoice` kind (managed on the
Invoices page). **Every category implicitly owns exactly three subcategories** — they
are NOT separate rows, they are a fixed enum stamped on invoice line items:

| Subcategory | Meaning | Display name (derived) |
|---|---|---|
| `deposit` | Money held (refundable). **Never rolls over.** Excluded from income totals. | "{Name} Deposit" |
| `balance` | Arrears carried forward from prior months. Grows at each rollover. | "{Name} Balance" |
| `current` | This month's charge. | "{Name}" |

So creating a utility "Water" gives the system Water Deposit / Water Balance / Water.
Creating invoice category "Rent" gives Rent Deposit / Rent Balance / Rent. Money is
invoiced, allocated, rolled over, and reported **per (category, subcategory)** pair.

**Defaults (seeded per landlord, protected — deactivatable, never deletable):**
- Invoice kind: **Rent** (auto-bill ON), **Lease Agreement** (one-off, auto-bill OFF).
  *(The earlier idea of a standalone "Deposit" default was dropped — every category
  already has its own deposit subcategory.)*
- Utility kind: **Water** (metered), **Electricity** (metered), **Security**
  (non-metered).
- **Penalty** is seeded as a protected invoice-kind category so the existing penalty
  generator flows through the same engine (replaces the old `other` bucket).

Landlords can add any number of additional categories of either kind.

---

## 1. Data model changes (`server/models.py` + one Alembic migration)

### 1.1 New: `ChargeCategory` (replaces `LandlordUtilityType`)

```python
class ChargeCategoryKind(str, enum.Enum):
    utility = "utility"
    invoice = "invoice"

class SubCategory(str, enum.Enum):
    deposit = "deposit"
    balance = "balance"
    current = "current"

class ChargeCategory(TimestampMixin, Base):
    __tablename__ = "charge_categories"
    id                = Column(Integer, primary_key=True)
    landlord_id       = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    name              = Column(String(80), nullable=False)          # "Water", "Rent"
    kind              = Column(String(10), nullable=False)          # ChargeCategoryKind
    description       = Column(Text, nullable=True)
    is_metered        = Column(Boolean, default=False, nullable=False)   # utility kind only
    default_rate      = Column(Numeric(12, 2), nullable=True)
    auto_bill_monthly = Column(Boolean, default=False, nullable=False)
    is_default        = Column(Boolean, default=False, nullable=False)   # protected row
    is_active         = Column(Boolean, default=True, nullable=False)
    __table_args__ = (
        UniqueConstraint("landlord_id", "name", name="uq_charge_categories_landlord_name"),
        CheckConstraint("NOT (is_metered AND auto_bill_monthly)",
                        name="ck_charge_categories_metered_not_autobill"),
    )
```

Rules enforced in routes/service:
- `auto_bill_monthly` may only be enabled when `is_metered` is false (metered amounts
  are unpredictable — DB CheckConstraint above backs this up).
- `is_default=True` rows reject DELETE (409) — only `is_active` may be toggled.
- Utilities page manages `kind=utility`; Invoices page manages `kind=invoice`. Same
  API, filtered by kind.
- Migrate `LandlordUtilityType` → drop table (data re-seeded, per §8); remove model,
  `Landlord.utility_types` relationship, and the old `UtilityCategory` enum.

### 1.2 `InvoiceLineItem` — becomes the allocation target

Add:
```python
category_id  = Column(Integer, ForeignKey("charge_categories.id"), nullable=False, index=True)
subcategory  = Column(String(10), nullable=False, index=True)     # SubCategory enum
amount_paid  = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
status       = Column(String(10), default="open", nullable=False) # open | paid | rolled
```
- `balance` of a line = `amount - amount_paid` (property, not a column).
- `status="rolled"` marks a line closed by rollover — excluded from "outstanding"
  everywhere (allocation, arrears, statements' open-amounts).
- Invoice header `status/amount_paid/balance` become derived from its lines (keep the
  columns, recompute in `apply_allocations` and rollover).
- Every line-item creation path (rent/custom/recurring/penalty/utility invoice
  generators, `InvoiceForm`) must now stamp `category_id` + `subcategory`.

### 1.3 `PaymentAllocation` — line-level

Add `line_item_id = Column(Integer, ForeignKey("invoice_line_items.id"), nullable=False, index=True)`.
Keep `invoice_id` (denormalised convenience). Replace unique constraint with
`UniqueConstraint("payment_id", "line_item_id")`. All reports/statements that join
allocations now resolve category/subcategory via the line item.

### 1.4 New: `BalanceRollover` — the audit trail ("where did this balance come from?")

```python
class BalanceRollover(TimestampMixin, Base):
    __tablename__ = "balance_rollovers"
    id                  = Column(Integer, primary_key=True)
    landlord_id         = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    tenant_id           = Column(Integer, ForeignKey("tenants.id"),   nullable=False, index=True)
    category_id         = Column(Integer, ForeignKey("charge_categories.id"), nullable=False, index=True)
    source_line_item_id = Column(Integer, ForeignKey("invoice_line_items.id"), nullable=False)
    target_line_item_id = Column(Integer, ForeignKey("invoice_line_items.id"), nullable=False, index=True)
    origin_month        = Column(Date, nullable=False)   # month the debt ORIGINALLY arose
    amount              = Column(Numeric(12, 2), nullable=False)
    __table_args__ = (
        UniqueConstraint("source_line_item_id", name="uq_balance_rollovers_source"),  # idempotency
    )
```

**Component semantics:** a balance line item's rollover rows are its *components*, each
tagged with the month the debt originally arose. When a balance line that already has
components rolls again, each unpaid component is carried into the new target line as a
new row **preserving its original `origin_month`** (provenance survives multiple
rolls). Payments against a balance line consume components **oldest-first** (display
convention for the audit view). Expanding "Rent Balance 15,000" in the UI shows
"5,000 from May 2026 + 10,000 from June 2026".

### 1.5 Tenant credit (advance)

- `Tenant.credit_balance = Column(Numeric(12, 2), default=0, nullable=False)`
- New `CreditLedger` table: `tenant_id, landlord_id, amount` (signed: + top-up from
  overpayment, − application to a line item), `payment_id` (nullable),
  `line_item_id` (nullable), `memo`, timestamps. `credit_balance` always equals the
  ledger sum — recompute on write, assert in tests.

### 1.6 `Landlord.allocation_priority` — new format

New column `allocation_priority_json` (Text, JSON array), old CSV column dropped.
Each entry is `"<category_id>:<subcategory>"`, e.g. `"3:balance"`. The list is the
complete, ordered allocation priority across **all** (category, subcategory) pairs.

- `get_allocation_priority(landlord)` backfills pairs missing from the stored list
  (new categories created after saving) using the **Kenya default grouping**:
  **all `balance` pairs → all `deposit` pairs → all `current` pairs**, within a group
  by category creation order. Inactive categories' pairs are skipped for auto-
  allocation but their existing invoices remain payable.
- Within one (category, subcategory) bucket, line items are consumed **oldest
  `issue_date` first** ("oldest debt first").

### 1.7 `UtilityReading`

`utility_type_id` FK repointed to `charge_categories.id` (rename to `category_id`).
Reading→invoice conversion (`generate_utility_invoices_task`) stamps the line item
with that category + `subcategory=current`.

---

## 2. The allocation engine (`server/services/allocation_service.py` — rewrite)

### 2.1 Outstanding items
`outstanding_line_items(tenant)` = line items on non-deleted, non-void invoices with
`status="open"` and `amount_paid < amount`. (Rolled lines excluded by status.)

### 2.2 Auto-allocate
```
auto_allocate(tenant, amount, landlord, ref_date) -> list[{line_item_id, amount}]
```
1. Bucket outstanding lines by `(category_id, subcategory)`.
2. Walk the landlord's priority list (§1.6); within a bucket, oldest issue_date first.
3. Fill each line up to its remaining balance until `amount` is exhausted.
4. **Remainder → tenant credit** (CreditLedger + `credit_balance`), never dumped onto
   the last invoice (removes the old "pay-full dumps remainder" behaviour).

### 2.3 Manual allocate
The landlord passes explicit `[{line_item_id, amount}]` rows. Validation: each amount
> 0 and ≤ the line's remaining balance; sum ≤ payment amount; any un-allocated
remainder → tenant credit (UI confirms this explicitly).

### 2.4 apply_allocations
Persists `PaymentAllocation` rows (payment → line item), bumps `line.amount_paid`,
flips `line.status` to `paid` when cleared, consumes balance-line components
oldest-first (recorded for the audit view), recomputes invoice header
`amount_paid/balance/status`, updates `tenant.balance`. Flush-only; caller commits.

### 2.5 Credit application
`apply_tenant_credit(tenant, landlord, ref_date)` — runs the auto-allocate cascade
using `credit_balance` as the amount, writing CreditLedger `−` rows instead of
PaymentAllocations tied to a real payment (use a synthetic "credit application"
payment source so statements show it). Called automatically:
1. at the end of monthly billing (§3) for each tenant with credit, and
2. whenever a new invoice is created for a tenant holding credit
so an overpayment always shrinks the very next bill. Landlord can also trigger it
manually from the tenant page.

### 2.6 Payment void/decline
Reversing a payment deletes its allocations, restores each line's `amount_paid`/
`status`, reverses any credit top-up from that payment, recomputes invoice headers and
`tenant.balance`.

---

## 3. Monthly billing & rollover (`server/tasks/invoice_tasks.py`)

Runs from the existing Celery beat `generate-monthly-invoices` (1st, 00:05 Nairobi)
and from the manual "generate invoices" actions. Per landlord, per active tenant,
in ONE transaction per tenant, strictly in this order:

**Step 1 — Rollover (all categories, both kinds):**
For each open line item with `subcategory in (current, balance)` and unpaid remainder
on invoices issued **before** the run month:
- group unpaid remainders by category;
- mark each source line `status="rolled"` (its remainder no longer counts as
  outstanding; invoice header recomputed);
- the grouped amounts become "{Category} Balance b/f" lines on the new monthly
  invoice (Step 2), `subcategory=balance`;
- write `BalanceRollover` rows per source line: unpaid components of a rolling
  balance line carry their original `origin_month`; a rolling *current* line gets
  `origin_month` = its invoice's issue month.
- **Deposit lines NEVER roll** — they stay open on their original invoice until paid.

**Step 2 — Monthly invoice (one per tenant):**
A single invoice titled "Monthly invoice — {Month Year}" containing:
- one balance-b/f line per category rolled in Step 1;
- one `current` line per active category with `auto_bill_monthly=True`:
  Rent uses the unit's rent amount; others use `default_rate` (skip if none set).
Metered utilities are NOT billed here — they bill when a reading is recorded, exactly
as today (reading → utility invoice, line stamped category + `current`).
If a tenant has nothing to roll and no auto-bill categories, no invoice is created.

**Step 3 — Credit application:** `apply_tenant_credit` for tenants with
`credit_balance > 0`.

**Idempotency:** the unique constraint on `BalanceRollover.source_line_item_id` plus a
per-landlord-month guard (skip tenants who already have this month's monthly invoice)
make re-runs safe. The user's canonical example must hold: Rent Balance 5,000 + unpaid
current Rent 10,000 → next month shows Rent Balance b/f **15,000** + Rent 10,000, with
the audit view showing 5,000 (origin month M-2) + 10,000 (origin month M-1).

---

## 4. API changes (`server/routes/`)

### 4.1 Categories — `utility_routes.py` + `invoice_routes.py` (shared service)
- `GET/POST /charge-categories?kind=utility|invoice` — list/create (create validates
  metered⊥auto_bill, unique name).
- `PATCH /charge-categories/<id>` — edit rate/description/toggles; `DELETE` — 409 if
  `is_default` or if any line items reference it (deactivate instead).
- Category payloads include the three derived subcategory display names so the client
  never re-derives labels.

### 4.2 Allocation settings — `settings_routes.py`
- `GET /settings/allocation-priority` → ordered list of
  `{key, category_id, category_name, kind, subcategory, label}` (backfilled per §1.6).
- `PUT /settings/allocation-priority` → accepts ordered key array, validates it covers
  exactly the landlord's pairs.

### 4.3 Payments — `payment_routes.py`
- `GET /tenants/<id>/outstanding-items` → all outstanding line items grouped by
  invoice: `{invoice_number, issue_date, lines: [{id, label ("Water Balance"),
  category, subcategory, amount, amount_paid, remaining}]}` + `credit_balance`.
- `POST /payments` (record/confirm): `allocation_mode: "auto" | "manual"`; manual
  passes `allocations: [{line_item_id, amount}]`. Response includes resulting
  allocations and any credit created.

### 4.4 Reports — `report_routes.py`
- `GET /reports/payments?category_id=<id|all>&date_from&date_to&property_id?` →
  per-tenant rows (§6) + footer totals. Export (PDF/Excel) via the existing
  `report_builder` pipeline like the other eight reports.
- `GET /line-items/<id>/rollover-trail` → the audit breakdown
  `[{origin_month, amount, remaining}]` for any balance line (used by the expandable
  audit view in statements/invoice detail).

### 4.5 Existing reports/statements
Tenant statement, property statement, arrears report: exclude `rolled` lines from
outstanding, show balance-b/f lines as ledger entries (they replace what they rolled,
so running balances stay continuous — verify no double count in tests).

---

## 5. Frontend changes (`client/src/features/landlord/`)

### 5.1 Utilities page (`utilities/UtilityTypesManager.jsx`, `RecordUtilityForm.jsx`)
- Manager CRUD against `kind=utility` categories: name, description, metered checkbox,
  default rate, **auto-bill toggle (hidden/disabled when metered)**, active toggle.
  Each category card lists its three auto-created subcategories (read-only chips:
  "Water Deposit · Water Balance · Water"). Defaults show a "Default" badge, no delete.
- Record-utility flow unchanged in spirit: pick the utility **category**, record
  reading/flat amount, then convert to invoice as today (line stamped
  category+`current`).

### 5.2 Invoices page (`invoices/`)
- New "Invoice Categories" manager (same component, `kind=invoice`): Rent & Lease
  Agreement protected defaults, plus custom ones. No metered checkbox for invoice kind.
- `InvoiceForm.jsx`: every line item requires picking a **target = category +
  subcategory** from a grouped dropdown ("Rent — Deposit", "Rent — Balance",
  "Rent — This month", "Water — Deposit", …). Generators (rent/custom/recurring/
  penalty) stamp their category automatically.

### 5.3 Settings → allocation priority (`settings/AllocationPriorityEditor.jsx` — rebuild)
Drag-to-reorder list of **all subcategory pairs** (not six fixed buckets), grouped
visually by category color/kind. "Reset to default" restores the Kenya order:
balances → deposits → currents. Newly created categories appear automatically in
their default group position until re-saved.

### 5.4 Record payment (`payments/RecordPaymentForm.jsx`, `ConfirmPaymentModal.jsx`)
- Mode switch: **Auto (use my settings)** | **Manual**.
- Manual: ONE screen listing all outstanding items across all invoices (grouped by
  invoice header), amount input per line (capped at remaining), live running
  remainder, and a footer note: "Unallocated remainder KES X will be saved as tenant
  credit". Auto mode shows a preview of the cascade before saving.
- Show tenant's current credit balance at the top of the form.

### 5.5 Reports → Payments Report (new `reports/PaymentsReport.jsx` + route/nav)
- Controls: **category dropdown (All categories + every active category)** +
  **date range** + optional property filter.
- Per-tenant columns for a selected category:
  1. **Deposit invoiced** (in range) · 2. **Deposit paid** (in range) ·
  3. **Deposit balance** (outstanding to date) — the three deposit columns
  4. **Deposit held to date** (lifetime collected — the money you're holding)
  5. **Balance collected** (allocations to the balance subcategory in range)
  6. **Current collected** (allocations to current in range)
  7. **Total collected = balance + current** (deposits excluded, per spec)
- Footer: totals per column, incl. "Total {category} deposit collected" and grand
  "Total money allocated to {category}".
- "All categories": one section per category with the same columns + a grand-total
  band ("Total collected across everything, June 2026").
- Balance cells expandable → rollover trail (origin months + amounts) via §4.4.

---

## 6. Seed data (`server/seed.py` — extend)

Fresh, comprehensive seed replacing old utility-catalogue seeding (owner chose new
seed data over migrating legacy rows). Must cover, for the demo landlord:
- All protected defaults + one custom utility ("Garbage", non-metered, auto-bill,
  rate 300) + one custom invoice category ("Parking").
- ≥4 tenants staged across **3 seeded months** exercising every path:
  tenant A fully paid; tenant B partial rent → rolled balance with 2-origin-month
  components; tenant C overpaid → credit consumed on the next monthly invoice;
  tenant D unpaid water deposit (open deposit, never rolled) + metered readings.
- Payments in both auto and manual allocation modes; at least one credit application;
  BalanceRollover rows consistent with the invoices.
- Update "seed data credentials" file if logins change.

---

## 7. Migration plan

One Alembic migration on head `a3b4c5d6e7f8`:
1. create `charge_categories`, `balance_rollovers`, `credit_ledger`;
2. add line-item columns (`category_id`, `subcategory`, `amount_paid`, `status`);
   add `payment_allocations.line_item_id` + new unique constraint;
   add `tenants.credit_balance`; add `landlords.allocation_priority_json`,
   drop `landlords.allocation_priority`;
3. drop `landlord_utility_types` and repoint `utility_readings.utility_type_id` →
   `charge_categories.id` (rename `category_id`).
Because data is re-seeded, no data backfill is written — dev DBs are rebuilt
(`seed.py`). Keep the migration reversible where cheap.

## 8. Implementation order

1. Models + migration + seeded defaults (categories seeded on landlord creation too —
   registration hook).
2. Rewrite `allocation_service.py` (line-level, credit, priority format) + unit-style
   smoke script.
3. Rollover + monthly invoice task (`invoice_tasks.py`) + idempotency guard.
4. Routes (§4) — categories, settings, outstanding-items, payments, reports, trail.
5. Seed data (§6) — needed before UI work for realistic testing.
6. Frontend (§5) — utilities, invoices, settings, record payment, payments report.
7. Update existing statements/arrears reports for `rolled` lines.
8. **Verification (§9)** end-to-end, then commit.

## 9. Acceptance simulation (must pass before done)

Scripted against seed data (5 simulated months, driving the real task + services):
1. Month 1: invoice deposits + rent + lease + metered readings; auto-pay covering
   deposits first per default priority; verify report columns.
2. Month 2 rollover: unpaid currents become balance-b/f on the single monthly
   invoice; sources closed (`rolled`); tenant's total owed unchanged across the
   roll (no double count); deposits did NOT roll.
3. The canonical example: balance 5,000 + unpaid rent 10,000 → Rent Balance b/f
   15,000 with audit trail showing both origin months.
4. Overpayment → credit; next month's invoice auto-consumed by credit.
5. Manual allocation across items of several invoices in one payment.
6. Re-run the monthly task same month → no duplicates (idempotent).
7. Payments Report per category and All categories over a date range: totals equal
   the sum of PaymentAllocations; deposits excluded from income totals; balance-cell
   drill-down shows correct origin months.
8. Tenant statement + arrears report remain continuous (no jump at rollover).
