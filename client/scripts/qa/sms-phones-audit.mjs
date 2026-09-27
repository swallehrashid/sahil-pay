/**
 * Items 4, 5, 7 on the Acme account:
 *   4  every SMS sent on the account (welcome by the owner, reminder by a team
 *      member) comes off the ACCOUNT's SMS balance; tenant login codes do not.
 *   5  07…, +254… and 254… are one number — saved as 254…, and the tenant can
 *      sign in with whichever they type.
 *   7  the audit trail shows Nairobi time even on a device set to US time.
 *
 *   QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/sms-phones-audit.mjs
 */
import { chromium, devices } from "playwright";
import { execSync } from "node:child_process";
import { BASE, results, shooter, staffLogin, tenantLogin, dismissTours } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execSync(`psql "${DB}" -tAc "${q.replace(/"/g, '\\"')}"`).toString().trim();
const R = results();
const LID = 1;

const rand8 = () => String(Math.floor(10000000 + Math.random() * 89999999));
const digits = `7${rand8()}`;                               // 9-digit subscriber number
const typedLocal = `0${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6)}`; // "07xx xxx xxx"
const stored = `254${digits}`;
const balance = () => Number(sql(`SELECT sms_balance FROM landlords WHERE id=${LID}`));
const pool = () => Number(sql("SELECT pool_balance FROM sms_pricing_config LIMIT 1"));

sql("UPDATE sms_pricing_config SET pool_balance=100000");
sql(`UPDATE landlords SET sms_balance=800 WHERE id=${LID}`);
// A unit inside the team member's assigned blocks, so they can see the tenant too.
const TEAM_SCOPE = `(SELECT a.property_id FROM team_member_property_access a JOIN team_members tm ON tm.id=a.team_member_id
  JOIN users us ON us.id=tm.user_id WHERE us.email='caretaker@sahilpay.test')`;
let vacant = sql(`SELECT u.id||'|'||u.name||'|'||p.name FROM units u JOIN properties p ON p.id=u.property_id
  WHERE p.landlord_id=${LID} AND NOT u.is_occupied AND NOT u.is_deleted AND NOT p.is_deleted
  AND p.id IN ${TEAM_SCOPE} ORDER BY u.id LIMIT 1`);
if (!vacant) {
  const pid = sql(`SELECT id FROM properties WHERE landlord_id=${LID} AND NOT is_deleted AND id IN ${TEAM_SCOPE} ORDER BY id LIMIT 1`);
  sql(`INSERT INTO units (property_id, landlord_id, name, rent_amount, is_occupied, is_deleted, created_at, updated_at)
       VALUES (${pid}, ${LID}, 'QA-${digits.slice(-4)}', 12000, false, false, now(), now())`);
  vacant = sql(`SELECT u.id||'|'||u.name||'|'||p.name FROM units u JOIN properties p ON p.id=u.property_id
    WHERE u.name='QA-${digits.slice(-4)}'`);
}
const [, unitName, propName] = vacant.split("|");
console.log(`Vacant unit ${unitName} in ${propName}; tenant phone typed as "${typedLocal}"`);

const comboBox = (page, label) => page.getByRole("combobox", { name: new RegExp(`^${label}( \\*)?$`) }).last();
async function pick(page, label, text) {
  await comboBox(page, label).click();
  await page.locator('[role="searchbox"]').last().fill(text);
  await page.locator('[role="listbox"]').last().locator('[role="option"]', { hasText: text }).first().click();
}
const navbarBalance = async (page) => Number((await page.getByTestId("navbar-sms-balance").textContent()).replace(/\D/g, ""));

