# SahilPay — Landlord Portal QA Walkthrough Report

**Date:** 2026-06-27
**Tester:** Automated browser-driven walkthrough (Playwright + chromium), every page exercised as a real landlord, with each write cross-checked against the REST API / database.
**Method:** Registered a brand-new landlord through the UI, logged in through the UI, then clicked through every landlord page and filled every core form. After each create/edit, the row was re-read from the API to confirm it actually persisted and was accurate.

---

## 0. TL;DR

When the walkthrough started, **the landlord portal was completely unusable**: you could not stay logged in, and even when forced past login, every list was empty and every "Save" button failed. I traced this to **4 systemic, app-wide bugs** plus **3 feature-specific bugs**. All 7 were root-caused and **fixed in this branch**, and the full flow now works end-to-end with accurate data.

| # | Severity | Area | Symptom | Status |
|---|----------|------|---------|--------|
| 1 | 🔴 Blocker | Auth (all portals) | Every login bounces straight back to `/login` | ✅ Fixed |
| 2 | 🔴 Blocker | API/CORS (all list+create) | Browser requests blocked by CORS preflight redirect | ✅ Fixed |
| 3 | 🔴 Blocker | All create/edit forms | Blank optional number field → HTTP 500 | ✅ Fixed |
| 4 | 🔴 Blocker | All list pages + dropdowns | Tables/dropdowns always empty despite data existing | ✅ Fixed |
| 5 | 🟠 Major | Invoices | Manual invoice create always 400 | ✅ Fixed |
| 6 | 🟠 Major | Communications | "Send message" always 400 | ✅ Fixed |
| 7 | 🟠 Major | Dashboard | Occupancy + Paid-vs-invoiced cards show 0 | ✅ Fixed |
| 8 | 🟡 Minor | Several | React warnings, a11y, notifications gap | Documented (not yet fixed) |

**Files changed (this branch):**
```
client/src/context/AuthContext.jsx                          (bug 1)
server/app.py                                               (bug 2)
client/src/store/apiSlice.js                                (bug 3)
client/src/utils/tableAdapters.js                           (bug 4)
server/routes/invoice_routes.py                             (bug 5)
client/src/features/landlord/communications/CommunicationsPage.jsx  (bug 6)
client/src/features/landlord/LandlordDashboard.jsx          (bug 7)
```
> `client/src/features/auth/Login.jsx` and `server/config.py` were already modified before this session (login error-message copy + a dev-only CORS origin regex). They are unrelated to the bugs below.

---

## 1. Environment / how to reproduce the walkthrough

- Frontend (Vite): `http://localhost:5173`
- Backend (Flask): `http://localhost:5000/api`
- DB: Postgres on `127.0.0.1:5432`
- Auth token is stored in `localStorage` under `sahilpay_access_token` / `sahilpay_refresh_token`.
- A fresh landlord can be **registered** at `/register` (company name, email, phone, password). Note: the backend creates the account with `is_verified=false` but **login does not enforce verification**, so the new account can log in immediately (see §8.5).

**Test data created during this run** (landlord `QA Walkthrough Estates`, login `qa.landlord.<ts>@sahilpay.test` / `QaLandlord@123`):
- 1 property: *QA Sunrise Apartments* (Nairobi, 4 units, water 150, electricity 23)
- 4 units: A1 (25,000), A2 (25,000), B1 (32,000), B2 (18,000 — left vacant on purpose)
- 3 tenants: John Kamau→A1, Mary Wanjiku→A2, Peter Otieno→B1
- 3 utility readings: water A1 (50), water A2 (50), electricity B1 (60)
- 3 invoices: John 25,000 / Mary 25,000 / Peter 32,000  → **82,000 billed**
- 3 payments: John 25,000 / Mary 10,000 / Peter 32,000  → **67,000 collected**
- 1 expense (garbage, 5,000), 1 maintenance request, 1 property group, 1 team member
- Resulting balances: John **0**, Mary **−15,000 (arrears)**, Peter **0** ✔ ledger correct

---

## 2. 🔴 BUG 1 — Every login bounces back to `/login` (auth hydration race)

