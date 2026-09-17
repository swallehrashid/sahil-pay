/**
 * Navigation & layout across screen sizes: phone → tablet → laptop → desktop → TV.
 * Checks no sideways scroll, the grouped nav, "+ New", the phone bottom bar,
 * and that every group opens to real pages.
 *
 *   node scripts/qa/nav-responsive.mjs
 */
import { chromium } from "playwright";
import { BASE, results, shooter, staffLogin, tenantLogin, noSideScroll } from "./helpers.mjs";

const SIZES = [
  { name: "phone", width: 390, height: 844, mobile: true },
  { name: "tablet", width: 820, height: 1180, mobile: true },
  { name: "laptop", width: 1366, height: 768 },
  { name: "desktop", width: 1920, height: 1080 },
  { name: "tv", width: 2560, height: 1440 },
];
const PAGES = ["/landlord/dashboard", "/landlord/payments", "/landlord/tenants", "/landlord/leases", "/landlord/reports/statements", "/landlord/settings/general"];
const R = results();
const browser = await chromium.launch();

try {
  for (const size of SIZES) {
    const ctx = await browser.newContext({ viewport: { width: size.width, height: size.height }, isMobile: !!size.mobile, hasTouch: !!size.mobile });
    const page = await ctx.newPage();
    const shot = shooter(page, "nav");
    await staffLogin(page, "landlord@sahilpay.test", "Landlord@123");
    for (const path of PAGES) {
      await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1800);
      R.check(`${size.name} ${path}: no sideways scroll`, await noSideScroll(page));
    }
    await page.goto(`${BASE}/landlord/dashboard`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot(`${size.name}-dashboard`, { fullPage: false });

    if (size.width < 1024) {
      R.check(`${size.name}: bottom bar visible`, await page.getByRole("navigation", { name: "Quick navigation" }).isVisible());
      await page.getByTestId("bottom-menu-button").click();
      await page.waitForTimeout(500);
      await page.getByTestId("nav-group-money").click();
      await page.waitForTimeout(300);
      await shot(`${size.name}-menu-open-money`, { fullPage: false });
      R.check(`${size.name}: Money group opens to Payments`, await page.getByRole("link", { name: "Payments" }).first().isVisible());
      await page.getByRole("link", { name: "Payments" }).first().click();
      await page.waitForTimeout(1200);
      R.check(`${size.name}: navigating from the menu works`, page.url().includes("/landlord/payments"));
      await page.getByRole("navigation", { name: "Quick navigation" }).getByTestId("new-action-button").click();
      await page.waitForTimeout(400);
      await shot(`${size.name}-new-menu`, { fullPage: false });
    } else {
      const groups = await page.locator('[data-testid^="nav-group-"]').count();
      R.check(`${size.name}: sidebar shows grouped nav`, groups >= 5, `${groups} groups`);
      await page.getByTestId("nav-group-tenants").click();
      await page.waitForTimeout(300);
      await page.locator("aside").getByTestId("new-action-button").click();
      await page.waitForTimeout(400);
      await shot(`${size.name}-sidebar-tenants-open-new-menu`, { fullPage: false });
      await page.getByRole("menuitem", { name: "Send a lease" }).click();
      await page.waitForTimeout(1500);
      R.check(`${size.name}: "+ New → Send a lease" opens the send wizard`, await page.getByRole("dialog").getByText("Send a lease").first().isVisible());
      await shot(`${size.name}-new-send-lease`, { fullPage: false });
      await page.keyboard.press("Escape");
      await page.goto(`${BASE}/landlord/settings/billing`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1500);
      await shot(`${size.name}-settings-grouped`, { fullPage: false });
    }
    await ctx.close();
  }

  // Team member sees only what they may, still grouped.
  const tctx = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const team = await tctx.newPage();
  await staffLogin(team, "viewer.acme@sahilpay.test", "Viewer@123");
  await team.goto(`${BASE}/team/dashboard`, { waitUntil: "domcontentloaded" });
  await team.waitForTimeout(2000);
  await shooter(team, "nav")("team-viewer-sidebar", { fullPage: false });
  R.check("view-only team member has no '+ New' button", !(await team.locator("aside").getByTestId("new-action-button").count()));

  // Tenant portal at TV size
  const tv = await (await browser.newContext({ viewport: { width: 2560, height: 1440 } })).newPage();
  await tenantLogin(tv, "+254711000003");
  await shooter(tv, "nav")("tenant-tv-dashboard", { fullPage: false });
  R.check("tenant portal: no sideways scroll on a TV", await noSideScroll(tv));
} catch (err) {
  console.error(err);
  R.check("script completed without errors", false, err.message.split("\n")[0]);
} finally {
  await browser.close();
  process.exit(R.summary() ? 1 : 0);
}