const browser = await chromium.launch();
try {
  // ── Owner, on a laptop set to US Eastern time (the user's audit-trail symptom) ──
  const ownerCtx = await browser.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: "America/New_York" });
  const owner = await ownerCtx.newPage();
  const shot = shooter(owner, "sms-phones-audit");
  await staffLogin(owner, "landlord@sahilpay.test", "Landlord@123");
  await owner.goto(`${BASE}/landlord/tenants`, { waitUntil: "domcontentloaded" });
  await dismissTours(owner);
  await owner.getByTestId("navbar-sms-balance").waitFor({ timeout: 20000 });
  await owner.waitForTimeout(1500);
  const shownBefore = await navbarBalance(owner);
  const dbBefore = balance();
  const poolBefore = pool();
  R.check("navbar shows the live SMS balance", shownBefore === dbBefore, `navbar ${shownBefore}, db ${dbBefore}`);

  await owner.getByRole("button", { name: "Add tenant" }).click();
  await pick(owner, "Property", propName);
  await pick(owner, "Unit", unitName);
  await owner.getByLabel("First name").fill("Wema");
  await owner.getByLabel("Last name").fill(`Phone${digits.slice(-4)}`);
  await owner.getByLabel(/^Phone/).first().fill(typedLocal);
  await owner.waitForTimeout(300);
  await shot("add-tenant-07-number-hint", { fullPage: false });
  R.check("phone field says the 07 number will be saved as 254…",
    await owner.getByText(`Will be saved as ${stored}`).isVisible());
  await owner.getByText("Send a welcome message to this tenant").click();
  const actionAt = new Date();
  await owner.getByRole("button", { name: "Save tenant" }).click();
  await owner.getByText(/Tenant added\. Welcome message sent\./).waitFor({ timeout: 20000 });
  await shot("tenant-added-welcome-sent", { fullPage: false });
  R.check("saved with 07… → stored as 254…", sql(`SELECT phone FROM tenants WHERE phone LIKE '%${digits}' AND NOT is_deleted`) === stored);

  const dbAfterWelcome = balance();
  const spent = dbBefore - dbAfterWelcome;
  R.check("welcome SMS came off the ACCOUNT's balance", spent >= 1, `${dbBefore} → ${dbAfterWelcome}`);
  R.check("…and the platform pool moved by the same credits (not free)", poolBefore - pool() === spent, `pool ${poolBefore} → ${pool()}`);
  const log = sql(`SELECT status||'|'||sms_charge FROM communication_logs WHERE landlord_id=${LID} AND message_type='sms' ORDER BY id DESC LIMIT 1`);
  R.check("message log: delivered and charged", log.startsWith("delivered|") && Number(log.split("|")[1]) > 0, log);
  await owner.waitForFunction((n) => {
    const el = document.querySelector('[data-testid="navbar-sms-balance"]');
    return el && Number(el.textContent.replace(/\D/g, "")) === n;
  }, dbAfterWelcome, { timeout: 15000 }).catch(() => {});
  const shownAfter = await navbarBalance(owner);
  await shot("navbar-balance-dropped", { fullPage: false });
  R.check("navbar balance drops immediately, no reload", shownAfter === dbAfterWelcome, `navbar ${shownBefore} → ${shownAfter}`);

  // ── Audit trail in Nairobi time, although this browser is on New York time ──
  await owner.goto(`${BASE}/landlord/settings/audit`, { waitUntil: "domcontentloaded" });
  await owner.getByText(/create_tenant|Tenant 'Wema/i).first().waitFor({ timeout: 20000 });
  await owner.waitForTimeout(1000);
  await shot("audit-trail-nairobi-time");
  const nairobi = (d) => new Intl.DateTimeFormat("en-KE", { timeZone: "Africa/Nairobi", hour: "2-digit", minute: "2-digit", hour12: true }).format(d);
  const bodyText = await owner.locator("body").innerText();
  const candidates = [-1, 0, 1, 2].map((m) => nairobi(new Date(actionAt.getTime() + m * 60000)));
  const found = candidates.find((c) => bodyText.includes(c));
  const wrongNY = new Intl.DateTimeFormat("en-KE", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: true }).format(actionAt);
  R.check("audit trail shows the Nairobi time the action happened", Boolean(found), `expected ~${candidates[1]}; NY would read ${wrongNY}`);

  // ── A team member sends a reminder: still the ACCOUNT's credits ──
  const teamCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const team = await teamCtx.newPage();
  const tshot = shooter(team, "sms-phones-audit-team");
  await staffLogin(team, "caretaker@sahilpay.test", "Caretaker@123");
  await team.goto(`${BASE}/team/tenants`, { waitUntil: "domcontentloaded" });
  await dismissTours(team);
  await team.getByPlaceholder(/search/i).first().fill(typedLocal.slice(0, 7));
  await team.waitForTimeout(1500);
  await tshot("team-search-by-07-prefix", { fullPage: false });
  R.check("tenant search with 07… finds the 254… number", await team.getByText(`Phone${digits.slice(-4)}`).first().isVisible());
  const beforeReminder = balance();
  const row = team.locator("tr, [role='row'], .glass", { hasText: `Phone${digits.slice(-4)}` }).first();
  await row.getByRole("button").last().click();
  await team.getByText("Send balance reminder").click();
  await team.getByRole("button", { name: "Send reminder" }).click();
  await team.getByText(/Reminder sent/).waitFor({ timeout: 20000 });
  await tshot("team-reminder-sent", { fullPage: false });
  R.check("team member's reminder SMS came off the account's balance", balance() < beforeReminder, `${beforeReminder} → ${balance()}`);

  // ── Tenant sign-in with every format; login codes are NOT charged ──
  const beforeLogins = balance();
  for (const [label, typed] of [["07 with spaces", typedLocal], ["+254 international", `+254 ${digits}`], ["254 no plus", stored]]) {
    const ctx = await browser.newContext({ ...devices["iPhone 13"] });
    const page = await ctx.newPage();
    try {
      await tenantLogin(page, typed);
      R.check(`tenant signs in typing ${label} ("${typed}")`, /\/portal\//.test(page.url()));
      await shooter(page, "sms-phones-audit-tenant")(`tenant-portal-${label.replace(/\W+/g, "-")}`, { fullPage: false });
    } catch (err) {
      R.check(`tenant signs in typing ${label} ("${typed}")`, false, err.message);
    }
    await ctx.close();
  }
  R.check("tenant login codes are NOT charged to the account", balance() === beforeLogins, `${beforeLogins} → ${balance()}`);

  // A legacy row still stored as 07… is found by a tenant typing 254…
  const legacyDigits = `7${rand8()}`;
  const legacyTenant = sql(`SELECT id FROM tenants WHERE landlord_id=${LID} AND NOT is_deleted AND phone NOT LIKE '%${digits}' ORDER BY id LIMIT 1`);
  const oldPhone = sql(`SELECT phone FROM tenants WHERE id=${legacyTenant}`);
  sql(`UPDATE tenants SET phone='0${legacyDigits}' WHERE id=${legacyTenant}`);
  const ctx = await browser.newContext({ ...devices["iPhone 13"] });
  const page = await ctx.newPage();
  try {
    await tenantLogin(page, `254${legacyDigits}`);
    R.check("legacy tenant saved as 07… signs in typing 254…", /\/portal\//.test(page.url()));
  } catch (err) {
    R.check("legacy tenant saved as 07… signs in typing 254…", false, err.message);
  } finally {
    sql(`UPDATE tenants SET phone='${oldPhone}' WHERE id=${legacyTenant}`);
    await ctx.close();
  }
} catch (err) {
  R.check("walkthrough ran to completion", false, err.message);
} finally {
  await browser.close();
}
process.exit(R.summary() ? 1 : 0);
