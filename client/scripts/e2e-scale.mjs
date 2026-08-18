/**
 * e2e-scale.mjs — drive the real UI against the 1,000-unit estate.
 *
 * The unit tests prove the logic and scale_audit.py proves the arithmetic. This
 * proves the third thing neither can: that the screens a property manager,
 * an accountant, a caretaker and a property owner actually open still work when
 * the account holds 100 properties, 943 tenants and four months of history —
 * and, just as importantly, that each of those people sees only what they
 * should.
 *
 * A permission bug is invisible on a three-tenant fixture. At this size it is
 * the difference between an owner seeing their own block and an owner reading
 * their competitors' books.
 *
 *   node scripts/e2e-scale.mjs        (stack must be pointed at sahilpay_scale)
 */

import { chromium } from "playwright";

const WEB = process.env.WEB_URL || "http://localhost:5173";
const API = process.env.API_URL || "http://localhost:5000/api";
const PASSWORD = "ScaleTest123!";

const results = [];
function say(ok, label, detail = "") {
  results.push({ ok, label, detail });
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
}
function section(name) {
  console.log(`\n${name}`);
}

const tokens = new Map();
async function api(path, { token, method = "GET", body } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, json: await res.json().catch(() => ({})) };
}

async function tokenFor(email) {
  if (tokens.has(email)) return tokens.get(email);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const { status, json } = await api("/auth/login", {
      method: "POST", body: { email, password: PASSWORD },
    });
    if (json.access_token) {
      tokens.set(email, json.access_token);
      return json.access_token;
    }
    if (status !== 429) throw new Error(`${email}: HTTP ${status}`);
    console.log(`        (rate limited as ${email} — waiting 20s)`);
    await new Promise((r) => setTimeout(r, 20000));
  }
  throw new Error(`${email}: still rate limited`);
}

async function signIn(page, email) {
  // Login is capped at 5/minute per IP. This script authenticates five accounts
  // and the cap is correct, so wait it out rather than reporting the app broken
  // — and surface whatever the screen actually says if it is something else.
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill(PASSWORD);
    await page.getByRole("button", { name: "Log in" }).click();
    try {
      await page.waitForURL(/\/(landlord|team)/, { timeout: 12000 });
      await page.waitForTimeout(1200);
      return;
    } catch {
      // The refusal is usually the rate limiter, and its toast has often faded
      // by the time innerText is sampled — so retry regardless of what the
      // screen currently says, and only report the text once retries run out.
      const last = attempt === 3;
      if (last) {
        const shown = await page.locator("body").innerText().catch(() => "");
        throw new Error(
          `${email} did not reach a portal after 4 attempts. Screen said: ` +
          `${shown.replace(/\s+/g, " ").slice(0, 140)}`
        );
      }
      console.log(`        (sign-in as ${email} did not land — waiting 25s and retrying)`);
      await new Promise((r) => setTimeout(r, 25000));
    }
  }
  throw new Error(`${email}: still rate limited after retries`);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message));

// ---------------------------------------------------------------------------
section("SCALE — the manager's own screens");

const pmToken = await tokenFor("scale-pm@sahilpay.test");

const props = await api("/properties/?per_page=200", { token: pmToken });
const propList = props.json?.properties || props.json?.data?.properties || [];
say(propList.length >= 100, "Property list returns the whole book", `${propList.length} properties`);

const tenantsRes = await api("/tenants/?per_page=1", { token: pmToken });
const tenantTotal = tenantsRes.json?.total ?? tenantsRes.json?.data?.total;
say(tenantTotal > 900, "Tenant list paginates a nine-hundred-tenant book", `${tenantTotal} tenants`);

// A report over four months of 943 tenants is the slowest thing in the product.
const started = Date.now();
const statement = await api(`/reports/statements/property/${propList[0].id}`, { token: pmToken });
const elapsed = Date.now() - started;
say(statement.status === 200, "Property statement renders at scale", `HTTP ${statement.status}, ${elapsed}ms`);
say(elapsed < 15000, "…and returns in a usable time", `${elapsed}ms`);

const arrears = await api("/reports/statements/arrears", { token: pmToken });
say(arrears.status === 200, "Arrears report renders across every property");

// ---------------------------------------------------------------------------
section("SCALE — the UI a manager actually opens");

await signIn(page, "scale-pm@sahilpay.test");
let body = await page.locator("main").innerText();
say(body.length > 100, "Dashboard renders for the manager");

