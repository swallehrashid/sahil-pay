/**
 * walkthrough.mjs — end-to-end click-through of the SahilPay portals.
 *
 * Drives a real browser against the local stack (Vite 5173, Flask 5000) at TWO
 * viewports, because "mobile-first" is a claim that has to be measured:
 *
 *   mobile   390 x 844   (iPhone 12/13/14 class — the Kenyan field default)
 *   desktop  1440 x 900
 *
 * For every page it checks three things:
 *   1. it renders (no error boundary, no uncaught page error);
 *   2. THE PAGE BODY DOES NOT SCROLL SIDEWAYS — the single most reliable
 *      signal that a layout is not actually mobile-first. A dense financial
 *      table dumped straight into a phone viewport fails here;
 *   3. no forbidden compliance wording leaks into the UI.
 *
 * Then it walks the KRA/eTIMS opt-in journey end to end for two very different
 * accounts: the huge property manager and a small self-managing landlord.
 *
 *   node walkthrough.mjs
 */

import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const WEB = "http://localhost:5173";
const SHOTS = process.env.SHOT_DIR || "/tmp/sahilpay-walkthrough";
mkdirSync(SHOTS, { recursive: true });

// Mobile FIRST — the narrower viewport is the one the layouts are designed
// around, so it is the one that must pass before the desktop check matters.
const VIEWPORTS = {
  mobile: { width: 390, height: 844 },    // iPhone 12/13/14 class
  desktop: { width: 1440, height: 900 },
};

const results = [];
let shotIndex = 0;

function record(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

async function shot(page, label) {
  const file = `${SHOTS}/${String(++shotIndex).padStart(3, "0")}-${label}.png`;
  await page.screenshot({ path: file }).catch(() => {});
}

async function login(page, email, password) {
  await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[type="email"], input[name="email"]', email);
  await page.fill('input[type="password"], input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 25000 });
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function logout(page) {
  await page.evaluate(() => window.localStorage.clear()).catch(() => {});
  await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
}

/**
 * Does the document scroll horizontally? A few px of slop absorbs subpixel
 * rounding; anything more is a real overflow a user would feel.
 */
async function horizontalOverflow(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const overflow = doc.scrollWidth - doc.clientWidth;
    if (overflow <= 2) return null;
    // Name the widest offender so the failure is actionable rather than "somewhere".
    let worst = null;
    for (const el of document.querySelectorAll("body *")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0) continue;
      const past = Math.round(r.right - doc.clientWidth);
      if (past > 2 && (!worst || past > worst.past)) {
        worst = {
          past,
          tag: el.tagName.toLowerCase(),
          cls: (el.className?.toString?.() ?? "").slice(0, 70),
        };
      }
    }
    return { overflow, worst };
  });
}

const BANNED = ["non-compliant", "noncompliant", "overdue", "violation"];

