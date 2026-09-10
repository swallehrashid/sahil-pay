# SahilPay — Full Diagnostic Scenario Catalogue

> Built before running the 5-month simulation. Every scenario below is exercised
> against the real backend engine (allocation, rollover, credit, billing) and/or
> the real HTTP API, one at a time. Fixes are applied and re-tested until green.
> Portals: **Landlord/PM**, **Team Member**, **Tenant**, **Admin**, **Affiliate**.

Legend: `[MONEY]` core ledger correctness · `[AUTH]` access control ·
`[FLOW]` multi-step workflow · `[EDGE]` boundary/error handling · `[TIME]` depends on month advancing.

---

## A. Landlord / Property Manager portal

### A1. Onboarding & structure
- A1.1 Register a brand-new landlord → default charge categories seeded (Rent, Lease, Penalty, Water, Electricity, Security). `[FLOW]`
- A1.2 Create property group → property → units with distinct rents. `[FLOW]`
- A1.3 Create a custom charge category (utility, non-metered, auto-bill) and (invoice-kind). `[FLOW]`
- A1.4 Metered + auto-bill mutual exclusion rejected (400). `[EDGE]`
- A1.5 Delete a default category blocked (409); delete an unused custom category allowed. `[EDGE]`

### A2. Tenants & leases
- A2.1 Add tenant to a unit with rent + deposit; unit marked occupied. `[FLOW]`
- A2.2 Move tenant out → unit vacant, TenantUnitHistory recorded. `[FLOW]`
- A2.3 Transfer tenant between units. `[EDGE]`
- A2.4 Add tenant to already-occupied unit rejected. `[EDGE]`

### A3. Billing over 5 months `[TIME][MONEY]`
- A3.1 Month-1 auto-bill: each active auto_bill category produces a `current` line at unit rent / default rate.
- A3.2 Fully-paid tenant: balance 0 every month, no rollover.
- A3.3 Partial-payer: unpaid current + balance roll into ONE "{Cat} Balance b/f" line next month; deposits never roll.
- A3.4 Multi-month arrears: b/f line accumulates across 2+ origin months, BalanceRollover provenance correct, consumed oldest-first.
- A3.5 Overpayer: remainder → credit_balance + CreditLedger, auto-applied on next month's billing.
- A3.6 Idempotency: running monthly billing twice for the same month does not double-bill.
- A3.7 Deposit line stays open, never rolls, never counted as income.

### A4. Payments
- A4.1 Record full payment (auto-allocation, oldest-first within priority buckets). `[MONEY]`
- A4.2 Record partial payment (line-level manual allocation). `[MONEY]`
- A4.3 Overpayment → credit. `[MONEY]`
- A4.4 Confirm a pending payment updates line status + tenant balance. `[FLOW]`
- A4.5 M-Pesa C2B payment matched to tenant by account ref → allocated. `[MONEY]`
- A4.6 Unmatched M-Pesa payment surfaced for manual matching. `[EDGE]`
- A4.7 Reversal / negative edge: paying an already-paid invoice → all to credit. `[EDGE]`

### A5. Invoices
- A5.1 Create manual invoice with category+subcategory line items. `[FLOW]`
- A5.2 Invoice status transitions (unpaid→partial→paid) reflect allocations. `[MONEY]`
- A5.3 b/f lines excluded from "invoiced this month" and from statement charges. `[MONEY]`

### A6. Utilities / metered readings
- A6.1 Record a metered water/electricity reading → produces a current line at consumption × rate. `[MONEY]`
- A6.2 Reading added to open invoice vs new invoice. `[FLOW]`

### A7. Expenses & maintenance
- A7.1 Record expense against a property; recurring expense generates monthly. `[FLOW]`
- A7.2 Maintenance request lifecycle (open→in-progress→resolved). `[FLOW]`

### A8. Reports (all 8) `[MONEY]`
- A8.1 Tenant statement reconciles to −tenant.balance (b/f not double-counted, credit re-app excluded).
- A8.2 Property statement, rent roll, income vs expense, payments report, arrears, occupancy, comparative MoM/YoY.
- A8.3 PDF + Excel export for each render without error (WeasyPrint deps).

