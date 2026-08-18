/**
 * The screens built in this round that had never been driven in a browser:
 * the tenant portal's side of the lease and message flows, the maintenance
 * detail with its photo and notes, and the eTIMS control-number importer.
 *
 * The tenant portal matters most. Everything about it was verified through the
 * API, which proves the data is right and proves nothing about whether a tenant
 * can actually find their lease — and "I sent a lease and the tenant never saw
 * it" was the original complaint.
 *
 * Tenant sign-in goes through the real OTP flow rather than an injected token:
 * the code is read out of the simulated-SMS log, which is exactly what a tenant
 * reads off their phone.
 *
 *   node scripts/_check-tenant-and-new-ui.mjs
 */

import { chromium } from "playwright";
import fs from "node:fs";

const WEB = process.env.WEB_URL || "http://localhost:5173";
const API = process.env.API_URL || "http://localhost:5000/api";
const API_LOG = process.env.API_LOG || "/tmp/sahilpay-api.log";
const TENANT_PHONE = "+254711000001";

const results = [];
function say(ok, label, detail = "") {
  results.push({ ok, label, detail });
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
}
function section(name) { console.log(`\n${name}`); }

async function api(path, { token, method = "GET", body } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, json: await res.json().catch(() => ({})) };
}

async function landlordToken() {
  for (let i = 0; i < 4; i += 1) {
    const { status, json } = await api("/auth/login", {
      method: "POST", body: { email: "landlord@sahilpay.test", password: "Landlord@123" },
    });
    if (json.access_token) return json.access_token;
    if (status !== 429) throw new Error(`landlord login: HTTP ${status}`);
    await new Promise((r) => setTimeout(r, 20000));
  }
  throw new Error("landlord login: rate limited");
}

/** The OTP a tenant would read off their phone, from the simulated-SMS log. */
function latestOtpFrom(logPath, sinceBytes) {
  const buf = fs.readFileSync(logPath, "utf8").slice(sinceBytes);
  const codes = [...buf.matchAll(/login code is (\d{4,8})/g)].map((m) => m[1]);
  return codes.at(-1) || null;
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

const token = await landlordToken();

// ---------------------------------------------------------------------------
section("Set up: a lease sent to the tenant, and a maintenance request with a photo");

const tenants = await api("/tenants/?per_page=5", { token });
const tenantList = tenants.json?.tenants || tenants.json?.data?.tenants || [];
const tenant = tenantList.find((t) => t.phone && t.phone.includes("711000001")) || tenantList[0];
say(Boolean(tenant), "Found a tenant to act as", tenant?.first_name);

const created = await api(`/tenants/${tenant.id}/leases`, { token, method: "POST", body: {} });
const leaseId = (created.json?.data ?? created.json)?.id;
say(Boolean(leaseId), "Landlord created a lease", `id ${leaseId}`);
const sent = await api(`/leases/${leaseId}/send`, { token, method: "POST", body: {} });
say(sent.status === 200, "Landlord sent it to the tenant");

// ---------------------------------------------------------------------------
section("TENANT — signs in with a real OTP");

// The PAGE must be the thing that requests the code. Verification matches the
// most recent unused token for the identifier, so requesting one here and then
// letting the page request another supersedes the code we read — which looks
// exactly like "the OTP is broken" and is entirely the test's fault.
await page.goto(`${WEB}/tenant/login`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(900);

await page.locator('input[name="identifier"]').first().fill(TENANT_PHONE);

const sinceBytes = fs.statSync(API_LOG).size;
await page.getByRole("button", { name: /send code/i }).first().click();
await page.waitForTimeout(2200);

const code = latestOtpFrom(API_LOG, sinceBytes);
say(Boolean(code), "Code arrived on the tenant's phone (simulated SMS)", code || "not found");

// Six single-character boxes.
const otpBoxes = page.locator('input[maxlength="1"]');
for (let i = 0; i < code.length; i += 1) {
  await otpBoxes.nth(i).fill(code[i]);
}
await page.waitForTimeout(500);
await page.getByRole("button", { name: /verify/i }).first().click();

await page.waitForURL(/\/portal/, { timeout: 20000 }).catch(() => {});
say(/\/portal/.test(page.url()), "Tenant reached their portal", page.url());

// ---------------------------------------------------------------------------
section("TENANT — the lease is actually visible and signable");

await page.goto(`${WEB}/portal/lease`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2200);
let body = await page.locator("body").innerText();

say(/TENANCY AGREEMENT/i.test(body), "The lease the landlord just sent is on screen");
say(!/no lease|nothing to sign/i.test(body), "It does not say there is no lease");
const canSign = /agree|sign/i.test(body);
say(canSign, "The tenant is offered a way to sign it");

// ---------------------------------------------------------------------------
section("TENANT — messages and maintenance are reachable");

await page.goto(`${WEB}/portal/messages`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1800);
body = await page.locator("body").innerText();
say(!/error|something went wrong/i.test(body) && body.length > 200,
    "Messages page renders for the tenant");

await page.goto(`${WEB}/portal/maintenance`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1800);
body = await page.locator("body").innerText();
say(!/error|something went wrong/i.test(body) && body.length > 200,
    "Maintenance page renders for the tenant");

say(errors.length === 0, "No uncaught errors in the tenant portal", errors[0]?.slice(0, 80) || "");

// ---------------------------------------------------------------------------
section("OFFICE — maintenance detail shows the photo and takes a note");

const office = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const officePage = await office.newPage();
const officeErrors = [];
officePage.on("pageerror", (e) => officeErrors.push(e.message));

await officePage.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
await officePage.locator('input[name="email"]').fill("landlord@sahilpay.test");
await officePage.locator('input[name="password"]').fill("Landlord@123");
await officePage.getByRole("button", { name: "Log in" }).click();
await officePage.waitForURL(/\/landlord/, { timeout: 25000 });

await officePage.goto(`${WEB}/landlord/maintenance`, { waitUntil: "domcontentloaded" });
await officePage.waitForTimeout(2200);
body = await officePage.locator("main").innerText();
say(/Maintenance/i.test(body), "Maintenance list loads");

const firstRequest = officePage.locator("table button").first();
if (await firstRequest.count()) {
  await firstRequest.click();
  await officePage.waitForTimeout(1800);
  const dialog = await officePage.locator("body").innerText();
  say(/Photo/i.test(dialog), "The detail view has a Photo section");
  say(/Notes/i.test(dialog), "…and a Notes thread");
  say(/Internal note|hide from the tenant/i.test(dialog),
      "…with the internal-note option");
} else {
  say(false, "Could not open a maintenance request", "no rows");
}
say(officeErrors.length === 0, "No uncaught errors on maintenance",
    officeErrors[0]?.slice(0, 80) || "");

// ---------------------------------------------------------------------------
section("OFFICE — the eTIMS control-number importer");

await officePage.goto(`${WEB}/landlord/etims-register/import`, { waitUntil: "domcontentloaded" });
await officePage.waitForTimeout(2200);
body = await officePage.locator("main").innerText();
say(/Import eTIMS numbers/i.test(body), "The importer page loads");
say(/nothing here is guessed/i.test(body),
    "It states that matches are never guessed");
say(/Read the file/i.test(body), "It offers the upload step");

await browser.close();

const failed = results.filter((r) => !r.ok);
console.log("\n" + "=".repeat(64));
console.log(`${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) {
  console.log("\nFailures:");
  for (const f of failed) console.log(`  ${f.label} — ${f.detail}`);
}
process.exit(failed.length ? 1 : 0);
