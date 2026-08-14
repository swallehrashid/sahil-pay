/**
 * recovery-check.mjs — drive the features that the interrupted session left
 * half-wired, and prove they actually work rather than merely render.
 *
 * walkthrough.mjs loads pages. This one presses the things a user presses:
 * it opens a help article from the list, follows the dashboard's eTIMS nudge
 * link, and takes an unenrolled admin through the start of 2FA enrolment —
 * the three paths that were broken or unreachable.
 *
 * Requires the dev estate:
 *   APP_ENV=development venv/bin/python seed.py
 *   APP_ENV=development venv/bin/python seed_tutorials.py
 *   APP_ENV=development venv/bin/python seed_dev_extras.py
 *
 *   node scripts/recovery-check.mjs [--base URL] [--out DIR]
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
const OUT = argOf("--out", "./recovery-check");
const TENANT_TOKEN = process.env.TENANT_TOKEN;

const LANDLORD = { email: "landlord@sahilpay.test", password: "Landlord@123" };
const ADMIN = { email: "admin@sahilpay.test", password: "Admin@123" };

// The article the dashboard nudge and the tax-compliance settings page both
// deep-link to. Until the Suspense fix these links landed on an error boundary.
const NUDGE_SLUG = "how-rental-taxes-work-in-kenya-the-basics";

const results = [];

function check(name, passed, detail = "") {
  results.push({ name, passed, detail });
  console.log(`[${passed ? "  ok  " : " FAIL "}] ${name}${detail ? ` — ${detail}` : ""}`);
}

async function shot(page, name) {
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
}

async function login(page, { email, password }) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(2500);
  return !page.url().includes("/login");
}

async function dismissTour(page) {
  try {
    const skip = page.getByRole("button", { name: /skip for now|explore on my own/i });
    if (await skip.isVisible({ timeout: 1200 })) await skip.click();
  } catch { /* not showing */ }
  await page.waitForTimeout(300);
}

/** Text of every sidebar/nav link on the page. */
async function navLabels(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll("nav a, aside a")].map((a) => a.textContent.trim())
  );
}