async function visit(page, label, path, { expect = [], viewport } = {}) {
  const pageErrors = [];
  const onPageError = (err) => pageErrors.push(err.message);
  page.on("pageerror", onPageError);

  try {
    await page.goto(`${WEB}${path}`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(350);

    const body = (await page.textContent("body")) ?? "";
    const crashed = /Something went wrong|Unexpected Application Error/i.test(body);
    const missing = expect.filter((t) => !body.includes(t));
    const banned = BANNED.filter((w) => body.toLowerCase().includes(w));
    const overflow = await horizontalOverflow(page);

    const problems = [
      crashed && "error boundary",
      missing.length && `missing: ${missing.join(", ")}`,
      banned.length && `forbidden wording: ${banned.join(", ")}`,
      overflow && `scrolls sideways by ${overflow.overflow}px (${overflow.worst?.tag}.${overflow.worst?.cls})`,
      pageErrors.length && `page error: ${pageErrors[0].split("\n")[0]}`,
    ].filter(Boolean);

    record(`[${viewport}] ${label}`, problems.length === 0, problems.join("; "));
    if (problems.length) await shot(page, `${viewport}-FAIL-${label}`.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
    return { ok: !problems.length, body };
  } catch (err) {
    record(`[${viewport}] ${label}`, false, err.message.split("\n")[0]);
    return { ok: false, body: "" };
  } finally {
    page.off("pageerror", onPageError);
  }
}

const LANDLORD_PAGES = [
  ["Dashboard", "/landlord/dashboard"],
  ["Properties", "/landlord/properties"],
  ["Units", "/landlord/units"],
  ["Tenants", "/landlord/tenants"],
  ["Invoices", "/landlord/invoices"],
  ["Payments", "/landlord/payments"],
  ["Owner payouts", "/landlord/owner-payouts"],
  ["Expenses", "/landlord/expenses"],
  ["Utilities", "/landlord/utilities"],
  ["Maintenance", "/landlord/maintenance"],
  ["Property groups", "/landlord/groups"],
  ["Reports statements", "/landlord/reports/statements"],
  ["Reports insights", "/landlord/reports/insights"],
  ["Communications", "/landlord/communications"],
  ["Tenant messages", "/landlord/messages"],
  ["Notifications", "/landlord/notifications"],
  ["Settings general", "/landlord/settings/general"],
  ["Settings account", "/landlord/settings/account"],
  ["Settings team", "/landlord/settings/team"],
  ["Settings billing", "/landlord/settings/billing"],
  ["Settings audit", "/landlord/settings/audit"],
  ["Settings tax compliance", "/landlord/settings/tax-compliance"],
  ["Help & Tutorials", "/landlord/help"],
  // Payment allocation engine (sahilpay_payment_allocation_spec.md).
  ["Review queue", "/landlord/payments/review-queue"],
  ["Payouts", "/landlord/payouts"],
  ["Settings payments & commission", "/landlord/settings/allocation"],
];

const ADMIN_PAGES = [
  ["Admin dashboard", "/admin/dashboard"],
  ["Admin landlords", "/admin/landlords"],
  ["Admin help content", "/admin/help-content"],
];

async function walkAccount(page, viewport, { label, email, password, optIn }) {
  console.log(`\n--- [${viewport}] ${label} (${email}) ---`);
  await login(page, email, password);
  record(`[${viewport}] ${label}: sign in`, true);

  for (const [name, path] of LANDLORD_PAGES) {
    await visit(page, `${label}: ${name}`, path, { viewport });
  }

  if (optIn) {
    // Opt in, then confirm the two gated pages appear and work.
    await page.goto(`${WEB}/landlord/settings/tax-compliance`, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});

    const enable = page.getByRole("button", { name: "Enable", exact: true });
    if (await enable.count()) await enable.first().click({ force: true, timeout: 10000 });

    const off = page.getByRole("button", { name: "Off", exact: true });
    try {
      await off.first().waitFor({ state: "attached", timeout: 15000 });
      await off.first().click({ force: true, timeout: 10000 });
      await page.getByRole("button", { name: "On", exact: true })
        .first().waitFor({ state: "attached", timeout: 15000 });
      record(`[${viewport}] ${label}: opt a property into eTIMS`, true);
    } catch {
      const on = await page.getByRole("button", { name: "On", exact: true }).count();
      record(`[${viewport}] ${label}: opt a property into eTIMS`, on > 0,
             on > 0 ? "already enabled" : "no property toggle");
    }
    await shot(page, `${viewport}-${label}-tax-compliance`.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
  }

  await visit(page, `${label}: eTIMS Register`, "/landlord/etims-register",
              { expect: ["eTIMS Register"], viewport });
  await visit(page, `${label}: KRA Monthly Report`, "/landlord/reports/kra-monthly",
              { expect: ["KRA Monthly Report"], viewport });

  await logout(page);
}

async function walkAdmin(page, viewport) {
  console.log(`\n--- [${viewport}] Admin ---`);
  // The admin portal demands an enrolled second factor, so an unenrolled admin
  // is correctly bounced. Record whichever happened rather than pretending.
  try {
    await login(page, "admin@sahilpay.test", "Admin@123");
  } catch {
    record(`[${viewport}] Admin: sign in`, false, "could not sign in (2FA gate or credentials)");
    return;
  }
  record(`[${viewport}] Admin: sign in`, true);
  for (const [name, path] of ADMIN_PAGES) {
    await visit(page, name, path, { viewport });
  }
  await logout(page);
}

const run = async () => {
  const browser = await chromium.launch({ headless: true });

  try {
    for (const [viewport, size] of Object.entries(VIEWPORTS)) {
      console.log(`\n================ ${viewport.toUpperCase()} ${size.width}x${size.height} ================`);
      const context = await browser.newContext({ viewport: size, deviceScaleFactor: 1 });
      const page = await context.newPage();

      await walkAccount(page, viewport, {
        label: "PM", email: "scale-pm@sahilpay.test", password: "ScaleTest123!", optIn: true,
      });
      await walkAccount(page, viewport, {
        label: "Landlord", email: "landlord@sahilpay.test", password: "Landlord@123", optIn: true,
      });
      await walkAdmin(page, viewport);

      await context.close();
    }
  } catch (err) {
    console.log("\nWALKTHROUGH ABORTED:", err.stack?.split("\n").slice(0, 6).join("\n"));
  } finally {
    const failed = results.filter((r) => !r.ok);
    console.log(`\n=== ${results.length - failed.length}/${results.length} checks passed ===`);
    if (failed.length) {
      console.log("\nFailures:");
      failed.forEach((f) => console.log(`  - ${f.name}: ${f.detail}`));
    }
    writeFileSync(`${SHOTS}/results.json`, JSON.stringify({ results }, null, 2));
    console.log(`\nScreenshots + results.json in ${SHOTS}`);
    await browser.close();
    process.exit(failed.length ? 1 : 0);
  }
};

run();
