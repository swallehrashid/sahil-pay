# SPEC — Landlord Onboarding & Tutorials System

**Status:** Approved for implementation.
**Scope:** Landlord portal only (role `landlord` / `property_manager`). No tenant, team-member, affiliate or admin tutorials in v1.
**Audience:** This document is written to be executed end-to-end by an implementing agent with no further product decisions needed. Where the doc says *verify*, it means: open the referenced file and confirm the detail before coding against it — do not guess.

---

## 1. Purpose

New landlords currently learn SahilPay through back-and-forth calls with the admin. This feature replaces most of those calls with:

1. A **first-login onboarding flow** — a welcome modal that offers a guided, step-by-step setup covering the core workflow (property → units → tenant → charge categories → invoice → payment → communication), skippable at every point.
2. A **persistent "Getting started" checklist** on the landlord dashboard that survives skipping the welcome modal, tracks real progress, and re-launches any step.
3. A **Help & Tutorials hub page** (top-level sidebar item) where every tutorial can be re-run individually at any time — segmented by topic, so the admin can tell a caller *"open Help & Tutorials and run the invoicing tutorial"*.

Success criterion: a landlord who has never seen SahilPay can, without a phone call, create a property, add units, onboard a tenant, understand charge categories, issue an invoice, record and allocate a payment, and understand exactly how SMS vs in-app notifications work (including the default `SahilPay` sender ID and the manual-payments-until-M-Pesa-is-connected story).

## 2. Locked product decisions (do not revisit)

| Decision | Choice |
|---|---|
| Tutorial format | **Hybrid**: interactive spotlight tours on the live UI for hands-on flows; slide-carousel explainers for conceptual topics. Built **in-house** — no third-party tour library (react-joyride/driver.js are not to be added; React 19 compatibility and theme control are the reasons). |
| First-login push | **Welcome modal + persistent dashboard checklist.** Never hard-block the app. Esc / "Skip" always available. |
| Hub location | **Dedicated sidebar page** `Help & Tutorials` at `/landlord/tutorials`, placed between "Notifications" and "Settings". |
| Progress storage | **Backend**, on the `Landlord` row (new JSON text column), exposed via a settings-style endpoint and hydrated through `/auth/me`. localStorage is used only as a same-session cache, never as the source of truth. |

## 3. Product facts — canonical copy inputs

All tutorial copy below is grounded in these verified facts. If any copy contradicts the code at implementation time, **the code wins** — fix the copy, and verify against the referenced file.

