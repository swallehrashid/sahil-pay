/**
 * Item 2 — Backup & Delete on the scale estate (100 properties, 1,000 units,
 * 1,000 tenants, months of invoices and payments).
 *
 *   team member refused → owner: are you sure → password (wrong, then right)
 *   → type the phrase exactly → final warning → backup downloads → account empty.
 *   Then: no trace of the records anywhere in the database, and the account,
 *   settings, SMS balance, team and audit trail are still there.
 *
 * DESTRUCTIVE for the scale account — run it last.
 *   QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/backup-and-delete.mjs
 */
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { BASE, SHOTS, api, apiLogin, results, shooter, staffLogin, dismissTours } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execFileSync("psql", [DB, "-tAc", q]).toString().trim();
const R = results();
const OWNER = { email: "scale-pm@sahilpay.test", password: "ScaleTest123!" };
const LID = Number(sql(`SELECT l.id FROM landlords l JOIN users u ON u.id=l.user_id WHERE u.email='${OWNER.email}'`));

const scoped = {
  properties: `SELECT count(*) FROM properties WHERE landlord_id=${LID}`,
  units: `SELECT count(*) FROM units WHERE property_id IN (SELECT id FROM properties WHERE landlord_id=${LID})`,
  tenants: `SELECT count(*) FROM tenants WHERE landlord_id=${LID}`,
  invoices: `SELECT count(*) FROM invoices WHERE landlord_id=${LID}`,
  invoice_line_items: `SELECT count(*) FROM invoice_line_items WHERE invoice_id IN (SELECT id FROM invoices WHERE landlord_id=${LID})`,
  payments: `SELECT count(*) FROM payments WHERE landlord_id=${LID}`,
  payment_allocations: `SELECT count(*) FROM payment_allocations WHERE payment_id IN (SELECT id FROM payments WHERE landlord_id=${LID})`,
  utility_readings: `SELECT count(*) FROM utility_readings WHERE landlord_id=${LID}`,
  queued_charges: `SELECT count(*) FROM queued_charges WHERE landlord_id=${LID}`,
  expenses: `SELECT count(*) FROM expenses WHERE landlord_id=${LID}`,
  owner_payouts: `SELECT count(*) FROM owner_payouts WHERE landlord_id=${LID}`,
  property_owners: `SELECT count(*) FROM property_owners WHERE landlord_id=${LID}`,
  communication_logs: `SELECT count(*) FROM communication_logs WHERE landlord_id=${LID}`,
  credit_ledger: `SELECT count(*) FROM credit_ledger WHERE landlord_id=${LID}`,
  balance_rollovers: `SELECT count(*) FROM balance_rollovers WHERE landlord_id=${LID}`,
  lease_agreements: `SELECT count(*) FROM lease_agreements WHERE landlord_id=${LID}`,
  notifications: `SELECT count(*) FROM notifications WHERE landlord_id=${LID}`,
  team_property_access: `SELECT count(*) FROM team_member_property_access a JOIN team_members tm ON tm.id=a.team_member_id WHERE tm.landlord_id=${LID}`,
};
const kept = {
  landlord: `SELECT count(*) FROM landlords WHERE id=${LID}`,
  sms_balance: `SELECT sms_balance FROM landlords WHERE id=${LID}`,
  team_members: `SELECT count(*) FROM team_members WHERE landlord_id=${LID}`,
  team_permissions: `SELECT count(*) FROM team_member_permissions p JOIN team_members tm ON tm.id=p.team_member_id WHERE tm.landlord_id=${LID}`,
  charge_categories: `SELECT count(*) FROM charge_categories WHERE landlord_id=${LID}`,
  settings: `SELECT count(*) FROM landlord_settings WHERE landlord_id=${LID}`,
  automation: `SELECT count(*) FROM automation_settings WHERE landlord_id=${LID}`,
  subscription: `SELECT count(*) FROM subscriptions WHERE landlord_id=${LID}`,
};
const snap = (qs) => Object.fromEntries(Object.entries(qs).map(([k, q]) => [k, Number(sql(q))]));

const before = snap(scoped);
const keptBefore = snap(kept);
const tenantIds = sql(`SELECT string_agg(id::text, ',') FROM tenants WHERE landlord_id=${LID}`);
console.log("before:", JSON.stringify(before));

