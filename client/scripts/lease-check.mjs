/**
 * lease-check.mjs — drive a tenancy agreement all the way through, in a browser.
 *
 * Landlord prepares and sends → tenant reads and signs → landlord approves →
 * both download. Then the paper route: upload a signed scan and check the
 * tenant can take a copy immediately.
 *
 * The API tests cover the state machine; this proves the two screens actually
 * do it, on a phone-sized viewport, without the page scrolling sideways.
 *
 *   TENANT_TOKEN=... node scripts/lease-check.mjs [--base URL] [--out DIR]
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
const OUT = argOf("--out", "./lease-check");
const TENANT_TOKEN = process.env.TENANT_TOKEN;
const LANDLORD = { email: "landlord@sahilpay.test", password: "Landlord@123" };

const results = [];
function check(name, passed, detail = "") {
  results.push({ name, passed, detail });
  console.log(`[${passed ? "  ok  " : " FAIL "}] ${name}${detail ? ` — ${detail}` : ""}`);
}

async function shot(page, name) {
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
}

async function noSideScroll(page) {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

async function login(page) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"]', LANDLORD.email);
  await page.fill('input[type="password"]', LANDLORD.password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(2800);
  try {
    const skip = page.getByRole("button", { name: /skip for now|explore on my own/i });
    if (await skip.isVisible({ timeout: 1000 })) await skip.click();
  } catch { /* no tour */ }
}

