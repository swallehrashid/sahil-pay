/**
 * Item 1 — every form dropdown offers ALL properties / units / tenants (not the
 * first 20) and its search finds records far beyond the first page.
 * Runs against the scale estate (seed_scale.py): 100 properties, 1,000 units, ~1,000 tenants.
 *
 *   QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/dropdowns-scale.mjs
 */
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import { BASE, results, shooter, staffLogin, dismissTours } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execSync(`psql "${DB}" -tAc "${q.replace(/"/g, '\\"')}"`).toString().trim();
const EMAIL = process.env.QA_SCALE_EMAIL || "scale-pm@sahilpay.test";
const PASSWORD = process.env.QA_SCALE_PASSWORD || "ScaleTest123!";

const R = results();
const LID = sql(`SELECT l.id FROM landlords l JOIN users u ON u.id=l.user_id WHERE u.email='${EMAIL}'`);
const nProps = Number(sql(`SELECT count(*) FROM properties WHERE landlord_id=${LID} AND NOT is_deleted`));
const nTenants = Number(sql(`SELECT count(*) FROM tenants t JOIN units u ON u.id=t.unit_id JOIN properties p ON p.id=u.property_id
  WHERE t.landlord_id=${LID} AND NOT t.is_deleted AND NOT u.is_deleted AND NOT p.is_deleted`));
const lastProp = sql(`SELECT name FROM properties WHERE landlord_id=${LID} AND NOT is_deleted ORDER BY name DESC LIMIT 1`);
const [lastTenantFirst, lastTenantLast, lastTenantUnit] = sql(`SELECT t.first_name||'|'||t.last_name||'|'||u.name FROM tenants t JOIN units u ON u.id=t.unit_id
  WHERE t.landlord_id=${LID} AND NOT t.is_deleted ORDER BY t.first_name DESC, t.last_name DESC LIMIT 1`).split("|");
console.log(`landlord ${LID}: ${nProps} properties, ${nTenants} tenants; probe property "${lastProp}", tenant "${lastTenantFirst} ${lastTenantLast}" in ${lastTenantUnit}`);

const comboBox = (page, label) => page.getByRole("combobox", { name: new RegExp(`^${label}( \\*)?$`) }).last();

async function openCombo(page, label) {
  const combo = comboBox(page, label);
  await combo.click();
  await page.locator('[role="listbox"]').last().waitFor({ timeout: 15000 });
  return combo;
}
const optionCount = (page) => page.locator('[role="listbox"]').last().locator('[role="option"]').count();
async function search(page, text) {
  await page.locator('[role="searchbox"]').last().fill(text);
  await page.waitForTimeout(300);
}

const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const shot = shooter(page, "dropdowns");
  await staffLogin(page, EMAIL, PASSWORD);

  // Tenants → Add tenant → Property / Unit
  await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByRole("button", { name: "Add tenant" }).click();
  await openCombo(page, "Property");
  let n = await optionCount(page);
  await shot("add-tenant-property-dropdown-open", { fullPage: false });
  R.check(`Add tenant: property dropdown lists all ${nProps} properties (not 20)`, n === nProps, `${n} options`);
  await search(page, lastProp);
  n = await optionCount(page);
  await shot("add-tenant-property-search-last", { fullPage: false });
  R.check(`Add tenant: searching "${lastProp}" (last alphabetically) finds it`, n >= 1, `${n} match(es)`);
  await page.locator('[role="listbox"]').last().locator('[role="option"]', { hasText: lastProp }).first().click();
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  await page.keyboard.press("Escape");

  // Invoices → Add invoice → Tenant
  await page.goto(`${BASE}/landlord/invoices`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByRole("button", { name: "Add invoice" }).click();
  await openCombo(page, "Tenant");
  n = await optionCount(page);
  await shot("add-invoice-tenant-dropdown-open", { fullPage: false });
  R.check(`Add invoice: tenant dropdown lists all ${nTenants} tenants`, n === nTenants, `${n} options`);
  await search(page, `${lastTenantFirst} ${lastTenantLast}`);
  n = await optionCount(page);
  await shot("add-invoice-tenant-search", { fullPage: false });
  R.check(`Add invoice: search finds "${lastTenantFirst} ${lastTenantLast}" beyond the first page`, n >= 1, `${n} match(es)`);
  await search(page, lastTenantUnit);
  n = await optionCount(page);
  R.check(`Add invoice: tenant search also matches by unit "${lastTenantUnit}"`, n >= 1, `${n} match(es)`);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");

  // Payments → Record payment → Tenant
  await page.goto(`${BASE}/landlord/payments`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByRole("button", { name: "Record payment" }).first().click();
  await openCombo(page, "Tenant");
  n = await optionCount(page);
  await shot("record-payment-tenant-dropdown", { fullPage: false });
  R.check(`Record payment: tenant dropdown lists all ${nTenants} tenants`, n === nTenants, `${n} options`);
  await search(page, `${lastTenantFirst} ${lastTenantLast}`);
  await page.locator('[role="listbox"]').last().locator('[role="option"]').first().click();
  await page.waitForTimeout(1500);
  await shot("record-payment-tenant-selected", { fullPage: false });
  R.check("Record payment: a tenant beyond the first page can be selected",
    (await comboBox(page, "Tenant").textContent()).includes(lastTenantLast));
  await page.keyboard.press("Escape");

  // Utilities → Bulk upload → Property, then its units
  await page.goto(`${BASE}/landlord/utilities`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByRole("button", { name: "Bulk upload" }).click();
  await openCombo(page, "Property");
  n = await optionCount(page);
  await shot("bulk-utilities-property-dropdown", { fullPage: false });
  R.check(`Bulk utilities: property dropdown lists all ${nProps} properties`, n === nProps, `${n} options`);
  await search(page, lastProp);
  await page.locator('[role="listbox"]').last().locator('[role="option"]').first().click();
  await openCombo(page, "Utility");
  await page.locator('[role="listbox"]').last().locator('[role="option"]').first().click();
  await page.getByRole("button", { name: /Next: record readings/ }).click();
  await page.waitForTimeout(800);
  const unitsInProp = Number(sql(`SELECT count(*) FROM units u JOIN properties p ON p.id=u.property_id WHERE p.landlord_id=${LID} AND p.name='${lastProp.replace(/'/g, "''")}' AND NOT u.is_deleted`));
  const rows = await page.locator(".glass-input.col-span-4, .glass-input").count();
  await shot("bulk-utilities-units-of-last-property", { fullPage: false });
  R.check(`Bulk utilities: every unit of "${lastProp}" is listed (${unitsInProp})`, rows >= unitsInProp, `${rows} inputs`);
  await page.keyboard.press("Escape");

  // Units → Add unit → Property
  await page.goto(`${BASE}/landlord/units`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByRole("button", { name: "Add unit" }).click();
  await openCombo(page, "Property");
  n = await optionCount(page);
  await shot("add-unit-property-dropdown", { fullPage: false });
  R.check(`Add unit: property dropdown lists all ${nProps} properties`, n === nProps, `${n} options`);
} catch (err) {
  R.check("walkthrough ran to completion", false, err.message);
} finally {
  await browser.close();
}
process.exit(R.summary() ? 1 : 0);