- **Charge categories** (`server/models.py` ~line 281, `CATEGORY_RESTRUCTURE_SPEC.md`): every chargeable thing is a `ChargeCategory` with `kind = utility | invoice`. Utility categories are managed on the **Utilities** page; invoice categories (rent, lease fees, …) on the **Invoices** page (via `ChargeCategoryManager.jsx`). Each category implicitly owns **three subcategories**: `deposit` (refundable, never rolls over, excluded from income), `balance` (arrears carried from prior months), `current` (this month's charge). Money lives on invoice **line items** stamped with category+subcategory — allocation, rollover and reporting all happen at line level.
- **Allocation**: payments are allocated across open invoice line items following the landlord's priority order (`allocation_priority_json`, edited in **Settings → General** via `AllocationPriorityEditor.jsx`, keys of the form `<category_id>:<subcategory>`). Overpayment becomes tenant **credit** applied to future invoices. Month-end **rollover** closes unpaid `current` lines and carries them forward as `balance` (line status `rolled`, excluded from "outstanding").
- **SMS** (`server/services/sms_billing.py`): landlords without their own sender ID send under SahilPay's shared sender ID — the constant `DEFAULT_PLATFORM_SENDER = "SahilPay"` — from SahilPay's credit pool, paying per SMS from their `sms_balance` credits. A landlord who connects their **own Africa's Talking sender ID** (Settings → SMS Provider, `connect`/`disconnect` endpoints in `settings_routes.py`) sends under their own brand from their own AT account and is billed SahilPay's service fee per SMS. Verify exact landlord-facing pricing wording against `sms_billing.py` before finalising copy.
- **In-app notifications**: sent from `/landlord/notifications/send` (`notificationsSend` route); they appear in the tenant portal's notifications page and are **free** (no SMS credits).
- **Communications page** (`CommunicationsPage.jsx`): compose SMS to a tenant (deep-linkable with `?compose=sms&tenant_id=`), message **templates** tab (`balance_reminder`, `invoice_reminder`, `custom`), a communications **log** with statuses and a resend action. It reads the SMS provider status via `useGetSmsProviderQuery` to show which sender ID is active.
- **Payments**: recorded **manually** (`RecordPaymentForm.jsx`, confirmed via `ConfirmPaymentModal.jsx`) until the landlord's M-Pesa paybill/till is connected — after connection, C2B payments record automatically (`mpesa_routes.py`). **Settings → M-Pesa Status** (`MpesaStatus.jsx`) lets a landlord check whether a specific M-Pesa reference was recorded (select shortcode, enter reference). Bank-statement import (`BankStatementReview.jsx`) exists but is an *advanced* mention only, not a tutorial.
- **Tenants**: a tenant is assigned to a vacant unit; tenants get portal access via **OTP login** (SMS or email) at `/tenant/login` — no password to manage.
- **Utilities**: meter readings recorded via `RecordUtilityForm.jsx` become invoice line items under the chosen utility category.
- **Reports**: `reports/statements` is the hub of report types; `reports/insights` is the charts/analytics page.
- **Trial/billing**: landlords start on a trial (`is_on_trial`, `trial_ends_at`); billing lives at Settings → Billing. One checklist mention, no dedicated tutorial.

## 4. Backend

### 4.1 Model + migration

In `server/models.py`, add to `Landlord` (near `sms_balance`):

```python
# Landlord onboarding/tutorials progress — JSON blob, shape owned by the
# frontend tutorials module (see ONBOARDING_TUTORIALS_SPEC.md §4.3).
onboarding_state_json = Column(Text, nullable=True)
```

Include the parsed value in `Landlord.to_dict()` as `onboarding_state` (parse with `json.loads`, fall back to `None` on empty/invalid). This makes `/auth/me` hydrate it with zero extra requests — `me()` in `auth_routes.py` already embeds `lp.to_dict()` as `payload["profile"]`.

Alembic migration in `server/migrations/versions/` following the existing naming style (e.g. `xxxx_landlord_onboarding_state.py`): `add_column landlords.onboarding_state_json TEXT NULL`; downgrade drops it. No data backfill — `NULL` means "brand-new, never saw onboarding", which is exactly the semantics the frontend wants (existing landlords predate the feature; see §4.4).

### 4.2 Endpoint

In `server/routes/settings_routes.py`, following the exact style of the existing `general_settings` handler:

```
GET /api/settings/onboarding
PUT /api/settings/onboarding
```

- Decorators: `@jwt_required()` + `@require_landlord_or_team()`. Inside the handler, **writes must be rejected for team members** (403) — tutorials are landlord-only in v1; team members share these page components, so the guard must be server-side, not just UI. Verify how other handlers detect the team-member case (e.g. `_check_permission_settings_edit` / the identity helpers already in that file) and reuse that mechanism.
- `GET` returns:

```json
{
  "state": { ...parsed onboarding_state_json or null... },
  "counts": {
    "properties": 0, "units": 0, "tenants": 0,
    "invoices": 0, "payments": 0, "charge_categories": 0
  }
}
```

`counts` are cheap `COUNT(*)` queries scoped to the landlord (`db.session.query(func.count(...))`), used by the dashboard checklist to auto-complete items from real data (a landlord who added a property *without* running the tutorial still gets the tick).

- `PUT` accepts the full state object, validates it is a JSON object ≤ 8 KB, stores it verbatim in `onboarding_state_json`, returns the stored state. **Last-write-wins, whole-object replace** — no server-side merging; the client always sends the complete state. Do not audit-log these writes (they are UI telemetry, not business actions — keep the audit trail meaningful).

### 4.3 State shape (owned by the frontend, documented here)

```json
{
  "version": 1,
  "welcome_seen_at": "2026-07-08T10:00:00Z",
  "checklist_dismissed_at": null,
  "tutorials": {
    "create-property": { "status": "completed", "at": "2026-07-08T10:05:00Z" },
    "communications":  { "status": "skipped",   "at": "2026-07-08T10:09:00Z" }
  }
}
```

`status ∈ completed | skipped`. A tutorial not present in the map has never been finished. `version` exists so future content overhauls can re-prompt; v1 writes `1` and never branches on it.

### 4.4 Existing landlords

Existing landlords have `NULL` state and **will** see the welcome modal once on their next login. This is intentional (they've never seen the tutorials either) — but the modal copy must read correctly for them too, so it says "Take a quick tour of SahilPay" not "Welcome to your new account". They dismiss once, it's stored, done.

### 4.5 Impersonation guard

When `/auth/me` returns `payload.impersonating` (admin operating a landlord account), the frontend must **never auto-open** the welcome modal and must **never write** onboarding state — the admin poking around must not consume the landlord's one-time welcome. Tutorials may still be launched manually from the hub while impersonating (useful for the admin walking a landlord through by phone); they just don't persist completion.

### 4.6 Tests

Add `server/tests/test_onboarding_settings.py` following the existing test style: GET returns null state + zero counts for a fresh landlord; PUT stores and GET round-trips; PUT as team member → 403; counts reflect seeded entities; oversized payload → 400.

## 5. Frontend architecture

New module: `client/src/features/landlord/tutorials/`

```
tutorials/
  tutorialsApiSlice.js        // RTK Query: getOnboarding / updateOnboarding
  tourSlice.js                // plain Redux slice: the active tour runtime state
  anchors.js                  // THE anchor registry — every data-tour id, one place
  useOnboardingState.js       // read/merge/write helper around the API slice
  TourProvider.jsx            // mounts overlay, exposes startTutorial(id)/exitTour()
  TourOverlay.jsx             // spotlight + step card renderer
  ExplainerModal.jsx          // slide-carousel renderer for explainer tutorials
  WelcomeModal.jsx            // first-login modal
  GettingStartedChecklist.jsx // dashboard card
  TutorialsPage.jsx           // the Help & Tutorials hub
  content/
    index.js                  // TUTORIALS registry: ordered array of definitions
    welcomeOverview.js  createProperty.js  addUnits.js  addTenant.js
    chargeCategories.js createInvoice.js   recordPayment.js
    paymentsAndMpesa.js allocation.js      communications.js  reports.js
```

### 5.1 API slice

`tutorialsApiSlice.js` mirrors `settingsApiSlice.js` exactly: `injectEndpoints`, `getOnboarding: query → "/settings/onboarding"` providing tag `Onboarding`, `updateOnboarding: mutation PUT` invalidating `Onboarding`. Add `"Onboarding"` to the `tagTypes` array in `client/src/store/apiSlice.js`.

`useOnboardingState.js` wraps these: exposes `{ state, counts, isLoading, markWelcomeSeen(), dismissChecklist(), markTutorial(id, status) }`. Every mutator builds the **full next state object** from the last known state and PUTs it. All mutators are no-ops when the session is impersonating or the role is not landlord/property_manager (§4.5). Seed the initial in-memory state from `user.profile.onboarding_state` (already in the `/auth/me` payload) so the welcome-modal decision needs **no extra request** on login.

### 5.2 Tour engine (`tourSlice` + `TourProvider` + `TourOverlay`)

Runtime state in `tourSlice`: `{ activeTutorialId, stepIndex, mode: 'tour'|'explainer'|null, origin: 'onboarding-sequence'|'standalone', sequenceIds: string[]|null, sequencePos: number|null }`.

`TourProvider` is mounted **once**, inside the landlord layout in `AppRoutes.jsx` (reminder: the real layout lives in `AppRoutes.jsx`, *not* `DashboardLayout.jsx`), so it survives route changes. It renders `TourOverlay` or `ExplainerModal` when a tutorial is active and exposes `startTutorial(id, { sequence })` via context + a `useTour()` hook.

**Step definition** (in content files):

```js
{
  anchor: "properties.addButton",       // key into anchors.js — or null for a centered card
  route: LANDLORD_ROUTES.properties,     // navigate here before showing (null = stay)
  title: "Create your first property",
  body: "…",                             // plain string; \n\n = paragraphs
  placement: "bottom",                   // preferred; engine flips if no room
  advanceOn: { event: "click" },         // OPTIONAL enhancement — Next button ALWAYS works too
  desktopOnly: false,                    // see §9 mobile rules
}
```

**Engine behaviour — these are hard requirements:**

1. **Navigation**: if `step.route` differs from the current location, `navigate(route)` first, then resolve the anchor.
2. **Anchor resolution**: poll `document.querySelector('[data-tour="<id>"]')` every 150 ms for up to **3 s** (lazy routes + data loading). Prefer a **visible** match when multiple exist (empty-state CTA vs header button — both carry the same anchor, engine picks the one with a non-zero client rect).
3. **Fail-safe (non-negotiable)**: if no anchor resolves in 3 s, render the step as a **centered card** with the same title/body — never a blank overlay, never a stuck spinner, never a blocked app. Log a `console.warn("[tour] anchor missing: …")` so drift is diagnosable.
4. **Spotlight**: full-viewport fixed overlay dimming the page (`bg-black/60`), with a rounded-rect cutout around the target (SVG mask or `box-shadow: 0 0 0 9999px` technique — implementer's choice), target padded ~8 px, `scrollIntoView({ block: "center", behavior: "smooth" })` before highlighting. The target element itself remains **clickable** (overlay uses pointer-events such that the cutout area passes clicks through — implement via four dim divs around the cutout, or `pointer-events: none` on the mask with a separate click-catcher). Recompute the cutout on `resize` and `scroll` (rAF-throttled).
5. **Step card**: dark-theme card matching existing idioms (`rounded-2xl`, `border-white/10`, `bg-…` consistent with `Modal.jsx` — copy its surface classes), showing: step counter ("Step 2 of 6"), title, body, and buttons `Back / Next / Exit tour` (final step: `Done`). During an onboarding **sequence**, also show a slim progress line: "Part 3 of 8 — Add your first tenant".
6. **Keyboard**: `Esc` exits (always), `←`/`→` back/next. Focus moves to the step card on each step (a11y).
7. **Exit semantics**: `Exit tour` on step ≥ 2 marks the tutorial `skipped`; finishing the last step marks `completed`. Exiting on step 1 records nothing. No mid-tour resume — relaunching starts from step 1 (tours are ≤ 8 steps; resume is not worth the state).
8. **`advanceOn`** (progressive enhancement): when present, a matching event on the anchor advances the tour automatically *in addition to* the Next button. v1 uses it only where noted in §7. If the click navigates or opens a modal, the next step's anchor resolution (rule 2) handles the new DOM.
9. **Z-index**: above `Modal.jsx`/`Drawer.jsx` — inspect their z classes and go one layer higher (e.g. `z-[100]`). Tours must be able to highlight elements *inside* an open modal (the property form steps depend on this).
10. **Route guard**: if the user hard-navigates away mid-tour (sidebar click outside the flow), exit the tour cleanly (same as Exit).

### 5.3 Explainer engine (`ExplainerModal`)

A `Modal.jsx`-based carousel: slide = `{ icon (lucide component), title, body, bullets?: string[] }`. Dots + Back/Next/Done, Esc closes (= skipped unless on final slide; final-slide Done = completed). Slides are pure content — no DOM anchors, so explainers can never break from UI drift. Some explainer tutorials end with a `cta: { label, route }` button (e.g. "Open SMS Provider settings").

### 5.4 Anchor registry (`anchors.js`)

Single source of truth mapping semantic keys → `data-tour` string values, e.g.:

```js
export const ANCHORS = {
  sidebar: { properties: "sidebar-properties", invoices: "sidebar-invoices", /* … */ },
  properties: { addButton: "properties-add", form: "properties-form", saveButton: "properties-save" },
  /* … one group per page used in §7 … */
};
```

Then add `data-tour={ANCHORS.x.y}` attributes to the real components. **Every anchor consumed in §7 must be added in the same PR** — grep for the constant, not the string. Anchor placement work per page:

| Page/component | Anchors to add |
|---|---|
| `LandlordSidebar.jsx` / `Sidebar.jsx` | one per nav item used in tours (pass through to the rendered link: `sidebar-properties`, `sidebar-units`, `sidebar-tenants`, `sidebar-invoices`, `sidebar-payments`, `sidebar-utilities`, `sidebar-reports`, `sidebar-communications`, `sidebar-notifications`, `sidebar-settings`, `sidebar-tutorials`) |
| `PropertiesPage.jsx` | add-property button (header action **and** the `EmptyState` CTA — same anchor value on both, engine picks the visible one), the create form/modal root, its save button |
| `UnitsPage.jsx` | add-unit button (+ EmptyState CTA), form root, property selector inside the form, save |
| `TenantsPage.jsx` | add-tenant button (+ EmptyState CTA), form root, unit selector, phone field, save |
| `InvoicesPage.jsx` / `InvoiceForm.jsx` | create-invoice button, manage-categories button/section (`ChargeCategoryManager` trigger), tenant selector, line-items area, save |
| `PaymentsPage.jsx` / `RecordPaymentForm.jsx` | record-payment button, tenant selector, amount field, save/confirm |
| `UtilitiesPage.jsx` | record-reading button, manage-utility-categories area |
| `StatementsPage.jsx` | report-type list/cards container |
| `CommunicationsPage.jsx` | compose button, templates tab, log table |
| `LandlordDashboard.jsx` | KPI/summary cards container, checklist card |
| `SettingsLayout.jsx` | settings nav: general, sms-provider, mpesa entries |

Exact JSX targets are the implementer's job — put the attribute on the element the user actually clicks. Where a page's structure makes an anchor awkward, prefer adjusting the step copy over contorting the DOM.

## 6. Entry points

### 6.1 Route + sidebar

- `routePaths.js`: add `tutorials: "/landlord/tutorials"` to `LANDLORD_ROUTES` (a top-level key like `bankStatementReview` — **not** in `SHARED_MODULES`; team members don't get it).
- `AppRoutes.jsx`: lazy `TutorialsPage`, mounted in the landlord portal section only.
- `LandlordSidebar.jsx`: insert `{ to: LANDLORD_ROUTES.tutorials, label: "Help & Tutorials", icon: <GraduationCap className="h-4 w-4" /> }` between Notifications and Settings (`GraduationCap` from `lucide-react`).

### 6.2 Welcome modal (`WelcomeModal.jsx`)

Rendered by `TourProvider`. Auto-opens when **all** hold: role is landlord/property_manager · not impersonating · `state.welcome_seen_at == null` · onboarding state has hydrated (never flash it while `/auth/me` is loading) · no tour already active. On open, immediately `markWelcomeSeen()` (prevents re-show loops even if they close the tab).

Content: SahilPay-styled full modal — title **"Welcome to SahilPay 👋"**, body: *"Let's get your first property set up. This guided tour walks you through everything you need to start collecting rent — properties, units, tenants, invoices, payments and messaging your tenants. It takes about 10 minutes and you can leave at any point."* Buttons: **"Start the guided setup"** (primary → starts the onboarding sequence, §7.0) and **"Skip for now — I'll explore on my own"** (ghost). Under the skip button, small print: *"You can run any tutorial later from Help & Tutorials in the sidebar."*

### 6.3 Getting-started checklist (`GettingStartedChecklist.jsx`)

A card at the top of `LandlordDashboard.jsx`. Visible while: role landlord/PM · not impersonating · `checklist_dismissed_at == null` · **not everything complete**. When all items complete, it swaps to a one-time "You're all set 🎉" state with a "Hide this" button (which sets `checklist_dismissed_at`); a manual "Dismiss" (small ✕, with confirm via `ConfirmDialog.jsx`) is available any time.

Items (each row: check icon, label, and a **"Show me"** button that launches the tutorial):

| Item | Auto-complete condition (OR) |
|---|---|
| Create your first property | `counts.properties > 0` \|\| tutorial `create-property` completed |
| Add your units | `counts.units > 0` \|\| `add-units` completed |
| Add a tenant | `counts.tenants > 0` \|\| `add-tenant` completed |
| Set up your charge categories | `counts.charge_categories > 0` \|\| `charge-categories` completed |
| Create your first invoice | `counts.invoices > 0` \|\| `create-invoice` completed |
| Record a payment | `counts.payments > 0` \|\| `record-payment` completed |
| Learn how tenant messaging works | `communications` completed or skipped |
| See your reports | `reports` completed or skipped |

Counts come from `getOnboarding` (§4.2). Progress bar: "5 of 8 done".

### 6.4 Help & Tutorials hub (`TutorialsPage.jsx`)

`PageHeader` title "Help & Tutorials", subtitle "Step-by-step guides to everything in SahilPay. Run any of them as many times as you like."

Cards grouped into sections, each card: lucide icon, name, one-line description, duration hint ("~2 min"), status badge (`Completed` / `Not started` — use `Badge.jsx`), and a **Start** button (`useTour().startTutorial(id)`). Top of page: a prominent **"Run the full guided setup"** banner button that starts the whole onboarding sequence (§7.0) — this is what the admin tells new landlords on the phone.

Sections & order = §7 groups: **Getting set up** (welcome-overview, create-property, add-units, add-tenant) · **Billing** (charge-categories, create-invoice) · **Payments** (record-payment, payments-and-mpesa, allocation) · **Communication** (communications) · **Reports** (reports).

## 7. Tutorial catalogue — content

The copy below is **canonical**: implement it verbatim (fixing only factual drift against the code per §3). Body strings support `\n\n` paragraph breaks. Where a step references a form field, verify the field's label in the actual component and mirror it exactly.

### 7.0 The onboarding sequence

`ONBOARDING_SEQUENCE = ["welcome-overview", "create-property", "add-units", "add-tenant", "charge-categories", "create-invoice", "record-payment", "communications"]` (reports/allocation/mpesa are hub-only — keep first contact to the essentials).

Between tutorials in a sequence, show an **interstitial card** (centered, dimmed backdrop): "✓ Nice — *{finished title}* done." + "Next up: **{next title}** ({duration})" with buttons **Continue** / **Finish later** (Finish-later exits the sequence; completed tutorials stay completed; the checklist carries the rest). The sequence skips tutorials already `completed`.

### 7.1 `welcome-overview` — "A quick look around" · tour · ~1 min

Route: dashboard. Steps:

1. *(centered card)* **Your dashboard** — "This is your home base. Every number you see here — collections, arrears, occupancy — updates live as you work. Let's take 60 seconds to see where everything lives."
2. *(anchor: dashboard KPI cards)* **Your numbers at a glance** — "These cards summarise your portfolio. They'll be zeros right now — by the end of this setup they'll be alive."
3. *(anchor: sidebar-properties)* **Properties & Units** — "Everything starts here: you create properties, then units inside them, then place tenants in units."
4. *(anchor: sidebar-invoices)* **Invoices & Payments** — "Each month you invoice tenants for rent and utilities, and record what they pay. SahilPay tracks every shilling per tenant, per line item."
5. *(anchor: sidebar-communications)* **Talk to your tenants** — "Send SMS and in-app messages — payment reminders, notices, receipts. We'll cover exactly how SMS works (and what it costs) in this setup."
6. *(anchor: sidebar-tutorials)* **Help is always here** — "Every tutorial in this setup lives in Help & Tutorials, so you can re-run any of them whenever you need a refresher."

### 7.2 `create-property` — "Create a property" · tour · ~2 min

Route: properties. Steps:

1. *(anchor: sidebar-properties, advanceOn click)* **Open Properties** — "Click Properties in the sidebar."
2. *(anchor: properties add button, advanceOn click)* **Add your property** — "Click here to create your first property. A property is a building or plot — units and tenants will live inside it."
3. *(anchor: property form)* **Fill in the details** — "Give the property a name your tenants would recognise (e.g. 'Mombasa Heights'), plus its location details. You can edit any of this later."
4. *(anchor: property form save)* **Save it** — "Click save. That's it — your first property exists. Next we'll add the units inside it."

Design note: steps 3–4 highlight elements inside the create modal/drawer — this is why the overlay must sit above `Modal.jsx` (§5.2 rule 9).

### 7.3 `add-units` — "Add units to a property" · tour · ~2 min

Route: units. Steps: open Units (sidebar, advanceOn) → add-unit button (advanceOn) → form: **"Pick the property, then give the unit its door label (e.g. 'A1'), its monthly rent and its deposit. Rent set here is what invoices will bill each month."** → property selector highlight: **"Every unit belongs to a property — if you manage several, this is how everything stays organised."** → save → *(centered)* **"Repeat for each unit — most landlords add them all now while they're at it. Vacant units cost nothing; you're billed only for what you manage."** *(verify that last claim against current billing rules in `billing_routes.py` / package logic — soften to 'Add as many as you like' if wrong).*

### 7.4 `add-tenant` — "Add a tenant" · tour · ~2 min

Route: tenants. Steps: open Tenants → add-tenant button (advanceOn) → form: **"Enter the tenant's name and phone number, and assign them to a vacant unit."** → phone field: **"The phone number matters: it's where the tenant receives SMS from you, and it's how they log in to their own tenant portal — they get a one-time code by SMS, no password to forget. They can view their balance, invoices and receipts there, which saves you a lot of 'how much do I owe?' calls."** → unit selector: **"A tenant occupies exactly one unit; moving them later is supported with a full history."** → save.

### 7.5 `charge-categories` — "Charge categories: how billing is organised" · **explainer + mini-tour** · ~3 min

Explainer slides first:

1. **Everything you charge is a category** — "Rent. Water. Electricity. Garbage. Lease fees. In SahilPay each of these is a *charge category*. Categories come in two kinds: **utility** categories (metered/recurring services, managed on the Utilities page) and **invoice** categories (rent and other charges, managed on the Invoices page)."
2. **Every category has three pockets** — bullets: "**Current** — this month's charge." · "**Balance** — arrears carried over from previous months." · "**Deposit** — refundable money you hold; it never mixes with rent and never counts as income."
3. **Why this matters** — "Every invoice line, payment allocation and report is organised by category + pocket. When a tenant asks 'what exactly do I owe?', you can answer to the shilling: 'KES 12,000 current rent, KES 3,500 water balance.'"
4. **Month-end rollover** — "Anything unpaid at month-end automatically rolls from *current* into *balance* — nothing is ever lost or forgotten. Deposits never roll; they just sit safely until refund day."

Then a 2-step mini-tour: route to invoices, highlight the manage-categories control — **"This is where you create and edit your invoice categories (rent is usually first)."** — then route to utilities, highlight the utility-categories area — **"And utility categories live here. Set up the ones you actually bill — water and electricity are the usual starters."**

### 7.6 `create-invoice` — "Create an invoice" · tour · ~3 min

Route: invoices. Steps:

1. *(anchor: create-invoice button, advanceOn click)* **New invoice** — "Click here to bill a tenant."
2. *(anchor: tenant selector)* **Who are you billing?** — "Pick the tenant. Their unit's rent comes in automatically."
3. *(anchor: line items area)* **Line items** — "An invoice is a list of lines — one per charge category: rent, water, garbage… Add whatever applies this month. Each line remembers its category and pocket, which is what makes your reports exact."
4. *(anchor: save)* **Send it** — "Save the invoice. The tenant can see it instantly in their portal, and you can send them an SMS about it from Communications."
5. *(centered)* **You won't do this by hand forever** — "Once you're comfortable, Settings → General has automation that can generate monthly invoices for every occupied unit automatically. Worth switching on after your first manual month." *(verify the automation's exact home/wording against `settings_routes.py` automation section.)*

### 7.7 `record-payment` — "Record a payment" · tour · ~2 min

Route: payments. Steps:

1. *(anchor: record-payment button, advanceOn click)* **Record what came in** — "Tenant paid you? Click here to record it."
2. *(anchor: tenant selector)* **Pick the tenant** — "SahilPay shows what they owe as you pick them."
3. *(anchor: amount field)* **Enter the amount** — "Enter exactly what they paid — even if it's not the full amount. Partial payments are normal; SahilPay spreads the money across what they owe in your priority order, and any extra becomes credit for next month. (There's a short 'How allocation works' guide in Help & Tutorials.)"
4. *(anchor: save/confirm)* **Confirm it** — "Save, review the allocation preview, confirm. The tenant's balance updates everywhere instantly — reports, their portal, everything."
5. *(centered)* **Manual today, automatic soon** — "Right now you record payments yourself. Once your M-Pesa paybill or till is connected to SahilPay, tenant payments will record themselves the moment they land — see 'Getting paid via M-Pesa' in Help & Tutorials for how that works."

### 7.8 `payments-and-mpesa` — "Getting paid via M-Pesa" · explainer · ~2 min · **hub-only**

Slides:

1. **Two phases** — "Every landlord starts in *manual* mode: tenants pay you the way they always have, and you record it in SahilPay. Nothing about how you receive money changes."
2. **Connecting M-Pesa** — "When you're ready, contact the SahilPay team to connect your paybill or till. Once connected, every tenant payment is captured and recorded **automatically, the second it lands** — correct tenant, correct allocation, receipt available immediately. No more evening data entry."
3. **Checking a payment** — "Tenant swears they paid but you can't see it? Settings → M-Pesa Status lets you check any M-Pesa reference against your shortcode and see instantly whether it was recorded."
4. **Also worth knowing** — "You can also import bank statements (Payments → bank statement review) and, on Android, the SahilPay Co-pilot app can forward payment SMS automatically. Both are optional extras — manual recording always works."
   CTA button: **"Open M-Pesa Status"** → `LANDLORD_ROUTES.settings.mpesa`.

### 7.9 `allocation` — "How payment allocation works" · explainer · ~2 min · **hub-only**

Slides:

1. **The problem it solves** — "A tenant owes rent, water and a bit of last month — then pays KES 10,000. Which debt does it clear? SahilPay answers this the same way every time, using **your** priority order."
2. **Your priority order** — "In Settings → General you rank every category-and-pocket (e.g. *rent — balance* before *rent — current* before *water*). Payments fill debts top-to-bottom in that order. Old arrears first is the common choice."
3. **Partial & overpayment** — "Partial payments fill as far down the list as the money reaches. Overpayments become **credit**, which is used automatically against the tenant's next invoice."
4. **You're always in control** — "Every allocation is visible line-by-line on the payment, and your reports break income down by exactly these categories."
   CTA: **"Open allocation settings"** → `LANDLORD_ROUTES.settings.general`.

### 7.10 `communications` — "Messaging your tenants: SMS & in-app" · **explainer + mini-tour** · ~4 min

This one carries the heaviest support-call load — it must be crystal clear. Slides:

1. **Two channels, two costs** — "SahilPay gives you two ways to reach tenants: **in-app notifications** — free, unlimited, delivered inside the tenant's portal — and **SMS** — delivered to their phone even without internet, paid per message from your SMS credits."
2. **How SMS sending works today** — "Out of the box, your SMS go out under the sender name **SahilPay**. Tenants see 'SahilPay' as the sender. You don't need to set up anything — top up SMS credits (Settings → Billing) and send. Your credit balance is always visible, and every sent message is logged."
3. **Your own sender name (optional)** — "Want messages to arrive as *your* brand instead of SahilPay? Register your own sender ID with Africa's Talking, then connect it under **Settings → SMS Provider**. From that moment your SMS carry your name and are sent through your own account — SahilPay just charges a small per-SMS service fee. Until you do this, the SahilPay sender works fine; most landlords start there."
4. **What to send, when** — bullets: "Invoice reminders when you bill." · "Payment receipts / thank-yous." · "Balance reminders before month-end — templates for these are built in." · "Notices (water shutoffs, inspections) — in-app is free and perfect for these."
5. **In-app notifications** — "Send from the **Notifications** page in your sidebar. Free, instant, and the tenant sees it next time they open their portal. Rule of thumb: urgent or money-related → SMS; everything else → in-app first."

Mini-tour: route to communications → highlight compose button — **"Compose an SMS here: pick the tenant, write or pick a template, send."** — highlight templates tab — **"Templates save retyping: balance reminders and invoice reminders are ready to personalise."** — highlight log — **"Every message ever sent, with delivery status. If one fails, resend it from here."** — then route `LANDLORD_ROUTES.notificationsSend`, centered card — **"And this is where free in-app notifications are sent from."**

### 7.11 `reports` — "Your reports" · tour · ~2 min

Route: reports/statements. Steps:

1. *(anchor: report list)* **Everything, on paper** — "Every report SahilPay produces lives here — tenant statements, payment reports, arrears, income by category and more. All of them respect your charge categories, so the numbers match what you bill."
2. *(centered)* **The one to remember** — "The **tenant statement** is the report you'll use most: a full money history for one tenant — every invoice, payment and balance. When a tenant disputes a balance, you send this and the conversation ends."
3. *(route: reports/insights, centered)* **Insights** — "Charts and trends across your whole portfolio — collections over time, occupancy, arrears. Check it monthly; it tells you where to focus."
4. *(centered)* **Export anything** — "Reports export to Excel and PDF — with your company logo once you've added it in Settings → General."

## 8. Styling

Match the existing portal exactly: dark surfaces, `rounded-2xl`, `border-white/10`, `text-white/60` secondary text, the existing `Button.jsx` variants for actions, lucide icons at `h-4 w-4`/`h-5 w-5`. The spotlight ring uses the app's existing accent color (inspect `Button.jsx` primary / active nav classes and reuse that token). Subtle transitions (`transition-all duration-200`) on cutout moves. No confetti, no illustrations, no new fonts. All rendering is fully self-contained — no external assets.

## 9. Mobile & accessibility

- **Mobile (< 768px)**: step cards render as a **bottom sheet** (full-width, docked) instead of a floating popover; spotlight cutout still highlights the target. Steps anchored to **sidebar items** don't work when the sidebar is hidden behind the hamburger: any step whose anchor starts with `sidebar-` renders on mobile as a centered card with adapted copy — write these as: "Open the ☰ menu and tap **Properties**." (Engine rule: sidebar-anchored steps on mobile automatically fall back to the centered card and prepend nothing — the copy variants live in the step as `mobileBody`, falling back to `body` when absent. Provide `mobileBody` for every sidebar-anchored step in §7.)
- Tab focus lands on the step card each step; buttons are real `<button>`s; step card has `role="dialog"` and `aria-label` = tutorial title; Esc always exits.
- Respect `prefers-reduced-motion`: no smooth scrolling / transitions when set.

## 10. Foreseen failure modes → required mitigations

Simulated months ahead — each of these **must** hold in the shipped code:

1. **UI drift breaks anchors** (someone renames/moves a button): the 3-second fallback-to-centered-card (§5.2 rule 3) means tours degrade to readable instructions, never break. The `anchors.js` registry + `console.warn` makes drift findable. Add one line to `CLAUDE.md`: "If you change or move an element carrying a `data-tour` attribute, keep the attribute (registry: `client/src/features/landlord/tutorials/anchors.js`) and re-run the affected tutorial."
2. **Empty-state vs header CTA**: pages render their add-button in `EmptyState.jsx` when there's no data and in the header once data exists — anchor **both** with the same value; the engine picks the visible one (§5.2 rule 2).
3. **Prerequisite gaps** (running "Add units" with zero properties): each tour may declare `prerequisite: { count: "properties", tutorialId: "create-property" }`. On start, if the count is zero, show a small dialog: "You'll need a property first — run *Create a property* now?" → **Start it** / **Cancel**. Applies to: add-units (properties), add-tenant (units), create-invoice (tenants), record-payment (invoices — soft: warn but allow).
4. **Team members** share these page components: `data-tour` attributes are inert for them; `TourProvider`, welcome modal, checklist and the tutorials route are mounted only in the landlord portal; server rejects team-member writes (§4.2).
5. **Impersonating admins** must not consume the landlord's welcome or write progress (§4.5) — but *can* launch tutorials from the hub.
6. **Welcome modal racing other overlays** (toasts, impersonation banner, verify-email nags): the modal only auto-opens on the landlord layout after hydration, once per account, and the checklist is the durable fallback — do not queue/retry the modal.
7. **Slow or failing PUTs**: progress writes are fire-and-forget optimistic — never toast an error for a failed progress write; the merged client state retries on the next mutator call. A failed write can only ever cost a re-shown checklist tick.
8. **Two devices / two tabs**: last-write-wins whole-object PUT is acceptable at this stakes level (worst case: a tick re-appears). Do not build merging.
9. **Existing landlords** see the welcome once (§4.4) — copy already accounts for them.
10. **Content staleness**: all copy lives in `content/*.js` only — never inline in page components — so updating a tutorial is a one-file edit. This spec's §7 is the source; future feature work that changes a flow should update the matching content file in the same PR.

## 11. Explicitly out of scope (do NOT build)

- Video tutorials or screenshots/images inside tutorials (maintenance trap — text + live UI only).
- Tutorials for tenant portal, team members, affiliates, admin (v2 candidates).
- Admin-editable tutorial content (CMS) or admin-side "onboarding status" columns — the backend field makes this cheap **later**; don't build it now.
- Gamification, badges, confetti, streaks.
- Mid-tour resume, tour analytics/telemetry beyond the state blob.
- Third-party tour libraries.
- Forced/blocking onboarding of any kind.
- i18n — English only, matching the rest of the app.

## 12. Implementation order & verification

Build in this order (each step leaves the app working):

1. Backend: column + migration + `to_dict` + endpoint + tests (§4). Run migration + pytest.
2. `tutorialsApiSlice` + `tagTypes` + `useOnboardingState` (§5.1).
3. Tour engine + explainer modal (§5.2–5.3), with a temporary dev-only trigger to iterate.
4. Anchors sweep across all pages in §5.4's table.
5. Content files for all 11 tutorials (§7) + `ONBOARDING_SEQUENCE`.
6. Hub page + route + sidebar item (§6.1, §6.4).
7. Welcome modal + checklist (§6.2–6.3).
8. Mobile pass (§9), then the full verification below.

**Verification checklist (run in the browser, seeded + fresh accounts):**

- [ ] Fresh landlord registration → verify email → first login → welcome modal appears exactly once; Skip → checklist on dashboard; re-login → no modal.
- [ ] "Start the guided setup" runs the full 8-part sequence end-to-end **while actually creating** a property, unit, tenant, categories, invoice and payment through the highlighted UI (this is the real product test).
- [ ] Exit mid-tour with Esc, with the Exit button, and by sidebar navigation — app never left dimmed/stuck in any of the three.
- [ ] Temporarily break one anchor (rename its `data-tour` value) → step degrades to centered card with a console warning, tour still completes. Restore it.
- [ ] Checklist auto-ticks from real data: create a property *without* the tutorial → tick appears after refetch.
- [ ] Prerequisite dialog: fresh account → start "Add units" from the hub → offered "Create a property" first.
- [ ] Hub: every tutorial launches, completes, and shows the Completed badge; re-running a completed one works.
- [ ] Team member login: no tutorials nav item, no welcome modal, no checklist; direct nav to `/landlord/tutorials` doesn't render for them; PUT as team member → 403 (pytest).
- [ ] Admin impersonating a landlord: no welcome modal; hub tutorials run; landlord's stored state unchanged after the session.
- [ ] Mobile viewport (375px): bottom-sheet cards, sidebar-anchored steps fall back to `mobileBody` centered cards, nothing overflows.
- [ ] Existing seeded landlord (pre-feature): sees welcome once with the generic "quick tour" copy; dismisses; never again.
- [ ] `npm run lint` clean; full pytest suite green.