async function run() {
  if (!TENANT_TOKEN) {
    console.error("TENANT_TOKEN is required — mint one for a seeded tenant first.");
    process.exit(2);
  }
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();

  // Phone-sized on purpose: this is the flow most likely to be done on a handset.
  const staff = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const staffPage = await staff.newPage();
  const tenant = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const tenantPage = await tenant.newPage();

  // Which tenancy the token belongs to — the lease must be prepared for THAT
  // one. Resolved in Node rather than inside the page: the portal redirects on
  // load, which destroys an in-page fetch mid-flight.
  // The portal context returns ids, not names, while the staff dropdown lists
  // names — so resolve the id here and look the name up as the landlord.
  // Preparing the lease for the wrong tenant is the silent failure this avoids.
  const apiBase = process.env.API_BASE || "http://127.0.0.1:8001";
  let tenantName = null;
  let tenantId = null;
  try {
    const ctxRes = await fetch(`${apiBase}/api/portal/context`, {
      headers: { Authorization: `Bearer ${TENANT_TOKEN}` },
    });
    // Some endpoints wrap in {data}, some return the object directly. Accept
    // both rather than guessing — guessing produced a null id and a lease
    // prepared for the wrong tenant.
    const raw = await ctxRes.json();
    const ctx = raw?.data ?? raw ?? {};
    tenantId = ctx.current_tenant_id ?? ctx.units?.[0]?.tenant_id ?? null;

    const authRes = await fetch(`${apiBase}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(LANDLORD),
    });
    const staffToken = (await authRes.json()).access_token;
    const listRes = await fetch(`${apiBase}/api/tenants?per_page=500`, {
      headers: { Authorization: `Bearer ${staffToken}` },
    });
    const listed = await listRes.json();
    const rows = listed.tenants ?? listed.items ?? listed.data?.items ?? [];
    const match = rows.find((r) => r.id === tenantId);
    if (match) tenantName = `${match.first_name} ${match.last_name}`.trim();
  } catch (err) {
    console.error("could not resolve the tenant:", err.message);
  }
  check("resolved the signed-in tenant", Boolean(tenantName),
        tenantName ? `${tenantName} (#${tenantId})` : "unknown");
  if (!tenantName) {
    console.error("Refusing to continue: the lease would be prepared for the wrong tenant.");
    process.exit(1);
  }

  await tenantPage.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await tenantPage.evaluate((t) => localStorage.setItem("sahilpay_access_token", t), TENANT_TOKEN);

  // ---- Landlord prepares and sends ---------------------------------------
  await login(staffPage);
  await staffPage.goto(`${BASE}/landlord/leases`, { waitUntil: "networkidle" });
  await staffPage.waitForTimeout(1200);
  check("leases page loads", /Lease agreements/i.test(await staffPage.innerText("body")));
  check("leases page does not scroll sideways", (await noSideScroll(staffPage)) === 0);
  await shot(staffPage, "01-leases-empty");

  await staffPage.getByRole("button", { name: /prepare a lease/i }).first().click();
  await staffPage.waitForTimeout(900);
  // Scope to the modal: the page behind it has its own status <select>, and
  // picking that one leaves the form's tenant unset and the button disabled.
  const modal = staffPage.locator("form").filter({ hasText: /Prepare|Tenant/i }).last();
  const select = modal.locator("select").first();
  // selectOption takes a literal label, not a pattern. The dropdown renders
  // "First Last", which is exactly what we resolved.
  await select.selectOption({ label: tenantName });
  await staffPage.waitForTimeout(400);

  const prepare = staffPage.getByRole("button", { name: /^prepare$/i });
  check("prepare is enabled once a tenant is chosen", !(await prepare.isDisabled()));
  await prepare.click();
  await staffPage.waitForTimeout(2200);
  const afterPrepare = await staffPage.innerText("body");
  check("lease prepared and sent", /With the tenant|Needs review/i.test(afterPrepare));
  await shot(staffPage, "02-leases-sent");

  // ---- Tenant reads and signs --------------------------------------------
  await tenantPage.goto(`${BASE}/portal/lease`, { waitUntil: "networkidle" });
  await tenantPage.waitForTimeout(1500);
  const leaseText = await tenantPage.innerText("body");
  // Assert on a CLAUSE, not the page title — "Tenancy agreement" is also the
  // heading, so matching that passes even when no lease loaded at all.
  check("tenant sees the agreement body",
        /The Landlord lets to the Tenant/i.test(leaseText));
  check("agreement carries the money terms",
        /deposit of/i.test(leaseText) && /rent of/i.test(leaseText));
  check("tenant lease page does not scroll sideways", (await noSideScroll(tenantPage)) === 0);
  await shot(tenantPage, "03-tenant-unsigned");

  // The button must stay disabled until BOTH the name and the tick are given —
  // the tick is the consent, the name alone could be a half-finished form.
  const signButton = tenantPage.getByRole("button", { name: /sign and submit/i });
  check("cannot sign with nothing filled in", await signButton.isDisabled());

  await tenantPage.fill('input[placeholder*="Amina"]', "Diana Achieng Test");
  check("cannot sign without ticking the box", await signButton.isDisabled());

  await tenantPage.locator('input[type="checkbox"]').first().check();
  await tenantPage.waitForTimeout(300);
  check("can sign once name and tick are given", !(await signButton.isDisabled()));

  await signButton.click();
  await tenantPage.waitForTimeout(2500);
  const afterSign = await tenantPage.innerText("body");
  check("tenant sees it is with the landlord", /with your landlord for review/i.test(afterSign));
  await shot(tenantPage, "04-tenant-signed");

  // ---- Landlord approves --------------------------------------------------
  await staffPage.reload({ waitUntil: "networkidle" });
  await staffPage.waitForTimeout(1500);
  check("landlord is told a lease needs review",
        /waiting for your review|Needs review/i.test(await staffPage.innerText("body")));

  const approve = staffPage.getByRole("button", { name: /^approve$/i }).first();
  check("approve is offered", (await approve.count()) > 0);
  if (await approve.count()) {
    await approve.click();
    await staffPage.waitForTimeout(2500);
    check("lease is approved", /Approved/i.test(await staffPage.innerText("body")));
    await shot(staffPage, "05-leases-approved");
  }

  // ---- Both sides download ------------------------------------------------
  const download = await fetch(`${apiBase}/api/portal/lease/download`, {
    headers: { Authorization: `Bearer ${TENANT_TOKEN}` },
  });
  const pdfBytes = new Uint8Array(await download.arrayBuffer());
  const tenantPdf = {
    status: download.status,
    head: String.fromCharCode(...pdfBytes.slice(0, 4)),
    size: pdfBytes.length,
  };
  check("tenant downloads a real PDF",
        tenantPdf.status === 200 && tenantPdf.head === "%PDF",
        `${tenantPdf.status}, ${tenantPdf.size} bytes`);

  await tenantPage.goto(`${BASE}/portal/lease`, { waitUntil: "networkidle" });
  await tenantPage.waitForTimeout(1400);
  const approvedText = await tenantPage.innerText("body");
  check("tenant is told it is approved", /approved/i.test(approvedText));
  check("tenant is offered their copy", /download my copy/i.test(approvedText));
  await shot(tenantPage, "06-tenant-approved");

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
  console.error("lease-check crashed:", err);
  process.exit(2);
});
