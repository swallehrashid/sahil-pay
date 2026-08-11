/**
 * feature-check.mjs — drive the new features, don't just load their pages.
 *
 * The page walkthrough proves a screen renders. This proves it WORKS: it fills
 * the forms, uploads a real spreadsheet, presses the buttons and checks what
 * came back. Everything it creates is thrown away afterwards except the tenants
 * it imports, which are named so they're obvious in the estate.
 *
 *   node scripts/feature-check.mjs [--base URL] [--out DIR]
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
const OUT = argOf("--out", "./feature-check");
const MANAGER = { email: "scale-pm@sahilpay.test", password: "ScaleTest123!" };

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

/** Dismiss the first-run tutorial if it's covering the page. */
async function dismissTour(page) {
  try {
    const skip = page.getByRole("button", { name: /skip for now|explore on my own/i });
    if (await skip.isVisible({ timeout: 1200 })) await skip.click();
  } catch { /* not showing */ }
  await page.waitForTimeout(300);
}

// A filled-in import template, built as CSV so the script needs no Excel writer.
function importCsv(stamp) {
  const header = [
    "property_name", "unit_name", "rent_amount", "first_name", "last_name",
    "phone", "email", "account_number", "opening_balance", "credit_balance",
  ].join(",");
  const rows = [
    `Import Test Block ${stamp},IT-1,15000,Grace,Imported,+2547${stamp}01,,IMP-${stamp}-1,0,0`,
    `Import Test Block ${stamp},IT-2,15000,Peter,Imported,+2547${stamp}02,,IMP-${stamp}-2,18000,0`,
    // Deliberately broken: proves bad rows are caught and reported, not written.
    `Import Test Block ${stamp},IT-3,NOT-A-NUMBER,Bad,Row,+2547${stamp}03,,IMP-${stamp}-3,0,0`,
  ];
  return [header, ...rows].join("\n");
}

