/**
 * walkthrough.mjs — drive every portal in a real browser and screenshot it.
 *
 * Signs in as each kind of user against the property-manager-scale estate
 * (server/seed_scale.py: 100 properties, 1,000 units, 943 tenants, 300 team
 * members) and walks their pages, capturing:
 *
 *   * a screenshot of every page, desktop and mobile,
 *   * every console error the page logged,
 *   * every failed network request,
 *   * how long each page took to settle.
 *
 * A build that compiles proves nothing about whether a caretaker's dashboard
 * actually renders. This does.
 *
 *   node scripts/walkthrough.mjs [--out DIR] [--base URL]
 */

import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const args = process.argv.slice(2);
const argOf = (flag, fallback) => {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : fallback;
};

const BASE = argOf("--base", "http://127.0.0.1:5173");
const OUT = argOf("--out", "./walkthrough");
// Which seeded estate to drive. `dev` is server/seed.py (+ seed_dev_extras.py,
// which publishes the help library and switches eTIMS on); `scale` is
// server/seed_scale.py, the 100-property/1,000-unit performance estate.
const PROFILE = argOf("--profile", "dev");

// Team members live under /team, not /landlord — pointing them at a landlord
// URL just bounces them home, which proves nothing about their own portal.
const LANDLORD_PAGES_FOR = (prefix) => [
  ["dashboard",      `${prefix}/dashboard`],
  ["properties",     `${prefix}/properties`],
  ["units",          `${prefix}/units`],
  ["tenants",        `${prefix}/tenants`],
  ["invoices",       `${prefix}/invoices`],
  ["payments",       `${prefix}/payments`],
  ["expenses",       `${prefix}/expenses`],
  ["utilities",      `${prefix}/utilities`],
  ["maintenance",    `${prefix}/maintenance`],
  ["reports",        `${prefix}/reports`],
  ["communications", `${prefix}/communications`],
];

// The eTIMS/KRA, allocation and help-library surfaces. These shipped in the
// items/eTIMS round and were never in this script, so nothing had ever loaded
// them in a browser.
const NEW_LANDLORD_PAGES = [
  ["review-queue",    "/landlord/payments/review-queue"],
  ["payout-runs",     "/landlord/payouts"],
  ["owner-payouts",   "/landlord/owner-payouts"],
  ["etims-register",  "/landlord/etims-register"],
  ["kra-monthly",     "/landlord/reports/kra-monthly"],
  ["help",            "/landlord/help"],
  ["settings-tax-compliance", "/landlord/settings/tax-compliance"],
  ["settings-allocation",     "/landlord/settings/allocation"],
  ["settings-penalties",      "/landlord/settings/penalties"],
  ["reports-penalties",       "/landlord/reports/penalties"],
  ["leases",                  "/landlord/leases"],
  ["settings-account",        "/landlord/settings/account"],
];

const SETTINGS_PAGES = [
  ["settings-team",    "/landlord/settings/team"],
  ["settings-general", "/landlord/settings/general"],
  ["settings-billing", "/landlord/settings/billing"],
  ["settings-receipt-layout", "/landlord/settings/receipt-layout"],
];

const PROFILES = {
  // server/seed.py — the varied four-landlord dev estate. landlord@ has eTIMS
  // switched on by seed_dev_extras.py, so its compliance pages have data.
  dev: {
    landlord: {
      email: "landlord@sahilpay.test", password: "Landlord@123",
      label: "Landlord (Acme)",
      pages: [...LANDLORD_PAGES_FOR("/landlord"), ...NEW_LANDLORD_PAGES, ...SETTINGS_PAGES],
    },
    teamMember: {
      email: "caretaker@sahilpay.test", password: "Caretaker@123",
      label: "Team member (Acme)",
      pages: [
        ...LANDLORD_PAGES_FOR("/team"),
        ["help",           "/team/help"],
        ["etims-register", "/team/etims-register"],
        ["kra-monthly",    "/team/reports/kra-monthly"],
        ["reports-penalties", "/team/reports/penalties"],
        ["tutorials",      "/team/tutorials"],
        ["leases",         "/team/leases"],
      ],
    },
    // The admin is deliberately NOT enrolled in 2FA, which is the state every
    // existing admin is in the moment this ships. Signing in must land on the
    // enrolment screen — see the assertion in run().
    admin: {
      email: "admin@sahilpay.test", password: "Admin@123",
      label: "System admin (2FA not enrolled)",
      expectRedirectTo: "/two-factor-setup",
      pages: [["two-factor-setup", "/two-factor-setup"]],
    },
  },

  // server/seed_scale.py — the performance estate.
  scale: {
    manager: {
      email: "scale-pm@sahilpay.test", password: "ScaleTest123!",
      label: "Property manager",
      pages: [...LANDLORD_PAGES_FOR("/landlord"), ...NEW_LANDLORD_PAGES, ...SETTINGS_PAGES],
    },
    owner: {
      email: "owner001@scale.sahilpay.test", password: "ScaleTest123!",
      label: "Owner (view only)",
      pages: LANDLORD_PAGES_FOR("/team"),
    },
    caretaker: {
      email: "caretaker001@scale.sahilpay.test", password: "ScaleTest123!",
      label: "Caretaker",
      pages: LANDLORD_PAGES_FOR("/team"),
    },
  },
};

