# SAHIL PAY — BRANDING SPEC

**Status:** Ready to execute · **Owner:** Swalleh · **Executor:** Claude (Sonnet)
**Goal:** Apply the official Sahil Pay logo, letterhead, slogan, and contact identity to every
surface of the platform — web app (all portals), generated PDFs/exports, emails, and the
Co-pilot Android app — using the assets that already exist in the repo (§2). Do **not**
redesign the logo; only wire it in.

---

## 1. Brand identity (canonical values)

| Token | Value |
|---|---|
| Name (display) | **Sahil Pay** (two words in user-facing text; `SahilPay` stays fine in code/identifiers) |
| Wordmark | `SAHIL PAY` — serif, letter-spaced, all caps |
| Slogan | `SMART RENT COLLECTION` — always all-caps, wide letter-spacing, under the wordmark |
| Phone | `0114 129 809` |
| Email | `info@sahilpay.co.ke` |
| Website | `https://sahilpay.co.ke` |
| Location | Nairobi, Kenya |
| Ink (light surfaces) | `#0f0246` (existing `--color-primary` / `primary-900`) |
| Ink (dark surfaces) | `#ffffff` |
| Accent | `#200497` (existing `--color-third`) |
| Wordmark font | **Cinzel** (Google Fonts) → fallback `'Playfair Display', Georgia, serif` |
| Slogan font | Existing sans stack (Inter / Montserrat / Helvetica) |

The logo is **monochrome and transparent-background by design**. It is rendered in whatever
ink the surface needs (white on dark sidebars, navy on light pages, black on print). Never
ship it on a white box inside a dark UI.

## 2. Assets already in the repo (source of truth — use these, do not recreate)

| Asset | Path | Use |
|---|---|---|
| React logo component | `client/src/components/branding/SahilPayLogo.jsx` | **The only way to render the logo in the web app.** Exports `SahilPayLogo` (mark + wordmark + optional slogan) and `SahilPayMark` (house only). `currentColor`-driven. |
| Mark SVG | `client/src/assets/logos/sahilpay-mark.svg` | Raw asset (imports, OG images, docs) |
| Full horizontal lockup | `client/src/assets/logos/sahilpay-logo-full.svg` | Marketing/print uses |
| Stacked lockup | `client/src/assets/logos/sahilpay-logo-stacked.svg` | Covers, splash screens |
| Favicon | `client/public/favicon.svg` | Already replaced (navy tile + white mark). Keep. |
| Server branding module | `server/services/branding.py` | Constants + `logo_mark_svg()`, `logo_lockup_html()`, `pdf_header_html()`, `pdf_footer_html()` for **all** PDFs/exports/emails |
| Android mark drawable | `copilot/app/src/main/res/drawable/ic_sahilpay_mark.xml` | Tintable vector for the Co-pilot app |

## 3. Sizing & usage rules (apply everywhere)

1. **Size by height only** — the component keeps its own aspect ratio. Navbars/sidebars:
   `h-8`–`h-9` desktop, `h-7` mobile. Never set width and height independently; never stretch.
2. **Below ~140px of available width, drop to `SahilPayMark`** (mark only, no text). This is
   the rule for collapsed sidebars, mobile top bars, and table/report headers on small screens.
3. **Slogan appears only when the logo renders ≥ 32px tall.** Smaller than that, use
   `withSlogan={false}` — the slogan becomes unreadable and wraps.
4. **Contrast:** white ink on `primary-900`/dark glass surfaces; `#0f0246` ink on white/light.
   The component inherits `currentColor`, so set a text colour class on the parent.
5. **Clear space** ≥ 0.5× mark height on all sides. Don't butt it against other elements.
6. **Alt text:** the component already carries `aria-label="Sahil Pay — Smart Rent Collection"`.
   Keep it; don't wrap in elements that hide it from the accessibility tree.
7. Landlord-facing documents (see §6.2) keep the **landlord's** letterhead as the primary
   header — Sahil Pay appears as the platform credit in the footer, never competing on top.

## 4. Fonts (do first — everything else depends on it)

In `client/index.html`, extend the existing Google Fonts request to include the wordmark font:

- Add `Cinzel:wght@500;600` (and `Montserrat:wght@400;500` if not covered by Inter) to the
  existing `fonts.googleapis.com/css2` link.
- Update the `<title>` to `Sahil Pay — Smart Rent Collection` and `<meta name="description">`
  to mention "Sahil Pay — smart rent collection for Kenyan landlords: M-Pesa rent payments,
  invoicing, tenant statements and reports."

## 5. Web app tasks (client/)

For each item: import `SahilPayLogo` / `SahilPayMark` from
`@/components/branding/SahilPayLogo` (adjust to the project's relative-import style — check
existing imports in the file being edited).

