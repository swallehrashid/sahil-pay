/**
 * _diag-five.mjs — reproduce the five reported faults through the real UI.
 *
 *   1. Landlord/team send a lease  → does the tenant portal show it?
 *   2. Tenant messages             → do they go both ways?
 *   3. Tenant maintenance photo    → does it reach the office?
 *   4. Recorded-payout statement   → does the button produce a PDF?
 *   5. Payout "Collected" picker   → does it exist at all?
 *
 * Everything is driven from the browser, as a person would: no injected
 * tokens, no direct API calls standing in for a click.
 */

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const WEB = process.env.WEB_URL || "http://localhost:5173";
const API = process.env.API_URL || "http://localhost:5000/api";
const API_LOG = process.env.API_LOG || "/tmp/sahilpay-api.log";
const OUT = process.env.OUT || "/tmp/claude-1000/-home-swalleh-Projects-sahil-pay/4a37e537-178b-4756-bd97-a07fec94c113/scratchpad/diag";
const TENANT_PHONE = "+254711000001";

fs.mkdirSync(OUT, { recursive: true });

const results = [];
const say = (ok, label, detail = "") => {
  results.push({ ok, label, detail });
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};
const section = (n) => console.log(`\n${n}`);
const shot = (page, name) => page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true }).catch(() => {});

function latestOtp(sinceBytes) {
  const buf = fs.readFileSync(API_LOG, "utf8").slice(sinceBytes);
  return [...buf.matchAll(/login code is (\d{4,8})/g)].map((m) => m[1]).at(-1) || null;
}

async function staffLogin(page, email, password, expect) {
  await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: /log in/i }).first().click();
  await page.waitForURL(new RegExp(expect), { timeout: 25000 }).catch(() => {});
  return new RegExp(expect).test(page.url());
}