### Symptom
After a correct email+password login, the URL went `/login → /landlord/dashboard → /login` within ~250 ms, every time, for **every** account (verified seed landlord included). The portal was impossible to enter. A page refresh or deep-link to any `/landlord/*` route did the same.

### Root cause
`ProtectedRoutes` decides between three states using `isAuthenticated` and `isHydrating` from `AuthContext`. The hydration flag was:

```js
const isHydrating = hasToken && isLoading && !user;   // ❌
```

RTK Query sets `data` **and** flips `isLoading` to `false` in the *same* render, but the `user` is only written to the store by a `useEffect` on the *next* render. That leaves a one-render window where:
`hasToken === true`, `isLoading === false` (so `isHydrating === false`), and `user === null` (so `isAuthenticated === false`).
In that window `ProtectedRoutes` runs its `if (!isAuthenticated) <Navigate to="/login">` branch and redirects before the user is ever committed.

### Fix — `client/src/context/AuthContext.jsx`
Gate hydration on the user actually being present, not on `isLoading`:
```js
const isHydrating = hasToken && !user && !isError;   // ✅
```
Now the guard keeps showing the loader until `setCredentials` has committed the user (or `/auth/me` errors, in which case the token is cleared and the user is correctly sent to login).

### Verify
- Log in via the UI → you land on and **stay** on `/landlord/dashboard`.
- Hard-refresh any `/landlord/*` page → it re-hydrates and stays.

---

## 3. 🔴 BUG 2 — CORS preflight redirect blocks every authenticated list/create

### Symptom
On Properties/Units/Tenants/Invoices/… the browser console showed:
```
Access to fetch at 'http://localhost:5000/api/properties' ... blocked by CORS policy:
Response to preflight request doesn't pass access control check:
Redirect is not allowed for a preflight request.
```
Lists never loaded; `net::ERR_FAILED`. (Simple endpoints like `/auth/me` worked, which is why login *appeared* fine once Bug 1 was fixed.)

### Root cause
Collection routes are registered as `@bp.route("/")` → real path `/api/properties/` (with trailing slash), but the frontend calls `/api/properties` (no slash). With Flask/Werkzeug default `strict_slashes=True`, the server answers the **OPTIONS preflight** with a `308 PERMANENT REDIRECT` to the slashed URL. Browsers refuse to follow a redirect on a preflight, so the request dies before the real call is made. Every authenticated request is preflighted (because of the `Authorization` header), so **every** list/create endpoint was affected.

### Fix — `server/app.py` (before `register_blueprints`)
```python
app.url_map.strict_slashes = False
```
Now `/api/properties` and `/api/properties/` match the same rule with **no redirect**, and the OPTIONS preflight returns `200` with the proper CORS headers.

### Verify
```bash
curl -i -X OPTIONS http://localhost:5000/api/properties \
  -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: GET"
# → HTTP/1.1 200 OK  (was 308 PERMANENT REDIRECT)
```

---

## 4. 🔴 BUG 3 — Blank optional numeric field → HTTP 500 on create/edit

### Symptom
Creating a property (or any entity) through the normal form failed. In the browser it looked like a CORS error (`No 'Access-Control-Allow-Origin' header`), but that was a red herring: the real response was a **500** whose Werkzeug error page carries no CORS header.

### Root cause
Forms send *every* field, and blank optional fields are sent as empty strings `""`. The backend inserts those straight into Postgres `NUMERIC` columns:
```
sqlalchemy.exc.DataError: (psycopg2.errors.InvalidTextRepresentation)
invalid input syntax for type numeric: ""
```
e.g. `rent_payment_penalty`, `management_fee`, `water_rate`, `electricity_rate` left blank. Any create/edit form with an optional number is affected.

### Fix applied — `client/src/store/apiSlice.js`
Normalise `"" → null` at the single mutation chokepoint (FormData/file uploads passed through untouched):
```js
function sanitizeBody(args) {
  const { body } = args;
  if (!body || typeof body !== "object" || body instanceof FormData) return args;
  const cleaned = {};
  for (const [k, v] of Object.entries(body)) cleaned[k] = v === "" ? null : v;
  return { ...args, body: cleaned };
}
// applied inside baseQueryWithReauth before the request goes out
```