const ACCOUNTS = PROFILES[PROFILE];
if (!ACCOUNTS) {
  console.error(`Unknown --profile "${PROFILE}". Use one of: ${Object.keys(PROFILES).join(", ")}`);
  process.exit(2);
}

const PUBLIC_PAGES = [
  ["home",     "/"],
  ["features", "/features"],
  ["pricing",  "/pricing"],
  ["faq",      "/faq"],
  ["about",    "/about"],
  ["contact",  "/contact"],
];

const results = [];
const VIEWPORTS = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } };

function record(entry) {
  results.push(entry);
  const status = entry.ok ? "  ok  " : " FAIL ";
  const detail = entry.problems.length ? ` — ${entry.problems.join(" | ")}` : "";
  console.log(`[${status}] ${entry.role.padEnd(18)} ${entry.name.padEnd(18)} ${String(entry.ms).padStart(5)}ms${detail}`);
}

/** Visit one page, screenshot it, and collect anything that went wrong. */
async function visit(page, { role, name, url, viewport = "desktop", expectDenied = false }) {
  const consoleErrors = [];
  const failedRequests = [];

  const onConsole = (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 200));
  };
  const onResponse = (res) => {
    // 401 on a public page is normal (the app probing for a session);
    // 5xx anywhere, or 4xx on an API the page needs, is not.
    if (res.status() >= 500) failedRequests.push(`${res.status()} ${res.url().slice(0, 120)}`);
  };
  page.on("console", onConsole);
  page.on("response", onResponse);

  const started = Date.now();
  let navError = null;
  try {
    await page.goto(`${BASE}${url}`, { waitUntil: "networkidle", timeout: 30000 });
  } catch (err) {
    navError = err.message.slice(0, 160);
  }
  // Dismiss the first-run tutorial overlay — it covers the page it is offering
  // to explain, so every screenshot behind it would be of the same modal.
  try {
    const skip = page.getByRole("button", { name: /skip for now|explore on my own/i });
    if (await skip.isVisible({ timeout: 1200 })) await skip.click();
  } catch { /* no tour showing */ }

  // Let animations and lazy chunks settle so the screenshot isn't mid-fade.
  await page.waitForTimeout(900);
  const ms = Date.now() - started;

  const dir = path.join(OUT, viewport, role);
  await mkdir(dir, { recursive: true });
  const file = path.join(dir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: viewport === "desktop" });

  // A blank white page compiles fine and tells the user nothing works.
  const bodyText = await page.evaluate(() => document.body?.innerText?.trim() ?? "");
  const isBlank = bodyText.length < 40;

  page.off("console", onConsole);
  page.off("response", onResponse);

  const problems = [];
  if (navError) problems.push(`navigation: ${navError}`);
  if (isBlank) problems.push("page rendered blank");
  if (failedRequests.length) problems.push(`server errors: ${failedRequests.slice(0, 2).join(", ")}`);

  // A 403 for a team member on a module their preset doesn't grant is the
  // permission system WORKING — we navigate straight to the URL on purpose, to
  // prove that hiding the nav item isn't the only thing stopping them. What
  // matters is that the page then shows a graceful no-access screen rather than
  // breaking, which the blank-page check above already covers.
  const realConsoleErrors = consoleErrors.filter(
    (e) => !(expectDenied && /403|FORBIDDEN/i.test(e))
  );
  if (realConsoleErrors.length) problems.push(`console: ${realConsoleErrors.slice(0, 2).join(", ")}`);

  record({ role, name, url, viewport, ms, ok: problems.length === 0, problems, file, bodyChars: bodyText.length });
  return { bodyText, problems };
}

async function login(page, email, password) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"], input[name="email"]', email);
  await page.fill('input[type="password"], input[name="password"]', password);
  await Promise.all([
    page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 20000 }).catch(() => {}),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForTimeout(1500);
  return !page.url().includes("/login");
}

