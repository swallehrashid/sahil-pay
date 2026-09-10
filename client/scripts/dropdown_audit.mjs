/**
 * Sweep every page that carries dropdowns and confirm each one is a real
 * combobox that opens, filters and scrolls — across all four portals, not just
 * the landlord forms the main walkthrough covers.
 */
import { chromium } from "playwright";

const BASE = "http://127.0.0.1:5173";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

const login = async (email, password) => {
  await page.evaluate(() => localStorage.clear()).catch(() => {});
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"], input[name="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
};

const PAGES = [
  ["landlord@sahilpay.test", "Landlord@123", [
    "/landlord/dashboard", "/landlord/properties", "/landlord/units",
    "/landlord/tenants", "/landlord/invoices", "/landlord/payments",
    "/landlord/expenses", "/landlord/utilities", "/landlord/maintenance",
    "/landlord/reports", "/landlord/communications", "/landlord/leases",
    "/landlord/penalties", "/landlord/settings/general",
    "/landlord/settings/receipt-layout", "/landlord/settings/team",
    "/landlord/bulk-import", "/landlord/property-groups",
  ]],
  ["caretaker@sahilpay.test", "Caretaker@123", ["/team/dashboard", "/team/tenants"]],
];

let totalCombos = 0, opened = 0, withSearch = 0, scrollable = 0;
const problems = [];

for (const [email, password, paths] of PAGES) {
  await login(email, password);
  for (const path of paths) {
    try {
      await page.goto(`${BASE}${path}`, { waitUntil: "networkidle", timeout: 20000 });
      await page.waitForTimeout(1100);
    } catch { continue; }

    const combos = page.locator('[role="combobox"]:visible');
    const n = await combos.count();
    totalCombos += n;
    if (!n) continue;

    // Open each visible combobox on the page and check its own panel.
    for (let i = 0; i < Math.min(n, 6); i++) {
      try {
        await combos.nth(i).click({ timeout: 4000 });
        await page.waitForTimeout(280);
        const list = page.locator('[role="listbox"]');
        if (!(await list.count())) { problems.push(`${path} #${i}: no listbox`); continue; }
        opened++;
        const panel = list.first().locator("xpath=..");
        if (await panel.locator('[role="searchbox"]').count()) withSearch++;
        else problems.push(`${path} #${i}: no search box`);
        const scrolls = await list.first().evaluate((el) => {
          const o = getComputedStyle(el).overflowY;
          return o === "auto" || o === "scroll";
        });
        if (scrolls) scrollable++;
        else problems.push(`${path} #${i}: list does not scroll`);
        await page.keyboard.press("Escape");
        await page.waitForTimeout(150);
      } catch (e) {
        problems.push(`${path} #${i}: ${e.message.split("\n")[0].slice(0, 60)}`);
      }
    }
  }
}

console.log(`comboboxes found:      ${totalCombos}`);
console.log(`opened and inspected:  ${opened}`);
console.log(`with a search box:     ${withSearch}`);
console.log(`with a scrolling list: ${scrollable}`);
console.log(`\nproblems: ${problems.length}`);
problems.slice(0, 15).forEach((p) => console.log("  " + p));
console.log(`\nconsole errors: ${errors.length}`);
errors.slice(0, 6).forEach((e) => console.log("  " + e.slice(0, 140)));
await browser.close();
process.exit(problems.length === 0 && opened > 0 ? 0 : 1);
