/**
 * Lease flow, end to end, as people actually use it.
 *
 *  A. Landlord sends the Sahil Pay STANDARD lease to James (desktop).
 *     James (phone) sees it on his dashboard, opens it, signs ON PAPER:
 *     downloads the branded blank, uploads photos of two signed pages.
 *     Landlord reviews the pages and approves. Both download the final copy.
 *  B. Landlord sends an UPLOADED lease document to a second tenant, who signs
 *     ELECTRONICALLY; the caretaker (team member) sees it; landlord approves.
 *
 *   node scripts/qa/lease-flow.mjs
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { BASE, SHOTS, results, shooter, staffLogin, tenantLogin, noSideScroll, dismissTours, api, apiLogin } from "./helpers.mjs";

const SCRATCH = process.env.QA_SCRATCH || "/tmp";
const R = results();
const browser = await chromium.launch();

async function savePdf(download, name) {
  const path = `${SHOTS}/lease/${name}.pdf`;
  await download.saveAs(path);
  execSync(`pdftoppm -png -r 60 -f 1 -l 1 "${path}" "${SHOTS}/lease/${name}-p1"`);
  const pages = execSync(`pdfinfo "${path}" | grep Pages | awk '{print $2}'`).toString().trim();
  execSync(`pdftoppm -png -r 60 -f ${pages} -l ${pages} "${path}" "${SHOTS}/lease/${name}-last"`);
  return { path, pages: Number(pages), text: execSync(`pdftotext "${path}" - | head -c 4000`).toString() };
}

try {
  // ---------------- A. standard lease, signed on paper ----------------
  const staffCtx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const staff = await staffCtx.newPage();
  const sshot = shooter(staff, "lease");
  await staffLogin(staff, "landlord@sahilpay.test", "Landlord@123");
  await staff.goto(`${BASE}/landlord/leases`, { waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await dismissTours(staff);
  await sshot("A01-landlord-leases-page");

  await staff.getByTestId("send-lease").click();
  await staff.getByPlaceholder(/Search tenants/).fill("James");
  await staff.waitForTimeout(1500);
  await staff.locator('label:has-text("James Mwangi") input[type=checkbox]').first().check();
  await sshot("A02-wizard-step1-tenants", { fullPage: false });
  await staff.getByRole("button", { name: /^Next/ }).click();
  await sshot("A03-wizard-step2-document", { fullPage: false });
  await staff.getByRole("button", { name: /^Next/ }).click();
  await sshot("A04-wizard-step3-review", { fullPage: false });
  await staff.getByRole("button", { name: /Send to 1 tenant/ }).click();
  await staff.waitForTimeout(2500);
  await sshot("A05-lease-sent-list");
  R.check("landlord sent the standard lease", await staff.getByText("With tenant").first().isVisible());

  // Tenant on a phone
  const phoneCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, acceptDownloads: true, isMobile: true, hasTouch: true });
  const tenant = await phoneCtx.newPage();
  const tshot = shooter(tenant, "lease");
  await tenantLogin(tenant, "+254711000001");
  await tenant.waitForTimeout(1500);
  await tshot("A06-tenant-dashboard-lease-card", { fullPage: false });
  R.check("tenant dashboard shows 'You have a lease to sign'", await tenant.getByTestId("lease-action-card").isVisible());
  const bottomLeases = tenant.locator('nav[aria-label="Tenant portal"] >> text=Leases').last();
  R.check("phone bottom tab bar shows Leases", await bottomLeases.isVisible());
  R.check("tenant dashboard has no sideways scroll", await noSideScroll(tenant));

  await tenant.goto(`${BASE}/portal/notifications`, { waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await tshot("A07-tenant-notifications");
  R.check("tenant notification about the lease exists", await tenant.getByText(/lease to sign/i).first().isVisible());

  await tenant.goto(`${BASE}/portal/leases`, { waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await tshot("A08-tenant-leases-list");
  await tenant.getByTestId("tenant-lease-list").locator("a").first().click();
  await tenant.waitForTimeout(1500);
  await tshot("A09-tenant-lease-detail-top", { fullPage: false });
  await tenant.getByRole("radio", { name: /Sign on paper/ }).click();
  const [blankDl] = await Promise.all([tenant.waitForEvent("download"), tenant.getByRole("button", { name: /Download to print/ }).click()]);
  const blank = await savePdf(blankDl, "A10-blank-lease-to-print");
  R.check("blank lease PDF downloads and carries the landlord's name", blank.text.includes("Acme Properties"), `${blank.pages} pages`);

  await tenant.locator('input[type=file]').setInputFiles([`${SCRATCH}/signed-page-1.jpg`, `${SCRATCH}/signed-page-2.jpg`]);
  await tenant.getByLabel(/Your full name, as you signed/).fill("James Mwangi");
  await tenant.getByText("These are the pages of the agreement I signed.").click();
  await tshot("A11-tenant-paper-sign-ready");
  await tenant.getByRole("button", { name: /Upload and submit/ }).click();
  await tenant.getByText(/with your landlord for review/i).first().waitFor({ timeout: 45000 });
  await tshot("A12-tenant-submitted-for-review", { fullPage: false });
  R.check("tenant sees 'with your landlord for review'", await tenant.getByText(/with your landlord for review/i).first().isVisible());

  // Landlord reviews
  await staff.goto(`${BASE}/landlord/leases`, { waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await staff.getByRole("tab", { name: /Needs review/ }).click();
  await staff.getByRole("button", { name: /^Review$/ }).first().waitFor({ timeout: 20000 });
  await sshot("A13-landlord-needs-review");
  await staff.getByRole("button", { name: /^Review$/ }).first().click();
  await staff.waitForTimeout(2500);
  await sshot("A14-landlord-review-drawer-scans", { fullPage: false });
  R.check("review drawer shows the scanned pages", await staff.getByAltText("Signed page 1").isVisible());
  await staff.getByTestId("approve-lease").click();
  await staff.getByText(/Approved\. The tenant has been notified/).waitFor({ timeout: 45000 });
  await sshot("A15-landlord-approved", { fullPage: false });

  await tenant.reload({ waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await tenant.waitForTimeout(1500);
  await tshot("A16-tenant-lease-approved", { fullPage: false });
  const [finalDl] = await Promise.all([tenant.waitForEvent("download"), tenant.getByRole("button", { name: /Download final copy/ }).click()]);
  const final = await savePdf(finalDl, "A17-final-lease-tenant-copy");
  R.check("tenant downloads the final approved lease", final.text.includes("APPROVED") && final.pages >= 3, `${final.pages} pages`);

  await staff.goto(`${BASE}/landlord/leases`, { waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await staff.getByRole("tab", { name: /^Approved/ }).click();
  await staff.waitForTimeout(800);
  const [staffFinal] = await Promise.all([staff.waitForEvent("download"), staff.getByRole("button", { name: /Final copy/ }).first().click()]);
  const sf = await savePdf(staffFinal, "A18-final-lease-landlord-copy");
  R.check("landlord downloads the same final copy", sf.pages === final.pages, `${sf.pages} pages`);

  // ---------------- B. uploaded document, signed electronically ----------------
  writeFileSync(`${SCRATCH}/own-lease.pdf`, execSync(`cd ../server && . venv/bin/activate && APP_ENV=development python -c "
from app import create_app
app=create_app()
with app.app_context():
    from utils import render_pdf
    import sys
    sys.stdout.buffer.write(render_pdf('<h1>ACME HOUSE RULES LEASE</h1><p>1. Rent is due on the 5th.</p><p>2. No pets.</p>'))
" 2>/dev/null`));
  await staff.goto(`${BASE}/landlord/leases`, { waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await staff.getByTestId("send-lease").click();
  await staff.getByPlaceholder(/Search tenants/).fill("Amina");
  await staff.waitForTimeout(1500);
  const graceBox = staff.locator('label:has(input[type=checkbox])').first();
  const graceName = (await graceBox.innerText()).split("\n")[0];
  await graceBox.locator("input").check();
  await staff.getByRole("button", { name: /^Next/ }).click();
  await staff.getByRole("radio", { name: /An uploaded lease document/ }).click();
  await staff.locator('input[type=file]').setInputFiles(`${SCRATCH}/own-lease.pdf`);
  await staff.getByLabel(/Title/).fill("Acme house rules lease 2026");
  await sshot("B01-wizard-uploaded-document", { fullPage: false });
  await staff.getByRole("button", { name: /^Next/ }).click();
  await staff.getByRole("button", { name: /Send to 1 tenant/ }).click();
  await staff.waitForTimeout(2500);
  R.check(`uploaded lease sent to ${graceName}`, await staff.getByText("Acme house rules lease 2026").first().isVisible());

  const llToken = await apiLogin("landlord@sahilpay.test", "Landlord@123");
  const found = await api(`/tenants?search=${encodeURIComponent(graceName.split(" ")[0])}&per_page=1`, { token: llToken });
  const tenantPhone2 = (found.json.tenants || found.json.items)[0].phone;
  const tabCtx = await browser.newContext({ viewport: { width: 820, height: 1180 }, acceptDownloads: true });
  const t2 = await tabCtx.newPage();
  const t2shot = shooter(t2, "lease");
  await tenantLogin(t2, tenantPhone2);
  await t2shot("B02-tablet-tenant-dashboard", { fullPage: false });
  await t2.getByTestId("lease-action-card").click();
  await t2.waitForTimeout(1500);
  await t2shot("B03-tablet-uploaded-lease-detail");
  await t2.getByLabel(/Your full name, as on your ID/).fill(graceName);
  await t2.getByText("I have read this tenancy agreement").click();
  await t2.getByRole("button", { name: /Sign and submit/ }).click();
  await t2.getByText(/with your landlord for review/i).first().waitFor({ timeout: 45000 });
  await t2shot("B04-tablet-signed-electronically", { fullPage: false });

  // Caretaker (team member) sees it
  const teamCtx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const team = await teamCtx.newPage();
  const teamShot = shooter(team, "lease");
  await staffLogin(team, "caretaker@sahilpay.test", "Caretaker@123");
  await team.goto(`${BASE}/team/leases`, { waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await team.waitForTimeout(1500);
  await teamShot("B05-caretaker-leases");
  R.check("caretaker (team member) sees the submitted lease", await team.getByText("Acme house rules lease 2026").first().isVisible());

  await staff.goto(`${BASE}/landlord/leases`, { waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await staff.getByRole("tab", { name: /Needs review/ }).click();
  await staff.getByRole("button", { name: /^Review$/ }).first().waitFor({ timeout: 20000 });
  await staff.getByRole("button", { name: /^Review$/ }).first().click();
  await staff.waitForTimeout(1200);
  await sshot("B06-landlord-review-electronic", { fullPage: false });
  await staff.getByTestId("approve-lease").click();
  await staff.getByText(/Approved\. The tenant has been notified/).waitFor({ timeout: 45000 });
  await t2.reload({ waitUntil: "domcontentloaded" }); await new Promise((r) => setTimeout(r, 1500));
  await t2.waitForTimeout(1000);
  const [dl2] = await Promise.all([t2.waitForEvent("download"), t2.getByRole("button", { name: /Download final copy/ }).click()]);
  const f2 = await savePdf(dl2, "B07-final-uploaded-lease");
  R.check("final copy of uploaded lease includes the landlord's own document", f2.text.includes("ACME HOUSE RULES LEASE") && f2.text.includes(graceName), `${f2.pages} pages`);
  await t2shot("B08-tablet-approved", { fullPage: false });
} catch (err) {
  console.error(err);
  R.check("script completed without errors", false, err.message);
} finally {
  await browser.close();
  process.exit(R.summary() ? 1 : 0);
}