### Recommended additional hardening (backend — not yet applied)
A malformed client should never be able to 500 the API. Coerce/validate numeric inputs at the route/schema boundary, e.g. a helper that turns `""`/missing into `None` before constructing the model, or Marshmallow/Pydantic fields with `allow_none`. The property route (`server/routes/property_routes.py::create_property`) passes `data.get("water_rate")` etc. straight into the model — those are the spots to guard.

### Verify
Create a property filling only Name / Number of units / City → **201**, persists, and appears in the list.

---

## 5. 🔴 BUG 4 — List tables & dropdowns always empty (`toRows` key mismatch)

### Symptom
Even with data in the DB, **every** list page rendered an empty table, and **every** "select a property/unit/tenant" dropdown was empty — which also made it impossible to create dependent records (no property to pick when adding a unit, etc.).

### Root cause
List endpoints key their array by entity name, e.g.:
```json
{ "properties": [ … ], "total": 1, "pages": 1, "current_page": 1 }
```
But `toRows()` only knew about `items` / `results` / `data`:
```js
return response.items ?? response.results ?? response.data ?? [];   // ❌ → []
```

### Fix — `client/src/utils/tableAdapters.js`
Fall back to the first array-valued property, which covers `properties`, `units`, `tenants`, `invoices`, `payments`, `groups`, … in one shot:
```js
if (Array.isArray(response.items)) return response.items;
if (Array.isArray(response.results)) return response.results;
if (Array.isArray(response.data)) return response.data;
return Object.values(response).find(Array.isArray) ?? [];   // ✅
```

### Verify
Properties/Units/Tenants/Invoices/Payments all show their rows after reload; the unit/tenant create dropdowns are populated.

> Related minor issue: `toPaginationMeta()` reads `response.page` / `response.per_page`, but the API returns `current_page` / `pages`. Pagination *count* works (total is read), but the page-number/per-page meta is wrong. Low priority — see §8.4.

---

## 6. 🟠 BUG 5 — Manual invoice creation always returns 400

### Symptom
`POST /invoices` → `400 "tenant_id, unit_id, property_id, and issue_date are required."` for every manual invoice.

### Root cause (two problems)
1. `InvoiceForm` only collects a **tenant** (plus dates + line items) — it never sends `unit_id` / `property_id`, but the backend required them.
2. Even once that's resolved, `create_invoice` computed the invoice total from a per-line `amount` field that the form never sends (the form sends `quantity` + `unit_price`), so `computed_total` was `0` and the request was rejected for not matching the declared `total_amount`.

### Fix — `server/routes/invoice_routes.py::create_invoice`
- Derive `unit_id` / `property_id` from the tenant when the client doesn't send them (a tenant already maps to a unit → property).
- Compute each line as `quantity * unit_price` when no explicit `amount` is present, consistent with how the `InvoiceLineItem` rows are built lower down.

```python
if tenant_id and (not unit_id or not property_id):
    _tenant = Tenant.query.filter_by(id=tenant_id, landlord_id=landlord_id).first()
    if _tenant:
        unit_id     = unit_id     or _tenant.unit_id
        property_id = property_id or (_tenant.unit.property_id if _tenant.unit else None)
...
def _line_amount(li):
    if li.get("amount") not in (None, ""):
        return Decimal(str(li["amount"]))
    return Decimal(str(li.get("quantity", 1))) * Decimal(str(li.get("unit_price", 0)))
computed_total = sum((_line_amount(li) for li in line_items), Decimal("0"))
```

### Verify
Create a manual invoice (tenant + one line item) → **201**, correct `total_amount`/`balance`, and the tenant's balance decreases by the invoice amount. Confirmed: INV-6-00001/2/3 created with totals 25,000 / 25,000 / 32,000.

---

## 7. 🟠 BUG 6 — Communications "Send message" always 400

### Symptom
`POST /communications/send` → `400 "tenant_ids list is required."`

### Root cause
The composer state is `{ tenant_id, message_type, content }`, sent verbatim, but the endpoint expects `{ tenant_ids: [int], channel, content }`. Classic field-name/contract drift.

### Fix — `client/src/features/landlord/communications/CommunicationsPage.jsx`
```js
await sendCommunication({
  tenant_ids: compose.tenant_id ? [Number(compose.tenant_id)] : [],
  channel: compose.message_type,
  content: compose.content,
}).unwrap();
```