async function tenantLogin(page) {
  await page.goto(`${WEB}/tenant/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(800);
  await page.locator('input[name="identifier"]').first().fill(TENANT_PHONE);
  const since = fs.statSync(API_LOG).size;
  await page.getByRole("button", { name: /send code/i }).first().click();
  await page.waitForTimeout(2200);
  const code = latestOtp(since);
  if (!code) return false;
  const boxes = page.locator('input[maxlength="1"]');
  for (let i = 0; i < code.length; i += 1) await boxes.nth(i).fill(code[i]);
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /verify/i }).first().click();
  await page.waitForURL(/\/portal/, { timeout: 20000 }).catch(() => {});
  return /\/portal/.test(page.url());
}

const browser = await chromium.launch();
const ctx = (w = 1440, h = 1000) => browser.newContext({ viewport: { width: w, height: h } });

// ===========================================================================
section("1 — LANDLORD sends a lease from the Leases page");

const office = await ctx();
const officePage = await office.newPage();
const officeErrors = [];
officePage.on("pageerror", (e) => officeErrors.push(e.message));
const officeFailed = [];
officePage.on("response", (r) => {
  if (r.status() >= 400 && r.url().includes("/api/")) officeFailed.push(`${r.status()} ${r.url().replace(API, "")}`);
});

say(await staffLogin(officePage, "landlord@sahilpay.test", "Landlord@123", "/landlord"),
    "Landlord signed in", officePage.url());

await officePage.goto(`${WEB}/landlord/leases`, { waitUntil: "domcontentloaded" });
await officePage.waitForTimeout(2500);
say(/Lease agreements/i.test(await officePage.locator("main").innerText()), "Leases page loads");

await officePage.getByRole("button", { name: /prepare a lease/i }).click();
await officePage.waitForTimeout(900);

// The tenant dropdown — pick James Mwangi, the phone we sign in as.
const sel = officePage.locator('select').last();
const options = await sel.locator("option").allTextContents();
say(options.length > 0, "Prepare modal lists tenants", `${options.length}: ${options.slice(0, 4).join(" | ")}`);
const james = options.findIndex((o) => /james/i.test(o));
await sel.selectOption({ index: james >= 0 ? james : 0 });
const chosen = options[james >= 0 ? james : 0];

const sendNow = officePage.locator('input[type="checkbox"]').first();
say(await sendNow.isChecked(), '"Send it to the tenant" is ticked by default');
await shot(officePage, "01-prepare-modal");
await officePage.getByRole("button", { name: /^Prepare$/ }).click();
await officePage.waitForTimeout(2600);
const afterPrepare = await officePage.locator("body").innerText();
say(/Prepared and sent/i.test(afterPrepare), "Landlord got the “prepared and sent” confirmation");
await shot(officePage, "02-leases-after-send");

const listText = await officePage.locator("main").innerText();
say(/With the tenant/i.test(listText), 'The list shows the lease as "With the tenant"');
say(officeFailed.length === 0, "No failing API calls while sending", officeFailed.slice(0, 3).join("; "));

// ===========================================================================
section("2 — TENANT opens the portal and looks for that lease");

const tctx = await ctx(390, 844);
const tpage = await tctx.newPage();
const tErrors = [];
tpage.on("pageerror", (e) => tErrors.push(e.message));
const tFailed = [];
tpage.on("response", (r) => {
  if (r.status() >= 400 && r.url().includes("/api/")) tFailed.push(`${r.status()} ${r.url().replace(API, "")}`);
});

say(await tenantLogin(tpage), "Tenant signed in with a real OTP", tpage.url());
say(/james/i.test(chosen), "…and it is the same person the lease was prepared for", chosen);

// Reach the lease the way a tenant would: the nav bar, not a typed URL.
await tpage.locator("header nav a").first().waitFor({ timeout: 15000 }).catch(() => {});
const leaseLink = tpage.locator('a[href$="/portal/lease"]').first();
say(await leaseLink.count() > 0, "There is a Lease link in the tenant nav");
const navNames = await tpage.locator("header nav a").evaluateAll(
  (els) => els.map((e) => (e.innerText || "").trim()).filter(Boolean));
say(navNames.length > 0, "Tenant nav links are readable on a phone",
    navNames.length ? navNames.join(", ") : "every nav link is icon-only — no text, no aria-label");
if (await leaseLink.count()) { await leaseLink.click(); await tpage.waitForTimeout(2800); }
else { await tpage.goto(`${WEB}/portal/lease`, { waitUntil: "domcontentloaded" }); await tpage.waitForTimeout(2800); }
await shot(tpage, "03-tenant-lease");
let tbody = await tpage.locator("body").innerText();
say(/TENANCY AGREEMENT/i.test(tbody), "The lease body is on screen for the tenant");
say(!/No agreement yet/i.test(tbody), 'It does not say "No agreement yet"');
say(/Sign and submit/i.test(tbody), "The tenant is offered the signing form");

// Actually sign it.
if (/Sign and submit/i.test(tbody)) {
  await tpage.getByLabel(/your full name/i).fill("James Mwangi");
  await tpage.locator('input[type="checkbox"]').first().check();
  await tpage.getByRole("button", { name: /sign and submit/i }).click();
  await tpage.waitForTimeout(2600);
  tbody = await tpage.locator("body").innerText();
  say(/with your landlord for review|Signed/i.test(tbody), "Signing succeeded", tbody.slice(0, 90).replace(/\n/g, " "));
  await shot(tpage, "04-tenant-signed");
}

// ===========================================================================
section("2b — LANDLORD approves, tenant downloads");

await officePage.goto(`${WEB}/landlord/leases`, { waitUntil: "domcontentloaded" });
await officePage.waitForTimeout(2500);
say(/Needs review/i.test(await officePage.locator("main").innerText()),
    "The signed lease appears in the landlord's review queue");
const approve = officePage.getByRole("button", { name: /^Approve$/ }).first();
if (await approve.count()) {
  await approve.click();
  await officePage.waitForTimeout(3000);
  say(/Lease approved/i.test(await officePage.locator("body").innerText()), "Landlord approved it");
} else say(false, "Landlord could not find an Approve button");

await tpage.reload({ waitUntil: "domcontentloaded" });
await tpage.waitForTimeout(2800);
tbody = await tpage.locator("body").innerText();
say(/approved/i.test(tbody), "Tenant sees it approved");
const dl = tpage.getByRole("button", { name: /download my copy/i });
say(await dl.count() > 0, "Tenant is offered the download");
if (await dl.count()) {
  const dlp = tpage.waitForEvent("download", { timeout: 15000 }).catch(() => null);
  await dl.click();
  const got = await dlp;
  say(Boolean(got), "The download actually produced a file", got ? await got.suggestedFilename() : "no download event");
}
await shot(tpage, "05-tenant-approved");

// ===========================================================================
section("3 — TENANT messages, both directions");

await tpage.goto(`${WEB}/portal/messages`, { waitUntil: "domcontentloaded" });
await tpage.waitForTimeout(2600);
await shot(tpage, "06-tenant-messages");
tbody = await tpage.locator("body").innerText();
say(/Messages/i.test(tbody), "Messages page renders");
const stamp = `diag-${Date.now()}`;
const ta = tpage.locator("textarea").first();
say(await ta.count() > 0, "There is a message box");
if (await ta.count()) {
  await ta.fill(`Tenant test ${stamp}`);
  await tpage.getByRole("button", { name: /^Send$/ }).click();
  await tpage.waitForTimeout(2600);
  tbody = await tpage.locator("body").innerText();
  say(tbody.includes(stamp), "The tenant's message appears in their own thread");
  say(/Message sent/i.test(tbody), "…and was confirmed sent");
}
await shot(tpage, "07-tenant-message-sent");

await officePage.goto(`${WEB}/landlord/messages`, { waitUntil: "domcontentloaded" });
await officePage.waitForTimeout(2800);
let obody = await officePage.locator("body").innerText();
say(obody.includes(stamp) || /James/i.test(obody), "The landlord inbox lists the tenant thread");
const thread = officePage.getByText(/James/i).first();
if (await thread.count()) { await thread.click(); await officePage.waitForTimeout(2200); }
obody = await officePage.locator("body").innerText();
say(obody.includes(stamp), "The landlord can read the tenant's message");
await shot(officePage, "08-landlord-inbox");

const reply = `Landlord reply ${stamp}`;
const rta = officePage.locator("textarea").first();
if (await rta.count()) {
  await rta.fill(reply);
  await officePage.getByRole("button", { name: /send|reply/i }).last().click();
  await officePage.waitForTimeout(2600);
  say((await officePage.locator("body").innerText()).includes(reply), "The landlord's reply posted");
} else say(false, "No reply box on the landlord inbox");

await tpage.reload({ waitUntil: "domcontentloaded" });
await tpage.waitForTimeout(3000);
tbody = await tpage.locator("body").innerText();
say(tbody.includes(reply), "The tenant sees the landlord's reply");
say(tFailed.length === 0, "No failing API calls in the tenant portal", tFailed.slice(0, 4).join("; "));
await shot(tpage, "09-tenant-sees-reply");

// ===========================================================================
section("4 — TENANT raises a maintenance request WITH a photo");

const photo = path.join(OUT, "leak.png");
fs.writeFileSync(photo, Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAHElEQVQoz2P8z8Dwn4GKgIlhFI" +
  "yCUTAKRsEoGAUAAB9UAgFR7hHLAAAAAElFTkSuQmCC", "base64"));

await tpage.goto(`${WEB}/portal/maintenance`, { waitUntil: "domcontentloaded" });
await tpage.waitForTimeout(2400);
await tpage.getByRole("button", { name: /new request/i }).click();
await tpage.waitForTimeout(900);
const summary = `Leaking tap ${stamp}`;
await tpage.getByLabel(/^Summary/i).fill(summary);
await tpage.locator("textarea").first().fill("Water under the sink since Tuesday.");
const fileInput = tpage.locator('input[type="file"]').first();
say(await fileInput.count() > 0, "The form offers a photo upload");
await fileInput.setInputFiles(photo);
await tpage.waitForTimeout(600);
await shot(tpage, "10-tenant-maintenance-form");
await tpage.getByRole("button", { name: /submit request/i }).click();
await tpage.waitForTimeout(3000);
say(/submitted/i.test(await tpage.locator("body").innerText()), "The request was submitted");
await shot(tpage, "11-tenant-maintenance-list");

await officePage.goto(`${WEB}/landlord/maintenance`, { waitUntil: "domcontentloaded" });
await officePage.waitForTimeout(3000);
obody = await officePage.locator("main").innerText();
say(obody.includes(summary), "The office sees the new request");
const row = officePage.getByText(summary).first();
if (await row.count()) {
  await row.click();
  await officePage.waitForTimeout(2400);
  await shot(officePage, "12-office-maintenance-detail");
  const imgs = await officePage.locator('[role="dialog"] img, dialog img').count();
  const dtext = await officePage.locator("body").innerText();
  say(imgs > 0, "The tenant's photo is displayed to the office",
      imgs === 0 ? (/No photo|no photo/i.test(dtext) ? 'shows "no photo"' : "no <img> in the dialog") : "");
} else say(false, "Could not open the request in the office");

// ===========================================================================
section("5 — TEAM MEMBER does the same lease job");

const team = await ctx();
const teamPage = await team.newPage();
const teamFailed = [];
teamPage.on("response", (r) => {
  if (r.status() >= 400 && r.url().includes("/api/")) teamFailed.push(`${r.status()} ${r.url().replace(API, "")}`);
});
say(await staffLogin(teamPage, "caretaker@sahilpay.test", "Caretaker@123", "/team"),
    "Team member signed in", teamPage.url());
// Wait for the sidebar to hydrate — it is rendered from the member's
// permission matrix, which arrives after the first paint.
await teamPage.locator('a[href^="/team"]').first().waitFor({ timeout: 15000 }).catch(() => {});
await teamPage.waitForTimeout(2500);
const teamLeaseLink = teamPage.locator('a[href$="/team/leases"]');
say(await teamLeaseLink.count() > 0, "Leases is in the team member's sidebar");
await teamPage.goto(`${WEB}/team/leases`, { waitUntil: "domcontentloaded" });
await teamPage.waitForTimeout(2800);
const ttext = await teamPage.locator("body").innerText();
say(/Lease agreements/i.test(ttext), "Team member can open the Leases page");
say(teamFailed.filter((f) => f.includes("lease")).length === 0,
    "…and the lease API answers them", teamFailed.slice(0, 3).join("; "));
await shot(teamPage, "13-team-leases");

// ===========================================================================
section("6 — PAYOUTS: the statement button and the Collected picker");

await officePage.goto(`${WEB}/landlord/payouts`, { waitUntil: "domcontentloaded" });
await officePage.waitForTimeout(3200);
await shot(officePage, "14-payouts");
obody = await officePage.locator("main").innerText();
say(/Owner payouts/i.test(await officePage.locator("body").innerText()), "Payouts page loads");
say(/Recorded payouts/i.test(obody), "The recorded-payouts table is present");

await officePage.locator('input[type="date"]').first().fill("2026-01-01");
await officePage.waitForTimeout(2600);
const genButton = officePage.getByRole("button", { name: /generate payouts/i });
if (await genButton.isEnabled()) {
  await genButton.click();
  await officePage.waitForTimeout(4000);
}
obody = await officePage.locator("main").innerText();

const stmt = officePage.getByRole("button", { name: /statement/i }).first();
say(await stmt.count() > 0, "A recorded payout offers a Statement button");
if (await stmt.count()) {
  const before = officePage.context().pages().length;
  const dlp = officePage.waitForEvent("download", { timeout: 8000 }).catch(() => null);
  await stmt.click();
  await officePage.waitForTimeout(4000);
  const got = await dlp;
  const pages = officePage.context().pages();
  const opened = pages.length > before ? pages[pages.length - 1] : null;
  let openedUrl = opened ? opened.url() : "";
  let openedText = "";
  if (opened) { await opened.waitForTimeout(1500); openedText = await opened.locator("body").innerText().catch(() => ""); }
  say(Boolean(got), "The Statement button produced a PDF download",
      got ? await got.suggestedFilename() : `no download; opened ${openedUrl || "nothing"} — ${openedText.slice(0, 70).replace(/\n/g, " ")}`);
}

// Does a way to choose what counts as "Collected" exist?
const checkboxes = await officePage.locator('input[type="checkbox"]').count();
say(checkboxes > 0, "There is a way to choose what goes into Collected", `${checkboxes} checkboxes on the page`);
say(/rent only|commission basis|total collected/i.test(obody),
    "There is a commission-basis toggle before Generate");

await browser.close();

console.log("\n" + "=".repeat(70));
const failed = results.filter((r) => !r.ok);
console.log(`${results.length - failed.length}/${results.length} checks passed   (screenshots in ${OUT})`);
if (failed.length) {
  console.log("\nFAILURES:");
  for (const f of failed) console.log(`  • ${f.label}${f.detail ? ` — ${f.detail}` : ""}`);
}