| # | Surface | File(s) | What to do |
|---|---|---|---|
| W1 | Public navbar | `client/src/features/public/components/PublicNavbar.jsx`, `client/src/components/Navbar.jsx` | Replace the current text brand (`Sahil<span>Pay</span>`) with `<SahilPayLogo withSlogan={false} className="h-8 md:h-9" />` linked to `/`. On `<sm` screens, mark only. |
| W2 | Public footer | `client/src/components/Footer.jsx` | Add the stacked or full lockup (white ink) at the top of the footer, plus a contact block: phone `0114 129 809`, `info@sahilpay.co.ke`, `sahilpay.co.ke`, Nairobi, Kenya. Slogan under the logo. |
| W3 | Auth navbar (login/register/OTP) | `client/src/features/auth/components/AuthNavbar.jsx` | Replace text brand with `<SahilPayLogo withSlogan={false} className="h-8" />`. |
| W4 | Landlord sidebar | `client/src/features/landlord/components/LandlordSidebar.jsx` | Logo at the top of the sidebar (white ink on dark). Expanded: `SahilPayLogo withSlogan={false}`; collapsed rail: `SahilPayMark`. |
| W5 | Admin sidebar | `client/src/features/admin/components/AdminSidebar.jsx` | Same treatment as W4. |
| W6 | Team-member sidebar | `client/src/features/teamMember/components/TeamMemberSidebar.jsx` | Same treatment as W4. |
| W7 | Affiliate sidebar | `client/src/features/affiliate/components/AffiliateSidebar.jsx` | Same treatment as W4. |
| W8 | Tenant navbar | `client/src/features/tenant/components/TenantNavbar.jsx` | `<SahilPayLogo withSlogan={false} className="h-7 sm:h-8" />`; mark-only under `sm`. |
| W9 | Auth pages hero side (if a brand panel exists on login/register) | `client/src/features/auth/**` | Use the stacked lockup **with** slogan (it's large enough there). |
| W10 | Onboarding welcome modal + tutorials hub | `client/src/features/landlord/tutorials/**`, welcome modal component | Mark (`SahilPayMark`) in the modal header; full logo on the hub page header. |
| W11 | On-screen report view | `client/src/features/landlord/reports/ReportView.jsx` | Small `SahilPayMark` + "Sahil Pay" caption in the report toolbar/header area so screenshots/prints of the screen are branded. Keep it subtle (h-6). |
| W12 | Loading / empty states that currently show a text brand | search `grep -rn "SahilPay" client/src` | Replace user-visible text brands with the component or the two-word "Sahil Pay". Do **not** rename code identifiers, API slices, or storage keys. |

**Mobile check for every W item:** at 360px wide the logo must not overflow, wrap, or push
menu buttons off-screen — that is what rule §3.2 (mark-only fallback) is for.

## 6. Generated documents (server/) — PDFs & exports

All server work routes through `server/services/branding.py`. Never inline brand strings.

### 6.1 Platform documents — full Sahil Pay letterhead
These are issued **by Sahil Pay itself**, so they carry the full brand header + footer:

| # | Document | File | What to do |
|---|---|---|---|
| S1 | Platform billing receipt / tax invoice (KRA) | `server/services/pdf_service.py` (`generate_billing_receipt_pdf` area, the block with `.brand`/"SahilPay" at ~line 139–153) | Replace the text-only `.brand` block with `branding.logo_lockup_html()`; append `branding.pdf_footer_html()` before `</body>`. Keep KRA fields untouched. |
| S2 | Affiliate statements / payout receipts | `server/services/pdf_service.py` (~line 213–228), `server/services/affiliate_report_service.py` | Same treatment as S1 ("Affiliate Program" as `document_label`). |
| S3 | Any other platform-issued PDF (subscription invoices, SMS credit receipts) | `server/routes/billing_routes.py` → whatever pdf functions they call | Header/footer via `branding.pdf_header_html(...)` / `pdf_footer_html()`. |

### 6.2 Landlord documents — landlord letterhead + Sahil Pay credit
Reports, tenant invoices, receipts, and statements are issued by the **landlord** to their
tenants. `server/services/report_builder.py` (letterhead at ~line 274–333) already renders the
landlord's `logo_url` + company details. Keep that. Add:

| # | Item | File | What to do |
|---|---|---|---|
| S4 | Platform credit footer on every landlord PDF | `server/services/report_builder.py`, `server/services/pdf_service.py` (invoice + receipt generators), `server/services/receipt_service.py` | Bottom of last page: small line `Generated by Sahil Pay · sahilpay.co.ke · 0114 129 809` with a 14px `branding.logo_mark_svg(color=BRAND_MUTED, size=14)` inline before the text. Subtle — muted grey, 9–10px. |
| S5 | Letterhead fallback | `server/services/report_builder.py` | When the landlord has **no** `logo_url`/company details, today the header is bare text. Keep landlord name primary, but render `branding.logo_mark_svg()` (24px, muted) beside the "generated" metadata so the document still looks finished. Do **not** put the full Sahil Pay lockup where a tenant would read it as the landlord's identity. |
| S6 | Excel exports | `server/services/export_service.py` | Last row of each sheet: `Generated by Sahil Pay — sahilpay.co.ke — info@sahilpay.co.ke` (muted style). Also set workbook properties `creator = "Sahil Pay"`. |

### 6.3 Emails

| # | Item | File | What to do |
|---|---|---|---|
| S7 | Email shell header/footer | `server/services/email_templates.py` (shell at ~line 138–174) | ⚠️ **Gmail/Outlook do not render SVG** — do not embed the SVG in emails. Keep a *styled-text* lockup: `SAHIL PAY` (serif stack `Georgia, 'Times New Roman', serif`, letter-spacing ≈ 0.14em) with `SMART RENT COLLECTION` under it (10px, letter-spacing 0.35em). Update the footer line to `Sahil Pay · Smart Rent Collection · Nairobi, Kenya · 0114 129 809 · info@sahilpay.co.ke`. Import contact constants from `services.branding`. |
| S8 | Sender name | `server/.env.example` + `server/config.py` default | `MAIL_DEFAULT_SENDER_NAME` default → `Sahil Pay`. |

## 7. Co-pilot Android app (copilot/)

The tintable mark already exists: `res/drawable/ic_sahilpay_mark.xml`.

| # | Item | File | What to do |
|---|---|---|---|
| C1 | Launcher icon | `res/drawable/ic_launcher_foreground.xml`, `ic_launcher_background.xml`, `mipmap-anydpi*/ic_launcher*.xml` | Foreground = white house mark (reuse the paths from `ic_sahilpay_mark.xml`, scaled into the 108dp adaptive-icon safe zone — keep artwork within the centre 66dp). Background = solid `#0f0246`. |
| C2 | App name | `res/values/strings.xml` | Keep `app_name` = `Co-pilot`; ensure `app_name_full` = `Co-pilot — by Sahil Pay` is what pairing/settings screens display. |
| C3 | In-app branding | `ui/screens/pairing/PairingScreen.kt`, `home/HomeScreen.kt`, `settings/SettingsScreen.kt` | Pairing screen: mark (72dp, tinted to theme ink) above the title, with `SAHIL PAY` wordmark text (serif, letter-spaced) and `SMART RENT COLLECTION` (10sp, letter-spaced) beneath. Home top bar: 28dp mark leading the title. Settings "About" row: mark + `Sahil Pay · sahilpay.co.ke · 0114 129 809`. |
| C4 | Theme ink | `ui/theme/Color.kt` | Ensure a brand navy `0xFF0F0246` exists and the mark is tinted with theme ink (white in dark theme). |

## 8. Order of execution

1. §4 fonts + `index.html` (everything visual depends on Cinzel being available).
2. §5 web surfaces W1→W12 (verify each in the browser at desktop + 360px mobile width).
3. §6 server documents (regenerate one sample of each PDF type + one Excel export to verify).
4. §7 Co-pilot (build not required locally; XML/Kotlin edits must at least be lint-clean).

## 9. QA checklist (must all pass before done)

- [ ] Every portal (public, auth, landlord, team, tenant, admin, affiliate) shows the logo in its nav/sidebar, correct ink for the surface.
- [ ] 360px-wide viewport: no logo overflow/wrap anywhere; mark-only fallbacks engage.
- [ ] Collapsed sidebar rails show the mark, not a squashed lockup.
- [ ] Favicon shows the navy tile + white mark in the browser tab.
- [ ] Billing receipt PDF: full lockup header + branded footer; KRA fields intact.
- [ ] A landlord report PDF: landlord letterhead untouched on top, "Generated by Sahil Pay" credit at bottom.
- [ ] Tenant invoice + receipt PDFs carry the platform credit footer.
- [ ] Excel export has the credit row + `creator` property.
- [ ] An OTP email renders correctly in Gmail (text lockup, no SVG, contact footer with 0114 129 809 / info@sahilpay.co.ke).
- [ ] `grep -rn "SahilPay" client/src --include="*.jsx"` shows no remaining *user-visible* one-word text brands (code identifiers are fine).
- [ ] Co-pilot: launcher icon, pairing screen, home top bar, settings about row all branded.