const browser = await chromium.launch();
try {
  R.check("the account is at scale before the wipe", before.properties >= 100 && before.units >= 1000 && before.tenants >= 1000,
    `${before.properties} properties, ${before.units} units, ${before.tenants} tenants, ${before.invoices} invoices, ${before.payments} payments`);

  // A team member — even with full access — cannot do this.
  const tmEmail = sql(`SELECT u.email FROM team_members tm JOIN users u ON u.id=tm.user_id WHERE tm.landlord_id=${LID} AND tm.preset='full_access' ORDER BY tm.id DESC LIMIT 1`)
    || sql(`SELECT u.email FROM team_members tm JOIN users u ON u.id=tm.user_id WHERE tm.landlord_id=${LID} ORDER BY tm.id LIMIT 1`);
  const tmToken = tmEmail.includes("qa.sahilpay.test") ? await apiLogin(tmEmail, "QaTeam123!") : await apiLogin(tmEmail, "ScaleTest123!");
  const tmTry = await api("/settings/wipe", { token: tmToken });
  R.check(`team member (${tmEmail}) is refused`, tmTry.status === 403, `HTTP ${tmTry.status}`);

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const shot = shooter(page, "backup-and-delete");
  await staffLogin(page, OWNER.email, OWNER.password);
  await page.goto(`${BASE}/landlord/settings/backup`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByTestId("backup-and-delete").scrollIntoViewIfNeeded();
  await shot("danger-zone", { fullPage: false });
  await page.getByTestId("wipe-open").click();

  await page.getByTestId("wipe-step-1").waitFor({ timeout: 20000 });
  await shot("step1-are-you-sure", { fullPage: false });
  R.check("step 1 shows what will be deleted", await page.getByTestId("wipe-step-1").getByText(/1,000\s*tenants/).isVisible());
  await page.getByTestId("wipe-step-1-yes").click();

  await page.getByTestId("wipe-password").fill("RealEstate254-wrong");
  await page.getByTestId("wipe-password-submit").click();
  await page.getByText("That password is not correct.").waitFor({ timeout: 10000 });
  await shot("step2-wrong-password", { fullPage: false });
  R.check("a wrong password stops it", true);
  await page.getByTestId("wipe-password").fill(OWNER.password);
  await page.getByTestId("wipe-password-submit").click();

  await page.getByTestId("wipe-step-3").waitFor({ timeout: 10000 });
  const phrase = (await page.getByTestId("wipe-phrase").textContent()).trim();
  await page.getByTestId("wipe-phrase-input").fill(phrase.toLowerCase());
  R.check("the phrase must match exactly (lower-case refused)", await page.getByTestId("wipe-phrase-ok").isDisabled());
  await page.getByTestId("wipe-phrase-input").fill(phrase);
  await shot("step3-typed-phrase", { fullPage: false });
  R.check(`phrase is "${phrase}"`, /^DELETE ACCOUNT SP-\d{5}$/.test(phrase));
  await page.getByTestId("wipe-phrase-ok").click();

  await page.getByTestId("wipe-step-4").waitFor({ timeout: 10000 });
  await shot("step4-final-warning", { fullPage: false });
  const t0 = Date.now();
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 600000 }),
    page.getByTestId("wipe-final").click(),
  ]);
  const file = `${SHOTS}/backup-and-delete/backup.xlsx`;
  await download.saveAs(file);
  await page.getByTestId("wipe-done").waitFor({ timeout: 600000 });
  await shot("step5-done");
  R.check("backup + delete finished", true, `${((Date.now() - t0) / 1000).toFixed(1)}s`);

  // The backup holds everything that was deleted.
  const sheets = JSON.parse(execFileSync("../server/venv/bin/python", ["-c",
    `import json,sys; from openpyxl import load_workbook; wb=load_workbook(sys.argv[1], read_only=True); print(json.dumps({ws.title: ws.max_row-1 for ws in wb.worksheets}))`, file]).toString());
  console.log("backup sheets:", JSON.stringify(sheets));
  R.check("backup: every property", sheets.Properties === before.properties, `${sheets.Properties}`);
  R.check("backup: every unit", sheets.Units === before.units, `${sheets.Units}`);
  R.check("backup: every tenant", sheets.Tenants === before.tenants, `${sheets.Tenants}`);
  R.check("backup: every invoice", sheets.Invoices === before.invoices, `${sheets.Invoices}`);
  R.check("backup: every invoice line", sheets["Invoice lines"] === before.invoice_line_items, `${sheets["Invoice lines"]}`);
  R.check("backup: every payment", sheets.Payments === before.payments, `${sheets.Payments}`);

  // Nothing left.
  const after = snap(scoped);
  console.log("after:", JSON.stringify(after));
  for (const [k, v] of Object.entries(after)) R.check(`deleted: ${k} (${before[k]} → ${v})`, v === 0);
  const traces = ["invoices", "payments", "communication_logs", "tenant_unit_history", "credit_ledger", "mpesa_transactions", "lease_agreements"]
    .map((t) => Number(sql(`SELECT count(*) FROM ${t} WHERE tenant_id = ANY('{${tenantIds}}'::int[])`)))
    .reduce((a, b) => a + b, 0);
  R.check("no row anywhere still points at a deleted tenant", traces === 0, `${traces}`);

  // What stays.
  const keptAfter = snap(kept);
  for (const [k, v] of Object.entries(keptAfter)) R.check(`kept: ${k}`, v === keptBefore[k], `${keptBefore[k]} → ${v}`);
  R.check("the wipe is in the audit trail",
    sql(`SELECT count(*) FROM audit_logs WHERE landlord_id=${LID} AND action='backup_and_delete_account'`) === "1");

  await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await shot("tenants-page-empty", { fullPage: false });
  await page.goto(`${BASE}/landlord/properties`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await shot("properties-page-empty", { fullPage: false });
  R.check("the owner is still signed in to a working, empty account", page.url().includes("/landlord/properties"));
} catch (err) {
  R.check("walkthrough ran to completion", false, err.message.split("\n")[0]);
} finally {
  await browser.close();
}
process.exit(R.summary() ? 1 : 0);
