# Sahil Pay — Search, Totals, Dropdowns and SMS Margins

Stage 2 of the September 2026 work: items 7–11. Everything here is about the
difference between a seed database and a real account. A property manager on
this platform runs 100 properties, 1,000 units, 1,000 tenants and 50+ team
members, and most of what follows was invisible until there was that much data
in the system.

---

## 1. Every dropdown filters as you type

`client/src/components/ui/Select.jsx` is no longer a native `<select>`. It is a
combobox with a search box, a scrolling list, and full keyboard control.

**Why.** A native `<select>` holding a thousand `<option>`s can be scrolled and
nothing else. There is no way to find "Riverside Block C" except by dragging a
scrollbar past nine hundred other names.

**The search box is on every dropdown, not only long ones.** A threshold ("show
it once there are more than eight options") reads as tidier and is worse: the
same control then behaves differently depending on data you cannot see from the
outside, so you never learn whether typing will work — and a list that is short
today is long once the account has real data in it.

**What changed for callers: nothing.** 131 call sites pass
`onChange={(e) => set(e.target.value)}` and read a *string*, because that is
what a native select gives them. The new component emits the same shape with the
value stringified, so no form quietly starts receiving numbers where it used to
get strings.

Three details worth knowing:

* **The panel is portaled.** Every data table wraps itself in an
  `overflow-x-auto` container, and an absolutely positioned child of one of
  those is clipped no matter what its z-index says. Same reason `Dropdown.jsx`
  portals its menu.
* **A real `<select>` is kept underneath**, transparent and click-through, so
  `required` still blocks a submit exactly as before. Losing that quietly would
  turn "you must pick a property" into a silent empty submit.
* **Opening lands on the current selection**, so pressing Enter without typing
  is a no-op rather than silently changing the value to whatever is first.

Row-action menus (`Dropdown.jsx`) already scrolled; they now also grow a search
box once they carry eight or more items. Below that a search box on a
three-item action menu is pure noise, and the menu is fully visible anyway.

The two raw `<select>` elements in `AffiliatesManagement.jsx` and the
rows-per-page control in `Pagination.jsx` now use the shared component. **There
are no raw `<select>` elements left in the app** outside the component itself.

**Audit it yourself:** `cd client && node scripts/dropdown_audit.mjs` opens every
visible dropdown across 20 pages in two portals and reports any that lack a
search box or a scrolling list. Currently: 23 found, 23 with both, 0 problems.

---

## 2. Search bars on every list

| Page | Searches on |
|---|---|
| Properties | name |
| Units | unit name, pay code, **and the property it is in** |
| Tenants | name, phone |
| Expenses | category, notes, property |
| Payments | M-Pesa reference, payment ref, tenant name, phone, account number |
| Team members | name, username, email |

**Server-side, and debounced.** Filtering the twenty rows already on screen
would be worse than useless: it would look like it worked and quietly miss
everything on the other forty-nine pages. Every one of these runs in the
database.

Units search deliberately covers the *property* as well — at 1,000 units nobody
remembers which block "B12" is in, so narrowing by block name is the other half
of the same search.

Tenants and team members already had a `search` parameter on the server. Nothing
was passing it.

---

## 3. The cards now read the whole dataset

This was the "data is not accurate" complaint, and it had two independent
causes stacked on top of each other.

**Cause one — the client read the aggregates from the wrong place.** Every list
endpoint returns them nested:

```json
{ "summary": { "total_units": 1000, "total_vacancies": 57 },
  "units": [ ...20 rows... ], "total": 1000, "current_page": 1 }
```

The pages read them *flat* — `data?.total_units` — which is always `undefined`,
so every card fell through to its fallback and **counted the rows on the current
page**. On an account with 1,000 units the card read 20. Not a rounding error:
the page size, wearing the label of a total.

Fixed with `readSummary()` in `client/src/utils/tableAdapters.js`, used by
Properties, Units, Tenants and Expenses. (Payments was already correct.)

Two more found in the same place:

* `toPaginationMeta` read `response.page`; the server sends `current_page`, so
  the pager reported "page 1" whichever page you were on.
* The Tenants page asked for `leases_expiring_soon`; the server sends
  `leases_expiring`, so that card showed **0 permanently**.

**Cause two — the summary described a different set from the table.** The
aggregates were computed from a *separate, unfiltered* query. Search for one
property and the table showed one row while the card above it still read 100 —
two numbers on the same screen disagreeing about the same question, with nothing
to say which one answered what you just asked.

Every list summary now derives from the same query the rows come from. The Units
summary also gained `total_properties` (the distinct blocks the matched units
belong to), so all three cards on that page describe one set.

**A performance fix came with it.** The tenants summary was computed by loading
every tenant row into Python and looping — the entire table fetched on every
page of every list request, to produce three numbers the database can return
itself. It is now one SQL aggregate. Arrears also correctly count *owed money
only*: a tenant in credit no longer nets off a tenant in arrears.

---

## 4. A property has as many units as it has units

`properties.number_of_units` was a number somebody typed in once and nothing
ever corrected.

* Bulk import created every property with the column at its default of **0** and
  then added the units without ever coming back to it. **Importing 100
  properties and 1,000 units left every property reading "0 units"** — on
  screen, in exports, in backups. This is exactly what was reported.
* Creating a property through the API **required** the number up front, which is
  a question nobody can answer correctly at that moment and which is wrong the
  first time a unit is added.
* Deleting a unit never decremented it, so the number only ever went up.

`server/services/unit_counts.py` is now the only thing allowed to write that
column, and it recomputes from the units table. It is called on unit create,
unit delete, bulk import and tenant import. One SQL statement however many
properties, so a thousand-unit import costs a single round trip.

`number_of_units` is **no longer required** when creating a property.

**Existing data is corrected on deploy** by migration `10aaeeb9b8d4`. On the dev
database it found real drift immediately: *Riverside Apartments — stored 4,
actual 8.*

The column is kept rather than deleted because it is read by the property list,
exports, backups and the Co-pilot API contract, and computing it per row on a
screen listing a hundred properties is an N+1 query.

---

## 5. SMS margins

**This one was already built.** `landlords.sms_price_override`, the admin
endpoint, and the admin modal with its live margin readout, below-cost guard and
mandatory audit reason all existed and work. What had never been checked is that
the pieces **agree** — and that is what was added.

The rate is decided in exactly one place,
`services/sms_billing.effective_price_per_sms`, which the buy screen, the
balance decrement, the send path and the margin report all call. When they did
not, a landlord you had agreed 1.20 with was charged 1.00 at the till and the
reports showed revenue that never arrived.

`server/tests/test_sms_margin_math.py` (20 tests) walks one number all the way
through:

| Rate | KES 1,000 buys | Charge/credit | Cost/credit | Margin/credit |
|---|---|---|---|---|
| 0.50 negotiated | 2,000 credits | 0.50 | 0.40 | **0.10** |
| 0.80 negotiated | 1,250 credits | 0.80 | 0.40 | **0.40** |
| 1.00 standard | 1,000 credits | 1.00 | 0.40 | **0.60** |
| 1.20 premium | 833 credits | 1.20 | 0.40 | **0.80** |

Things the tests pin, because each is a way the books could be quietly wrong:

* Three landlords on three rates do not affect each other.
* A landlord with **no `LandlordSettings` row** keeps their negotiated rate —
  falling back to the standard one there is a discount nobody agreed to,
  applied invisibly.
* The quote on the buy screen equals the amount actually charged.
* Delivery cost does **not** vary with the sender ID. Every registered sender ID
  sits on Sahil Pay's own FluxSMS account, so a branded sender costs the same to
  deliver. Recording zero there is what used to hide a real loss.
* A below-cost rate produces a genuine **negative** margin in the report rather
  than being clamped at zero — a loss-leader is a legitimate choice and has to
  be visible.
* A rate change without a reason is refused, and the reason lands in the audit
  log. These are verbally agreed commercial terms; the reason is the record.

**Setting a rate:** Admin → SMS Management → the landlord's row → set the rate
per credit. The margin updates live as you type. Leave it empty to put them back
on the standard rate.

---

## Verifying

```bash
# Backend
cd server && source venv/bin/activate && python -m pytest tests/ -q

# The Stage 2 features, in a real browser
cd client
node scripts/stage2_walkthrough.mjs   # 17 checks
node scripts/dropdown_audit.mjs       # every dropdown, every portal
```