for (const [label, route, expect] of [
  ["Properties", "/landlord/properties", /Propert/i],
  ["Tenants", "/landlord/tenants", /Tenant/i],
  ["Invoices", "/landlord/invoices", /Invoice/i],
  ["Payments", "/landlord/payments", /Payment/i],
  ["Owner payouts", "/landlord/payouts", /payout/i],
  ["Penalties", "/landlord/reports/penalties", /Penalt/i],
  ["Bulk import", "/landlord/imports", /Bulk import/i],
  ["Reports", "/landlord/reports/statements", /Statement|Report/i],
]) {
  const before = pageErrors.length;
  await page.goto(`${WEB}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2200);
  const text = await page.locator("main").innerText();
  say(expect.test(text) && pageErrors.length === before, `${label} loads at scale`,
      pageErrors.length > before ? pageErrors[pageErrors.length - 1].slice(0, 70) : "");
}

// ---------------------------------------------------------------------------
section("SCALE — an owner sees only their own block");

const ownerToken = await tokenFor("owner001@scale.sahilpay.test");

const ownerProps = await api("/properties/?per_page=200", { token: ownerToken });
const ownerList = ownerProps.json?.properties || ownerProps.json?.data?.properties || [];
say(ownerList.length > 0 && ownerList.length < 5,
    "An owner sees their own property, not the portfolio",
    `${ownerList.length} of ${propList.length}`);

// The report they are entitled to...
const ownStatement = await api(`/reports/statements/property/${ownerList[0].id}`, { token: ownerToken });
say(ownStatement.status === 200, "An owner can pull their own property statement");

// ...and the ones they are not. This is #10 holding at 160 team members.
const ownerPayments = await api("/reports/payments", { token: ownerToken });
say(ownerPayments.status === 403, "An owner cannot open the payments report",
    `HTTP ${ownerPayments.status}`);
const ownerArrears = await api("/reports/statements/arrears", { token: ownerToken });
say(ownerArrears.status === 403, "An owner cannot open the portfolio arrears report",
    `HTTP ${ownerArrears.status}`);

// Another owner's block must be refused outright.
const foreign = propList.find((p) => !ownerList.some((o) => o.id === p.id));
const trespass = await api(`/reports/statements/property/${foreign.id}`, { token: ownerToken });
say([403, 404].includes(trespass.status),
    "An owner cannot read another owner's statement", `HTTP ${trespass.status}`);

// ---------------------------------------------------------------------------
section("SCALE — a caretaker records meter readings and nothing else");

const careToken = await tokenFor("caretaker001@scale.sahilpay.test");

const careCats = await api("/charge-categories/?kind=utility", { token: careToken });
say(careCats.status === 200, "A caretaker can load the utility categories",
    `HTTP ${careCats.status}`);
const careProps = await api("/properties/?per_page=200", { token: careToken });
say(careProps.status === 200, "A caretaker can load their properties for the form");

const careInvoices = await api("/invoices/", { token: careToken });
say(careInvoices.status === 403, "A caretaker cannot reach invoices", `HTTP ${careInvoices.status}`);
const carePayments = await api("/payments/", { token: careToken });
say(carePayments.status === 403, "A caretaker cannot reach payments", `HTTP ${carePayments.status}`);

// ---------------------------------------------------------------------------
section("SCALE — an accountant runs the money");

const acctEmail = "accountant001@scale.sahilpay.test";
let acctToken = null;
try {
  acctToken = await tokenFor(acctEmail);
} catch {
  say(false, "Accountant login exists", acctEmail);
}

if (acctToken) {
  const acctPayments = await api("/payments/", { token: acctToken });
  say(acctPayments.status === 200, "An accountant can reach payments");
  const acctReports = await api("/reports/payments", { token: acctToken });
  say(acctReports.status === 200, "An accountant can pull the payments report");
  const acctPenalties = await api("/penalties/batch/candidates", { token: acctToken });
  say(acctPenalties.status === 200, "An accountant can see who is in arrears for a penalty run");
  const acctSettings = await api("/team/", { token: acctToken });
  say(acctSettings.status === 403, "An accountant cannot manage the team",
      `HTTP ${acctSettings.status}`);
}

// ---------------------------------------------------------------------------
section("SCALE — a team member signs in and sees their own portal");

await context.clearCookies();
const teamPage = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
const teamErrors = [];
teamPage.on("pageerror", (e) => teamErrors.push(e.message));
await signIn(teamPage, "owner001@scale.sahilpay.test");
const sidebar = await teamPage.locator("aside").innerText();
say(!/Settings/.test(sidebar), "An owner's sidebar offers no Settings");
say(!/Bulk import/.test(sidebar), "An owner's sidebar offers no Bulk import");
say(/Reports/.test(sidebar), "An owner's sidebar does offer Reports");
say(teamErrors.length === 0, "No uncaught errors in the owner portal",
    teamErrors[0]?.slice(0, 70) || "");

await browser.close();

const failed = results.filter((r) => !r.ok);
console.log("\n" + "=".repeat(64));
console.log(`${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) {
  console.log("\nFailures:");
  for (const f of failed) console.log(`  ${f.label} — ${f.detail}`);
}
process.exit(failed.length ? 1 : 0);