### Verify
After the fix the request passes the contract check and reaches the business rule (`"Insufficient SMS balance. Required: 1, Available: 0."`) — expected for a brand-new landlord with 0 SMS balance. Top up SMS balance to send for real.

---

## 8. 🟠 BUG 7 — Dashboard "Occupancy" and "Paid vs invoiced" show 0

### Symptom
On `/landlord/dashboard`, the **Occupancy** card showed `0` and **Paid vs invoiced** showed `KES 0.00 / KES 0.00`, even though the data existed (3/4 units occupied; 67,000 paid of 82,000 billed). Arrears/advances were correct.

### Root cause
The backend `/dashboard/summary` returns the right numbers but under different keys than the frontend reads:

| Card | Frontend read (❌) | API key (✅) |
|------|--------------------|--------------|
| Occupancy | `occupancy_rate` | `occupancy_percent` |
| Paid | `total_paid` | `payments_this_month` |
| Invoiced | `total_invoiced` | `invoices_this_month` |

(`total_arrears` / `total_advances` happened to match, which is why those two cards worked.)

### Fix — `client/src/features/landlord/LandlordDashboard.jsx`
```jsx
<SummaryCard label="Occupancy" value={summary?.occupancy_percent ?? 0} ... />
<SummaryCard label="Paid vs invoiced"
  value={`${formatCurrency(summary?.payments_this_month)} / ${formatCurrency(summary?.invoices_this_month)}`} ... />
```

### Verify
Dashboard now shows **Occupancy 75** and **Paid vs invoiced KES 67,000.00 / KES 82,000.00**.

---

## 9. ✅ What works (verified end-to-end after the fixes)

Every page below loaded with **no API failures**, rendered its data, and (where applicable) accepted a create and persisted it:

| Module | Create via UI | Persists & renders | Notes |
|--------|:---:|:---:|-------|
| Dashboard | — | ✅ | all 4 metric cards + arrears table accurate |
| Properties | ✅ | ✅ | full optional-field form |
| Units | ✅ | ✅ | property dropdown populated, 4 units |
| Tenants | ✅ | ✅ | cascading property→unit selects |
| Utilities | ✅ | ✅ | consumption auto-computed (150−100=50 etc.) |
| Invoices | ✅ | ✅ | after Bug 5 fix |
| Payments | ✅ | ✅ | balances update correctly |
| Expenses | ✅ | ✅ | |
| Maintenance | ✅ | ✅ | |
| Property Groups | ✅ | ✅ | |
| Communications | ✅ (payload fixed) | n/a | blocked only by SMS balance (expected) |
| Notifications | partial | n/a | see §10.4 |
| Reports → Statements | ✅ | ✅ | PDF + Excel; numbers verified (below) |
| Reports → Insights | — | ✅ | arrears/advances/occupancy accurate |
| Settings → General | ✅ save | ✅ | company name persisted |
| Settings → Account | loads | — | password/profile form present |
| Settings → Alerts | loads | — | cadence/channel form present |
| Settings → Backup | loads | ✅ API | `POST /settings/backup` needs `scope_type` |
| Settings → Documents | loads | ✅ API | `/documents/templates` empty list |
| Settings → Team | ✅ create | ✅ | **team-member creation works** (1 editor created) |
| Settings → Billing | loads | ✅ API | |
| Settings → M-Pesa | loads | ✅ | transaction-status page |
| Settings → Audit | — | ✅ | **20 actions logged accurately** (see below) |
| Settings → Impersonation | loads | ✅ | requests list |

### Reports — numbers verified against the dataset (via Excel export)
- **Arrears report:** Mary Wanjiku · A2 · **KES 15,000.00** (only tenant in arrears; sign correct) ✔
- **Tenant statement (Mary):** Invoice INV-6-00002 −25,000 → Payment 10,000 → running balance **−15,000** ✔
- **Property statement:** all 3 payments listed, **67,000** collected ✔
- **Expenses report:** garbage · **5,000** · Total 5,000 ✔
- **Insights:** Mary in arrears, John & Peter zero-balance, advances empty ✔
- **Occupancy:** 4 units total, B2 flagged vacant, 3 occupied = **75%** ✔

