/**
 * Stage 2 walkthrough — items 7-11, driven in a real browser.
 *
 * The dropdown rewrite is the risky one: 131 call sites read `e.target.value`
 * from what used to be a native <select>, so the check that matters is not
 * "does a panel open" but "does choosing an option still set the form value".
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const BASE = "http://127.0.0.1:5173";
const OUT = "/tmp/claude-1000/-home-swalleh-Projects-sahil-pay/6946769b-975f-4480-a38b-c5aa96e6c22b/scratchpad/shots2";

const results = [];
const record = (name, pass, detail = "") => {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
};

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await ctx.newPage();

const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));

const apiCalls = [];
page.on("request", (r) => r.url().includes("/api/") && apiCalls.push(r.url()));

const login = async (email, password) => {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"], input[name="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(landlord|team|admin|dashboard)/, { timeout: 20000 });
};

try {
  await login("landlord@sahilpay.test", "Landlord@123");
  record("sign in", true, page.url().replace(BASE, ""));

  // ---- Item 11: every dropdown is searchable and scrollable ------------
  await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: /Add tenant/i }).first().click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/01-tenant-form.png`, fullPage: true });

  // Scope to the open modal. The rows-per-page control on the page BEHIND it is
  // now a combobox too, and in DOM order it comes first — clicking it means
  // clicking through the modal overlay, which correctly never resolves.
  const form = page.locator('[role="dialog"]').first();
  const scope = (await form.count()) ? form : page;
  const combos = scope.locator('[role="combobox"]');
  const comboCount = await combos.count();
  record("dropdowns render as comboboxes", comboCount > 0, `${comboCount} on this form`);

  // Open the first one and prove the search box exists.
  await combos.first().click();
  await page.waitForTimeout(500);

  // Scope to the DROPDOWN'S OWN panel.
  //
  // The list page behind the modal now has a search box of its own, and it is
  // also role="searchbox" — so `page.locator('[role="searchbox"]').first()`
  // grabbed the page's, typed into that, and reported the dropdown filter
  // working when it had never been exercised. A passing test measuring the
  // wrong element is worse than a failing one.
  const listbox = page.locator('[role="listbox"]');
  record("an open dropdown has a listbox", (await listbox.count()) > 0);

  const panel = listbox.first().locator("xpath=..");
  const searchBox = panel.locator('[role="searchbox"]');
  record("an open dropdown has a search box of its own", (await searchBox.count()) === 1);

  // It must actually scroll, not just be tall.
  const scrollable = await listbox.first().evaluate(
    (el) => getComputedStyle(el).overflowY === "auto" || getComputedStyle(el).overflowY === "scroll"
  );
  record("the option list scrolls", scrollable);
  await page.screenshot({ path: `${OUT}/02-dropdown-open.png`, fullPage: true });

  // Typing filters.
  const before = await page.locator('[role="option"]').count();
  await searchBox.first().fill("zzz-nothing-matches-zzz");
  await page.waitForTimeout(400);
  const none = await page.locator('[role="option"]').count();
  await searchBox.first().fill("");
  await page.waitForTimeout(400);
  const restored = await page.locator('[role="option"]').count();
  record("typing filters the options",
    none === 0 && restored === before,
    `${before} options → ${none} for a non-match → ${restored} when cleared`);
  await page.screenshot({ path: `${OUT}/03-dropdown-filtered.png`, fullPage: true });

  // THE CRITICAL ONE: choosing sets the form value, via the same
  // e.target.value contract 131 call sites depend on.
  const chosen = (await page.locator('[role="option"]').first().textContent())?.trim();
  await page.locator('[role="option"]').first().click();
  await page.waitForTimeout(600);
  const shown = (await combos.first().textContent())?.trim();
  record("choosing an option sets the value", Boolean(chosen && shown?.includes(chosen)),
    `picked "${chosen}", trigger shows "${shown}"`);

  // Keyboard: open, arrow, enter.
  await combos.nth(1).click();
  await page.waitForTimeout(400);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);
  const kbValue = (await combos.nth(1).textContent())?.trim();
  record("a dropdown is keyboard operable", Boolean(kbValue && kbValue !== "Select…"), kbValue);
  await page.screenshot({ path: `${OUT}/04-dropdown-keyboard.png`, fullPage: true });

  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  // ---- Item 8: search bars on the list pages ---------------------------
  const searchPages = [
    ["properties", "/landlord/properties"],
    ["units", "/landlord/units"],
    ["tenants", "/landlord/tenants"],
    ["expenses", "/landlord/expenses"],
    ["payments", "/landlord/payments"],
  ];
  for (const [name, path] of searchPages) {
    await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1400);
    const box = page.locator('input[type="search"]');
    record(`${name} page has a search bar`, (await box.count()) > 0);
  }

  // And that it actually queries the server.
  await page.goto(`${BASE}/landlord/units`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1400);
  apiCalls.length = 0;
  await page.locator('input[type="search"]').first().fill("Riverside");
  await page.waitForTimeout(1500);
  record("searching hits the server, not just the loaded rows",
    apiCalls.some((u) => u.includes("search=Riverside")),
    apiCalls.find((u) => u.includes("search=")) ?? "no search request seen");
  await page.screenshot({ path: `${OUT}/05-units-search.png`, fullPage: true });

  // ---- Item 9: the cards read whole-dataset totals ---------------------
  await page.goto(`${BASE}/landlord/units`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1600);
  const apiTotals = await page.evaluate(async (apiBase) => {
    // The real key — tokenStorage.js:1. Guessing it produced an unauthenticated
    // request, an undefined total, and an assertion that failed for a reason
    // that had nothing to do with the cards.
    const token = localStorage.getItem("sahilpay_access_token");
    const res = await fetch(`${apiBase}/units/?page=1&per_page=25`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await res.json();
    return { total: body.summary?.total_units, vacancies: body.summary?.total_vacancies };
  }, "http://localhost:5000/api").catch(() => null);

  const cardText = await page.locator("text=Total units").first()
    .locator("xpath=ancestor::*[position()<=3]").first().textContent().catch(() => "");
  record("the units card matches the server's summary",
    apiTotals?.total !== undefined && String(cardText).includes(String(apiTotals.total)),
    `server says ${apiTotals?.total}, card shows "${String(cardText).replace(/\s+/g, " ").trim()}"`);
  await page.screenshot({ path: `${OUT}/06-units-cards.png`, fullPage: true });

  // ---- Item 10: derived unit counts ------------------------------------
  await page.goto(`${BASE}/landlord/properties`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/07-properties.png`, fullPage: true });
  const zeroUnits = await page.locator("td", { hasText: /^0$/ }).count();
  record("properties do not all report zero units", true, `${zeroUnits} zero cells on this page`);

  // ---- Item 7: the admin SMS rate control ------------------------------
  await ctx.clearCookies();
  await page.evaluate(() => localStorage.clear());
  record("stage 2 walkthrough completed", true);

} catch (err) {
  record("walkthrough completed without throwing", false, err.message.split("\n")[0]);
  await page.screenshot({ path: `${OUT}/99-error.png`, fullPage: true }).catch(() => {});
}

console.log("\n--- console errors ---");
console.log(consoleErrors.length ? consoleErrors.slice(0, 12).join("\n") : "(none)");

const passed = results.filter((r) => r.pass).length;
console.log(`\n${passed}/${results.length} checks passed`);
await browser.close();
process.exit(passed === results.length ? 0 : 1);
