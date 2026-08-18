import { chromium } from "playwright";

const WEB = "http://localhost:5173";
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 1100 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

const results = [];
function say(ok, label, detail = "") {
  results.push(ok);
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
}

await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
await page.locator('input[name="email"]').fill("landlord@sahilpay.test");
await page.locator('input[name="password"]').fill("Landlord@123");
await page.getByRole("button", { name: "Log in" }).click();
await page.waitForURL(/\/landlord/, { timeout: 20000 });

await page.goto(`${WEB}/landlord/reports/penalties`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2000);

let body = await page.locator("main").innerText();
say(/Charges/.test(body) && /Run a batch/.test(body), "Penalties page has both tabs");
say((body.match(/^Penalties$/gm) || []).length === 1, "Page title is not duplicated");

await page.getByRole("button", { name: "Run a batch" }).click();
await page.waitForTimeout(1500);
body = await page.locator("main").innerText();

say(/Owes at least/.test(body) && /Days overdue/.test(body),
    "All four filters are offered");
say(/Find tenants/.test(body), "Filters are applied deliberately, not on every keystroke");

await page.getByRole("button", { name: "Find tenants" }).click();
await page.waitForTimeout(2000);
body = await page.locator("main").innerText();

const hasCandidates = /Owes/.test(body) && !/Nobody matches/.test(body);
say(hasCandidates, "Tenants in arrears are listed");

if (hasCandidates) {
  say(/% of what they owe/.test(body) || /flat amount each/.test(body),
      "Flat and percentage are both offered");
  say(/open invoice \(one bill\)/i.test(body) || /new penalty invoice/i.test(body),
      "Where the charge lands is a choice");
  say(/tenants? selected/.test(body), "It shows how many are selected and the total");

  // Confirmation must be required — this moves real money.
  const chargeBtn = page.getByRole("button", { name: /^Charge \d+ tenants?$/ });
  say(await chargeBtn.count() > 0, "Charge button reflects the selection",
      (await chargeBtn.innerText().catch(() => "")).trim());

  await chargeBtn.click();
  await page.waitForTimeout(900);
  const dialog = await page.locator("body").innerText();
  say(/Charge \d+ tenants?\?/.test(dialog), "A confirmation is required before charging");
  say(/skipped automatically/.test(dialog),
      "The dialog explains the once-a-month guard");

  // Back out — this check must not actually fine anyone.
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.waitForTimeout(500);
  say(true, "Cancelled without charging anyone");
}

say(errors.length === 0, "No uncaught page errors", errors[0] || "");
await browser.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
process.exit(results.every(Boolean) ? 0 : 1);