async function run() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();

  // =======================================================================
  // Landlord — navigation, help library, eTIMS
  // =======================================================================
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
    const page = await ctx.newPage();

    const signedIn = await login(page, LANDLORD);
    check("landlord signs in", signedIn, page.url());
    await dismissTour(page);

    // --- Nav wiring -----------------------------------------------------
    await page.goto(`${BASE}/landlord/dashboard`, { waitUntil: "networkidle" });
    await dismissTour(page);
    const labels = await navLabels(page);
    const has = (t) => labels.some((l) => l.toLowerCase().includes(t));

    check("nav shows Guides (help library)", has("guides"));
    check("nav shows Review queue", has("review queue"));
    check("nav shows Payout runs", has("payout runs"));
    // eTIMS links are conditional on /api/etims/scope reporting an enabled
    // property — seed_dev_extras.py switches this account on.
    check("nav shows eTIMS Register (scope-gated)", has("etims register"));
    check("nav shows KRA Monthly Report (scope-gated)", has("kra monthly"));

    // --- The dashboard nudge's deep link --------------------------------
    // This is the link that used to die: HelpPage was lazy and mounted with no
    // Suspense boundary, so following it threw into the error boundary.
    await page.goto(`${BASE}/landlord/help/${NUDGE_SLUG}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    const articleText = await page.evaluate(() => document.body.innerText);
    check(
      "deep-linked help article renders",
      /rental tax/i.test(articleText) && !/something went wrong/i.test(articleText),
      `${articleText.length} chars`
    );
    check(
      "article carries the CMS disclaimer footer",
      /not tax advice/i.test(articleText)
    );
    await shot(page, "landlord-help-article");

    // --- Opening an article from the list --------------------------------
    await page.goto(`${BASE}/landlord/help`, { waitUntil: "networkidle" });
    await page.waitForTimeout(900);
    const firstArticle = page.locator("a", { hasText: /rental taxes work/i }).first();
    const clickable = await firstArticle.count();
    if (clickable) {
      await firstArticle.click();
      await page.waitForTimeout(1400);
      check("clicking an article from the list opens it",
            /\/landlord\/help\//.test(page.url()), page.url());
    } else {
      check("clicking an article from the list opens it", false, "no article link found");
    }

    // --- eTIMS surfaces ---------------------------------------------------
    await page.goto(`${BASE}/landlord/etims-register`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    const registerText = await page.evaluate(() => document.body.innerText);
    check("eTIMS register renders for an enabled account",
          registerText.length > 200 && !/something went wrong/i.test(registerText),
          `${registerText.length} chars`);
    await shot(page, "landlord-etims-register");

    await page.goto(`${BASE}/landlord/reports/kra-monthly`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1400);
    const kraText = await page.evaluate(() => document.body.innerText);
    check("KRA monthly report renders",
          kraText.length > 200 && !/something went wrong/i.test(kraText),
          `${kraText.length} chars`);
    await shot(page, "landlord-kra-monthly");

    // --- Allocation surfaces ---------------------------------------------
    for (const [name, url] of [
      ["review queue", "/landlord/payments/review-queue"],
      ["payout runs", "/landlord/payouts"],
      ["allocation settings", "/landlord/settings/allocation"],
    ]) {
      await page.goto(`${BASE}${url}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(1100);
      const text = await page.evaluate(() => document.body.innerText);
      check(`${name} renders`, text.length > 150 && !/something went wrong/i.test(text),
            `${text.length} chars`);
    }

    await ctx.close();
  }

  // =======================================================================
  // Admin — the 2FA enrolment that had no screen
  // =======================================================================
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await ctx.newPage();

    await login(page, ADMIN);
    const landed = new URL(page.url()).pathname;
    check("unenrolled admin is routed to 2FA enrolment",
          landed === "/two-factor-setup", landed);

    // Start enrolment: the server must hand back a secret and a provisioning
    // URI, and the page must draw the QR locally (never via an image service —
    // that would post the secret to a third party).
    const start = page.getByRole("button", { name: /get started/i });
    if (await start.count()) {
      await start.click();
      await page.waitForTimeout(2000);
      const state = await page.evaluate(() => ({
        text: document.body.innerText,
        hasSvgQr: Boolean(document.querySelector("svg")),
        externalImg: [...document.querySelectorAll("img")]
          .map((i) => i.src)
          .filter((s) => /^https?:\/\//.test(s) && !s.startsWith(location.origin)),
      }));
      check("enrolment returns a secret to type in",
            /can't scan|enter this key/i.test(state.text));
      check("QR is rendered locally as SVG", state.hasSvgQr);
      check("secret is never sent to a third-party image service",
            state.externalImg.length === 0, state.externalImg.join(", "));
      check("enrolment asks for the 6-digit code",
            /6-digit code/i.test(state.text));
      await shot(page, "admin-2fa-enrolment");
    } else {
      check("enrolment returns a secret to type in", false, "no Get started button");
    }

    await ctx.close();
  }

  // =======================================================================
  // Tenant — the audience whose articles had no reader at all
  // =======================================================================
  if (TENANT_TOKEN) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.evaluate((t) => localStorage.setItem("sahilpay_access_token", t), TENANT_TOKEN);

    await page.goto(`${BASE}/portal/help`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1400);
    const listText = await page.evaluate(() => document.body.innerText);
    check("tenant sees the help library", /tax compliance/i.test(listText),
          `${listText.length} chars`);
    check("tenant sees the tenant-specific article",
          /for tenants/i.test(listText));
    // Role filtering: landlord-only material must not be on a tenant's shelf.
    check("tenant does NOT see landlord-only articles",
          !/for landlords/i.test(listText));

    const tenantArticle = page.locator("a", { hasText: /for tenants/i }).first();
    if (await tenantArticle.count()) {
      await tenantArticle.click();
      await page.waitForTimeout(1400);
      const body = await page.evaluate(() => document.body.innerText);
      check("tenant can open their article",
            /kra pin|receipt/i.test(body) && !/something went wrong/i.test(body),
            `${body.length} chars`);
      await shot(page, "tenant-help-article");
    } else {
      check("tenant can open their article", false, "article link not found");
    }

    await ctx.close();
  } else {
    console.log("\n(TENANT_TOKEN not set — skipping the tenant portal checks)\n");
  }

  await browser.close();

  await writeFile(path.join(OUT, "results.json"), JSON.stringify(results, null, 2));
  const failed = results.filter((r) => !r.passed);
  console.log(`\n${"=".repeat(72)}`);
  console.log(`Checks: ${results.length}   Passed: ${results.length - failed.length}   Failed: ${failed.length}`);
  if (failed.length) {
    console.log("\nFAILED:");
    for (const f of failed) console.log(`  ${f.name}${f.detail ? ` — ${f.detail}` : ""}`);
  }
  console.log(`\nScreenshots in ${path.resolve(OUT)}`);
  process.exit(failed.length ? 1 : 0);
}

run().catch((err) => {
  console.error("recovery-check crashed:", err);
  process.exit(2);
});
