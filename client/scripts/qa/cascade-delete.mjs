/**
 * Item 3 — property → units → tenants cascade, in the browser, plus the redeploy
 * clean-up of tenants left behind by property deletes made BEFORE this release.
 *
 *   QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/cascade-delete.mjs
 */
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import { BASE, api, apiLogin, results, shooter, staffLogin, dismissTours } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execSync(`psql "${DB}" -tAc "${q.replace(/"/g, '\\"')}"`).toString().trim();
const R = results();
const EMAIL = "sunrise@sahilpay.test";
const PASSWORD = "Sunrise@123";
const tag = `CQ${Date.now().toString().slice(-5)}`;

async function buildBlock(token, name) {
  const p = await api("/properties/", { token, method: "POST", body: { name, city: "Nairobi" } });
  const pid = p.json?.id ?? p.json?.property?.id;
  const ids = [];
  for (let i = 1; i <= 3; i++) {
    const u = await api(`/properties/${pid}/units`, { token, method: "POST", body: { name: `${name}-U${i}`, rent_amount: 9000 } });
    const unit = Array.isArray(u.json) ? u.json[0] : (u.json?.units ?? [u.json?.unit ?? u.json])[0];
    const t = await api("/tenants/", { token, method: "POST", body: {
      unit_id: unit.id, first_name: tag, last_name: `${name.slice(-2)}T${i}`, phone: `07${String(10000000 + Math.floor(Math.random() * 89999999))}` } });
    ids.push({ unit: unit.id, tenant: t.json?.id });
  }
  return { pid, ids };
}

const liveTenants = (pid) => Number(sql(`SELECT count(*) FROM tenants t JOIN units u ON u.id=t.unit_id WHERE u.property_id=${pid} AND NOT t.is_deleted`));
const liveUnits = (pid) => Number(sql(`SELECT count(*) FROM units WHERE property_id=${pid} AND NOT is_deleted`));

async function rowAction(page, text, action) {
  const row = page.locator("tr", { hasText: text }).first();
  await row.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: action }).or(page.getByText(action, { exact: true })).first().click();
}

// The dev copy of this account owes a subscription balance and is locked; clear it.
const SLID = sql(`SELECT l.id FROM landlords l JOIN users u ON u.id=l.user_id WHERE u.email='${EMAIL}'`);
sql(`UPDATE subscriptions SET amount_due=0, balance_due_since=NULL, status='active' WHERE landlord_id=${SLID}`);

const browser = await chromium.launch();
try {
  const token = await apiLogin(EMAIL, PASSWORD);
  const A = await buildBlock(token, `${tag} Block A`);
  R.check("setup: block A has 3 units and 3 tenants", liveUnits(A.pid) === 3 && liveTenants(A.pid) === 3);

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const shot = shooter(page, "cascade");
  await staffLogin(page, EMAIL, PASSWORD);

  // 1. Delete a unit → its tenant goes, the property stays.
  await page.goto(`${BASE}/landlord/units`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByPlaceholder(/search/i).first().fill(`${tag} Block A-U1`);
  await page.waitForTimeout(1500);
  await rowAction(page, `${tag} Block A-U1`, "Delete");
  await page.getByText(/together with the tenant living in it/).waitFor({ timeout: 10000 });
  await shot("delete-unit-warning", { fullPage: false });
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.getByText(/with its 1 tenant/).waitFor({ timeout: 15000 });
  await shot("unit-deleted-with-tenant", { fullPage: false });
  R.check("deleting a unit removes its tenant", liveTenants(A.pid) === 2 && liveUnits(A.pid) === 2);
  R.check("…and the property stays", sql(`SELECT is_deleted FROM properties WHERE id=${A.pid}`) === "f");

  // 2. Delete a tenant → unit and property stay.
  await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "domcontentloaded" });
  await page.getByPlaceholder(/search/i).first().fill(tag);
  await page.waitForTimeout(1500);
  await rowAction(page, `AT2`, "Delete");
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.waitForTimeout(1500);
  R.check("deleting a tenant keeps the unit and property", liveTenants(A.pid) === 1 && liveUnits(A.pid) === 2
    && sql(`SELECT is_occupied FROM units WHERE id=${A.ids[1].unit}`) === "f");

  // 3. Delete the property → every unit and tenant goes.
  await page.goto(`${BASE}/landlord/properties`, { waitUntil: "domcontentloaded" });
  await page.getByPlaceholder(/search/i).first().fill(`${tag} Block A`);
  await page.waitForTimeout(1500);
  await rowAction(page, `${tag} Block A`, "Delete");
  await page.getByText(/together with ALL of its units/).waitFor({ timeout: 10000 });
  await shot("delete-property-warning", { fullPage: false });
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.getByText(/has been deleted, with its/).waitFor({ timeout: 15000 });
  await shot("property-deleted-with-units-and-tenants", { fullPage: false });
  R.check("deleting the property removes all its units and tenants", liveUnits(A.pid) === 0 && liveTenants(A.pid) === 0);
  await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "domcontentloaded" });
  await page.getByPlaceholder(/search/i).first().fill(tag);
  await page.waitForTimeout(1500);
  await shot("tenants-page-no-headless-tenants", { fullPage: false });
  R.check("no headless tenants left on the Tenants page", await page.getByText(/No tenants|0 results|No results/i).first().isVisible().catch(() => false)
    || (await page.locator("tr", { hasText: tag }).count()) === 0);

  // 4. The live account's situation: properties deleted by the OLD code, tenants left live.
  const B = await buildBlock(token, `${tag} Block B`);
  sql(`UPDATE properties SET is_deleted=true, deleted_at=now() WHERE id=${B.pid}`);   // what the old delete did
  R.check("old-style delete leaves 3 headless tenants in the database", liveTenants(B.pid) === 3 && liveUnits(B.pid) === 3);
  // Redeploy: re-run this release's migration exactly as `flask db upgrade` will on the server.
  const env = "APP_ENV=development FLASK_APP=app.py";
  execSync(`cd ../server && ${env} venv/bin/flask db downgrade ah1b2c3d4e5f && ${env} venv/bin/flask db upgrade`, { stdio: "pipe" });
  R.check("after the redeploy migration: no headless units or tenants", liveTenants(B.pid) === 0 && liveUnits(B.pid) === 0);
  const orphans = sql(`SELECT count(*) FROM tenants t JOIN units u ON u.id=t.unit_id JOIN properties p ON p.id=u.property_id
    WHERE NOT t.is_deleted AND (u.is_deleted OR p.is_deleted)`);
  R.check("no headless tenants anywhere in the database", orphans === "0", `${orphans} left`);
} catch (err) {
  R.check("walkthrough ran to completion", false, err.message);
} finally {
  await browser.close();
}
process.exit(R.summary() ? 1 : 0);