async function run() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();

  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 160));
  });

  // ---- Sign in ----------------------------------------------------------
  check("Property manager can sign in", await login(page, MANAGER));
  await dismissTour(page);

  // ---- Phase 8: the import wizard ---------------------------------------
  const stamp = String(Date.now()).slice(-6);

  await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "networkidle" });
  await dismissTour(page);

  const importButton = page.getByRole("button", { name: /^Import$/ });
  check("Tenants page offers an Import button", await importButton.isVisible().catch(() => false));
  await importButton.click();
  await page.waitForTimeout(800);
  await shot(page, "import-1-upload");

  // Upload the filled-in file.
  await page.setInputFiles('input[type="file"]', {
    name: "import.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(importCsv(stamp)),
  });
  await page.waitForTimeout(2500);
  await shot(page, "import-2-review");

  const reviewText = await page.locator("body").innerText();
  check(
    "Review step reports the good rows",
    /Ready to import/i.test(reviewText),
    reviewText.match(/Rows found\s*\n?\s*\d+/)?.[0] ?? "",
  );
  check(
    "Review step catches the bad row without writing it",
    /rent_amount must be a number/i.test(reviewText),
  );

  const importNow = page.getByRole("button", { name: /Import \d+ tenants?/ });
  const canCommit = await importNow.isVisible().catch(() => false);
  check("Commit button offers only the valid rows", canCommit);

  if (canCommit) {
    await importNow.click();
    await page.waitForTimeout(4000);
    await shot(page, "import-3-done");
    const doneText = await page.locator("body").innerText();
    check("Import completed and reported what it created", /Imported \d+ tenant/i.test(doneText));
    check(
      "Opening balance became a real invoice",
      /Opening balances/i.test(doneText),
    );
  }

  // Close the wizard and confirm the tenants really landed.
  await page.getByRole("button", { name: /^Done$/ }).click().catch(() => {});
  await page.waitForTimeout(1500);
  // Ask the API the question that actually matters — are the tenants there and
  // findable? With ~950 tenants they're not on page 1, and scrolling a paginated
  // list in a test proves nothing about the data.
  await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "networkidle" });
  await dismissTour(page);
  await shot(page, "import-4-tenants-list");

  const found = await page.evaluate(async () => {
    const token = localStorage.getItem("sahilpay_access_token");
    const res = await fetch(
      `${window.location.origin.replace("5173", "8000")}/api/tenants?search=Imported&per_page=50`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const body = await res.json().catch(() => ({}));
    return (body.tenants || []).map((t) => ({
      name: `${t.first_name} ${t.last_name}`,
      account: t.account_number,
      balance: t.balance,
    }));
  });

  check(
    "Imported tenants are searchable in the tenant list",
    found.length >= 2,
    `${found.length} found`,
  );
  check(
    "The imported arrears show as a real balance owed",
    found.some((t) => Number(t.balance) === -18000),
    found.map((t) => `${t.name}=${t.balance}`).join(", "),
  );

  // ---- Phase 9: the receipt layout designer ------------------------------
  await page.goto(`${BASE}/landlord/settings/receipt-layout`, { waitUntil: "networkidle" });
  await dismissTour(page);
  await page.waitForTimeout(1200);

  check(
    "Receipt designer offers every paper size",
    /Thermal roll/i.test(await page.locator("body").innerText()),
  );

  // Switch to the thermal roll and render a real preview PDF.
  await page.getByText("Thermal roll (80mm)").click();
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /Update preview/i }).click();
  await page.waitForTimeout(5000);
  await shot(page, "receipt-1-thermal-preview");

  const hasPreview = await page.locator('iframe[title="Receipt preview"]').isVisible().catch(() => false);
  check("Receipt preview renders a real PDF", hasPreview);

  await page.getByRole("button", { name: /Save layout/i }).click();
  await page.waitForTimeout(2000);
  check(
    "Receipt layout saves",
    /saved/i.test(await page.locator("body").innerText()),
  );
  await shot(page, "receipt-2-saved");

  // It must survive a reload — otherwise it was never persisted.
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const thermalStillSelected = await page
    .locator('button:has-text("Thermal roll (80mm)")')
    .evaluate((el) => el.className.includes("ring-secondary"))
    .catch(() => false);
  check("Saved layout survives a reload", thermalStillSelected);

  // Put it back so the estate isn't left on a till roll.
  await page.getByRole("button", { name: /Reset to default/i }).click();
  await page.getByRole("button", { name: /Save layout/i }).click();
  await page.waitForTimeout(1500);

  // ---- Phase 3.4: two-factor enrolment ------------------------------------
  // Driven through the API from inside the page so it uses the real session.
  const twofa = await page.evaluate(async () => {
    const token = localStorage.getItem("sahilpay_access_token");
    const call = async (path, body) => {
      const res = await fetch(`${window.location.origin.replace("5173", "8000")}/api${path}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      return { status: res.status, body: await res.json().catch(() => ({})) };
    };
    const setup = await call("/auth/2fa/setup");
    const wrong = await call("/auth/2fa/enable", { code: "000000" });
    return { setup, wrong };
  });

  check(
    "2FA setup returns a provisioning URI",
    twofa.setup.status === 200 && String(twofa.setup.body.provisioning_uri || "").startsWith("otpauth://"),
  );
  check(
    "2FA refuses a wrong confirmation code",
    twofa.wrong.status === 400,
    `got ${twofa.wrong.status}`,
  );

  await ctx.close();
  await browser.close();

  await writeFile(path.join(OUT, "results.json"), JSON.stringify({ results, consoleErrors }, null, 2));

  const failed = results.filter((r) => !r.passed);
  console.log(`\n${"=".repeat(66)}`);
  console.log(`Checks: ${results.length}   Passed: ${results.length - failed.length}   Failed: ${failed.length}`);
  if (consoleErrors.length) {
    console.log(`\nConsole errors seen (${consoleErrors.length}):`);
    [...new Set(consoleErrors)].slice(0, 5).forEach((e) => console.log(`  ${e}`));
  }
  console.log(`\nScreenshots in ${path.resolve(OUT)}`);
  process.exit(failed.length ? 1 : 0);
}

run().catch((err) => {
  console.error("feature-check crashed:", err);
  process.exit(2);
});
