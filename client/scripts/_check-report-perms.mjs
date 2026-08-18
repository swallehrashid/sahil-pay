import { chromium } from "playwright";

// Login is capped at 5/minute per IP — correct in production, and easily hit
// when several check scripts run back to back. Wait it out rather than
// reporting the app broken.
async function signInWithRetry(page, WEB, email, password) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill(password);
    await page.getByRole("button", { name: "Log in" }).click();
    try {
      await page.waitForURL(/\/(landlord|team)/, { timeout: 12000 });
      return;
    } catch {
      if (attempt === 3) throw new Error(`could not sign in as ${email}`);
      console.log(`        (sign-in did not land — waiting 25s)`);
      await new Promise((r) => setTimeout(r, 25000));
    }
  }
}

const WEB = "http://localhost:5173";
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

function say(ok, label, detail = "") {
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
}

await signInWithRetry(page, WEB, "landlord@sahilpay.test", "Landlord@123");

await page.goto(`${WEB}/landlord/settings/team`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2000);

let body = await page.locator("body").innerText();
say(/Team/i.test(body), "Team settings page loads");

// Row actions live behind a Dropdown, so open that first, then pick Edit.
// The Dropdown renders a bare button containing a MoreVertical icon.
await page.locator("table .lucide-ellipsis-vertical, table .lucide-more-vertical").first().click();
await page.waitForTimeout(500);
await page.getByText("Edit", { exact: true }).first().click();
await page.waitForTimeout(2000);

// The picker is deliberately hidden until Reports is actually granted — an
// unreachable list of report checkboxes reads as a bug. So confirm it is absent
// first, then grant Reports and confirm it appears.
const before = await page.locator("body").innerText();
say(!/All reports \(including any added later\)/.test(before),
    "Report picker is hidden while Reports is not granted");

// Row whose label cell is exactly the Reports module.
const reportsRow = page.locator("tr").filter({ hasText: "Statements and reports" }).first();
await reportsRow.locator('input[type="checkbox"]').first().check({ force: true });
await page.waitForTimeout(1000);

body = await page.locator("body").innerText();
const hasMatrix = /Which reports|All reports/.test(body);
say(hasMatrix, "Permission matrix shows the per-report picker", hasMatrix ? "" : "picker not found");

// "All reports" starts ticked (allowed_reports = null), which collapses the
// individual list — that IS the default state, so untick it to reveal them.
await page
  .locator("label", { hasText: "All reports (including any added later)" })
  .locator('input[type="checkbox"]')
  .uncheck({ force: true });
await page.waitForTimeout(800);

body = await page.locator("body").innerText();
const named = ["Property statement", "Tenant statement", "Arrears", "Month-on-month"]
  .filter((n) => body.includes(n));
say(named.length >= 3, "Individual reports are listed by name", named.join(", "));

// Plain-English module labels replaced the raw keys.
say(!/unit_utilities/.test(body), "Raw module keys are not shown to the landlord");

say(errors.length === 0, "No uncaught page errors", errors[0] || "");
await browser.close();