### A9. Communications & notifications
- A9.1 Send templated SMS/email to a tenant (simulation mode — logged, not sent). `[FLOW]`
- A9.2 Bulk send to all tenants of a property. `[FLOW]`
- A9.3 Low-SMS-balance / trial-expiring platform notifications appear. `[FLOW]`

### A10. Billing/subscription (landlord's own SahilPay bill)
- A10.1 Trial state, plan upgrade, subscription status transitions. `[FLOW]`
- A10.2 Custom package assigned by admin reflected in landlord billing. `[MONEY]`

### A11. Settings
- A11.1 Allocation priority reorder persists and changes auto-allocation order. `[MONEY]`
- A11.2 SMS provider settings, copilot settings, general settings save. `[FLOW]`

---

## B. Team Member portal `[AUTH]`
- B1. Editor can perform permitted CRUD (create tenant, record payment). Actions audit-logged under landlord.
- B2. Viewer is read-only: mutating endpoints rejected (403).
- B3. Property-scoped team member sees only assigned properties; cross-property access rejected.
- B4. Team member view is logged to landlord audit trail.
- B5. Editing a permission the member doesn't have → 403 (the known "edit-button gap" from memory — verify).

---

## C. Tenant portal `[AUTH][FLOW]`
- C1. OTP login via SMS/email (request → verify → token).
- C2. Wrong/expired OTP rejected; rate-limited.
- C3. Tenant sees own invoices, balance, payment history — and ONLY their own.
- C4. Tenant statement download (PDF) with correct key/reconciliation.
- C5. Tenant initiates M-Pesa STK payment → callback records + allocates.
- C6. Tenant messages landlord; landlord replies (comms gap from memory — verify).
- C7. Cross-tenant data isolation: tenant A cannot fetch tenant B's data.

---

## D. Admin portal `[AUTH]`
- D1. Admin dashboard aggregates (landlord count, revenue, SMS pool) load.
- D2. Landlord drill-down: view a landlord's properties/tenants/payments read-only.
- D3. **Client Support (renamed from Impersonation):** request access → landlord grants → admin operates account → every action audit-logged with "[Client support session…]" prefix → revoke/exit.
- D4. Client support denied by landlord → no access.
- D5. Client support request expiry respected.
- D6. Pricing/packages: create/edit public package, assign custom package to a landlord.
- D7. SMS reselling: pricing config, pool top-up, per-landlord usage & analytics.
- D8. Trials: extend/configure trial, trial scope.
- D9. Platform C2B payments (subscriptions/SMS credits) recorded & reconciled.
- D10. Master audit logs: filter by landlord/actor/entity/date and "Client support actions only".
- D11. Copilot device/release management.
- D12. Suspend/reactivate a landlord.

---

## E. Affiliate portal `[MONEY][AUTH]`
- E1. Affiliate signup → pending admin approval → approved/active with referral code.
- E2. Referral attribution: a landlord who signs up via code is linked.
- E3. Commission accrual: 40%/configurable for N months on VERIFIED (paid) referrals only.
- E4. Trial/never-paid referral shows projected (not accrued) earnings.
- E5. Withdrawal request → admin process → paid, with WHT + fee math and KRA receipt.
- E6. Withdrawal reject path.
- E7. Affiliate cannot see another affiliate's referrals/commissions.

---

## F. Cross-cutting / platform `[EDGE]`
- F1. Auth: expired/invalid JWT, refresh flow, must-change-password gate.
- F2. Rate limiting active (memory:// in dev).
- F3. Demo mode: shadow demo landlord isolated; writes marked demo-scope; reset reseeds clean.
- F4. Soft-delete: deleted entities excluded from queries but audit-preserved.
- F5. Pagination on large lists.
- F6. Multi-tenant isolation: landlord A never sees landlord B's data (the master isolation invariant).
- F7. Money invariants hold after 5 months: outstanding-line-remaining == −tenant.balance; credit_balance == credit_ledger sum; no deposit ever rolled; payments-report total == balance+current.

---

## G. Time-advance mechanics `[TIME]`
- G1. Advance clock month-by-month for 5 cycles, running monthly billing each cycle.
- G2. Recurring bills/expenses fire once per month.
- G3. Trial expiry / subscription renewal boundaries crossed.
- G4. Affiliate commission window (N months) opens and closes correctly across the 5 months.