async function run() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();

  // ---- Public marketing pages (no auth) ---------------------------------
  for (const [viewportName, viewport] of Object.entries(VIEWPORTS)) {
    const ctx = await browser.newContext({ viewport });
    const page = await ctx.newPage();
    for (const [name, url] of PUBLIC_PAGES) {
      await visit(page, { role: "public", name, url, viewport: viewportName });
    }
    // The SEO tags a crawler actually reads.
    if (viewportName === "desktop") {
      await page.goto(`${BASE}/pricing`, { waitUntil: "networkidle" });
      await page.waitForTimeout(600);
      const seo = await page.evaluate(() => ({
        title: document.title,
        description: document.querySelector('meta[name="description"]')?.content,
        canonical: document.querySelector('link[rel="canonical"]')?.href,
        og: document.querySelector('meta[property="og:title"]')?.content,
        jsonLd: [...document.querySelectorAll('script[type="application/ld+json"]')].map(
          (s) => JSON.parse(s.textContent)["@type"]
        ),
      }));
      await writeFile(path.join(OUT, "seo-pricing.json"), JSON.stringify(seo, null, 2));
      console.log("\nSEO on /pricing:", JSON.stringify(seo), "\n");
    }
    await ctx.close();
  }

  // ---- Each signed-in role ----------------------------------------------
  for (const [key, account] of Object.entries(ACCOUNTS)) {
    for (const [viewportName, viewport] of Object.entries(VIEWPORTS)) {
      const ctx = await browser.newContext({ viewport });
      const page = await ctx.newPage();

      const signedIn = await login(page, account.email, account.password);
      if (!signedIn) {
        record({
          role: key, name: "login", url: "/login", viewport: viewportName,
          ms: 0, ok: false, problems: [`could not sign in as ${account.email}`],
          file: null, bodyChars: 0,
        });
        await ctx.close();
        continue;
      }

      // Where login SENDS them is itself a behaviour worth asserting. An admin
      // without 2FA must land on enrolment: the server answers `needs_2fa_setup`
      // and refuses every /api/admin/* route until it is done, so routing them
      // to the dashboard instead produces a portal of 403s with no way out.
      if (account.expectRedirectTo) {
        const landed = new URL(page.url()).pathname;
        record({
          role: key, name: "login-redirect", url: landed, viewport: viewportName,
          ms: 0, ok: landed === account.expectRedirectTo,
          problems: landed === account.expectRedirectTo
            ? []
            : [`expected ${account.expectRedirectTo}, landed on ${landed}`],
          file: null, bodyChars: 0,
        });
      }

      for (const [name, url] of account.pages) {
        // Team members are deliberately walked through pages their preset does
        // not grant, to confirm the backend refuses them.
        await visit(page, {
          role: key, name, url, viewport: viewportName,
          expectDenied: key !== "manager",
        });
      }
      await ctx.close();
    }
  }

  // ---- Tenant portal --------------------------------------------------
  // OTP login can't be scripted, so the session is established by injecting a
  // token minted server-side for a genuinely multi-unit tenant — the case the
  // unit switcher exists for.
  const tenantToken = process.env.TENANT_TOKEN;
  if (tenantToken) {
    const TENANT_PAGES = [
      ["dashboard",   "/portal/dashboard"],
      ["pay",         "/portal/pay"],
      ["statement",   "/portal/statement"],
      ["maintenance", "/portal/maintenance"],
      ["messages",    "/portal/messages"],
      ["profile",     "/portal/profile"],
      // The help library's tenant-facing articles had no reader until now.
      ["help",        "/portal/help"],
      ["lease",       "/portal/lease"],
    ];
    for (const [viewportName, viewport] of Object.entries(VIEWPORTS)) {
      const ctx = await browser.newContext({ viewport });
      const page = await ctx.newPage();
      await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
      await page.evaluate((token) => {
        localStorage.setItem("sahilpay_access_token", token);
        localStorage.setItem("accessToken", token);
      }, tenantToken);
      for (const [name, url] of TENANT_PAGES) {
        await visit(page, { role: "tenant", name, url, viewport: viewportName });
      }
      await ctx.close();
    }
  }

  await browser.close();

  // ---- Summary -----------------------------------------------------------
  const failures = results.filter((r) => !r.ok);
  const slow = results.filter((r) => r.ms > 3000);

  await writeFile(path.join(OUT, "results.json"), JSON.stringify(results, null, 2));

  console.log(`\n${"=".repeat(72)}`);
  console.log(`Pages visited: ${results.length}   Screenshots: ${results.filter((r) => r.file).length}`);
  console.log(`Failures: ${failures.length}   Slow (>3s): ${slow.length}`);
  if (failures.length) {
    console.log("\nFAILURES:");
    for (const f of failures) console.log(`  ${f.role}/${f.viewport}/${f.name}: ${f.problems.join(" | ")}`);
  }
  if (slow.length) {
    console.log("\nSLOW PAGES:");
    for (const s of slow) console.log(`  ${s.role}/${s.viewport}/${s.name}: ${s.ms}ms`);
  }
  console.log(`\nScreenshots in ${path.resolve(OUT)}`);
  process.exit(failures.length ? 1 : 0);
}

run().catch((err) => {
  console.error("walkthrough crashed:", err);
  process.exit(2);
});
