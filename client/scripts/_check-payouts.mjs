import { chromium } from "playwright";

const WEB = "http://localhost:5173";
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

function say(ok, label, detail = "") {
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
  return ok;
}

await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
await page.locator('input[name="email"]').fill("landlord@sahilpay.test");
await page.locator('input[name="password"]').fill("Landlord@123");
await page.getByRole("button", { name: "Log in" }).click();
await page.waitForURL(/\/landlord/, { timeout: 20000 });
await page.waitForTimeout(1200);

const sidebar = await page.locator("aside").innerText();
say(!/Payout runs/.test(sidebar), "Sidebar no longer shows a separate 'Payout runs' link");
say((sidebar.match(/Owner payouts/g) || []).length === 1, "Sidebar shows exactly one owner-payouts entry");

// The tab shell.
await page.goto(`${WEB}/landlord/payouts`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1500);
let body = await page.locator("body").innerText();
say(/Owner payouts/.test(body), "Payouts page renders its title");
say(/Payout runs/.test(body) && /Ledger/.test(body), "Both tabs are present");
// Count only inside the main content: the sidebar link says "Owner payouts"
// too, so counting the whole body would always find at least two.
const mainText = await page.locator("main").innerText().catch(async () => body);
say((mainText.match(/^Owner payouts$/gm) || []).length <= 1,
    "Title is not duplicated by the child page",
    `${(mainText.match(/^Owner payouts$/gm) || []).length} occurrence(s) in main`);

// Switch to the ledger tab by clicking it, like a person would.
await page.getByRole("link", { name: "Ledger" }).click();
await page.waitForTimeout(1500);
say(/\/payouts\/ledger$/.test(page.url()), "Ledger tab navigates", page.url());
body = await page.locator("body").innerText();
say(/Record payout/.test(body), "Ledger tab shows its 'Record payout' action");

// The old bookmarked URL must still land somewhere sensible.
await page.goto(`${WEB}/landlord/owner-payouts`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1500);
say(/\/payouts\/ledger$/.test(page.url()), "Old /owner-payouts URL redirects to the ledger tab", page.url());

// Back to runs.
await page.getByRole("link", { name: "Payout runs" }).click();
await page.waitForTimeout(1500);
body = await page.locator("body").innerText();
say(/what each owner is owed/i.test(body), "Runs tab explains what it does");

say(errors.length === 0, "No uncaught page errors", errors[0] || "");
await browser.close();