### Audit trail — verified
The audit log captured every write made during the walkthrough with correct action names: `create_tenant×3, create_utility_reading×3, create_invoice×3, create_payment×3, create_expense, create_maintenance_request, create_property_group, update_general_settings, update_automation_settings, create_team_member, update_team_member_permissions, update_team_member_property_access`.

---

## 10. 🟡 Minor issues & observations (not yet fixed)

### 10.1 React "controlled/uncontrolled Select" warning (low)
Console warning on Invoices, Payments, Expenses, Reports, and several Settings pages:
> *Select elements must be either controlled or uncontrolled…*

The shared `components/ui/Select.jsx` (or its callers) passes both a `value` and a `defaultValue`, or a `value` that starts `undefined`. Harmless at runtime but noisy and a real React anti-pattern. **Fix:** ensure `value` is always a defined string (default to `""`) and never pass `defaultValue` alongside it.

### 10.2 Invalid nested `<button>` on Invoices page (low)
Console error on `/landlord/invoices`:
> *In HTML, `<button>` cannot be a descendant of `<button>` … will cause a hydration error.*

A clickable control (likely a row action or icon button) is rendered inside another `<button>`. **Fix:** change the inner/outer element to a non-button (e.g. a `<div role="button">` or restructure so actions aren't nested inside a row button).

### 10.3 Form labels not associated with inputs (low, a11y)
Across forms the `<label>` elements have no `htmlFor` and inputs have no `id`, so labels aren't programmatically tied to fields (hurts screen readers and test tooling). **Fix:** give `components/ui/Input.jsx` / `Select.jsx` a generated `id` and set `htmlFor` on the label.

### 10.4 In-app notifications to "all tenants" find no recipients (medium-ish)
`POST /notifications/send` with audience `all_tenants` → `400 "No recipients matched that audience."` Reason: tenants created through the landlord form have `user_id = null` (no user account until they onboard via tenant OTP login), and in-app notifications target *users*. So a landlord who just added tenants cannot notify them in-app yet. **Decide intent:** either auto-provision a tenant user on creation, or make the UI explain that only onboarded tenants receive in-app notifications, or fall back to SMS for un-onboarded tenants.

### 10.5 Email verification not enforced at login (decide intent)
`register` sets `is_verified=false` and "sends" a verification email (stubbed), but `POST /auth/login` never checks `is_verified`. New landlords can use the app immediately. This is convenient for testing but means the verification step is effectively optional. Confirm whether that's intended; if not, gate login (or specific actions) on `is_verified`.

### 10.6 `toPaginationMeta` key mismatch (low)
`client/src/utils/tableAdapters.js::toPaginationMeta` reads `response.page` / `response.per_page`, but the API returns `current_page` / `pages`. Multi-page lists will show the wrong current page / page size. **Fix:** read `response.current_page` and derive per-page, or standardise the API meta keys.

---

## 11. Coverage notes (full disclosure)

**Exercised:** registration, login, all 25 landlord routes, and the create flow for Properties, Units, Tenants, Utilities, Invoices, Payments, Expenses, Maintenance, Property Groups, Team members; General-settings save; report generation (PDF + Excel) and insights; audit verification.

**Not exhaustively exercised** (recommend a follow-up pass, now that the portal is usable): bulk/generate flows (Generate rent/penalty/recurring invoices, bulk utilities, bulk invoices), bank-statement upload & review, file uploads (logo/receipt/signature/photo — these go through the `FormData` path that the Bug-3 sanitizer intentionally skips), Edit and Delete actions on each list (only Create was deeply verified), the M-Pesa STK flow, billing/subscription payment, and the impersonation request lifecycle. These returned no load errors but their write paths were not individually submitted.

---

## 12. Suggested regression guard

To stop bugs 1, 4, 5, 7 (all contract/shape drift) from recurring, add a tiny contract test that, for each list endpoint, asserts `toRows(response).length === response.total`, and a dashboard test asserting the summary keys the UI reads actually exist in the API response. Bugs 2 and 3 are well covered by a single Playwright smoke test that logs in, creates a property with only the required fields, and asserts it appears in the list.
