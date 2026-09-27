/**
 * Items 8 and 6 on the scale estate (100 properties, 1,000 units, ~1,000 tenants).
 *
 *   The owner creates three team members in the UI:
 *     Office  — "Full access" preset: everything except Settings
 *     Care    — "Caretaker" preset on two blocks: utilities only
 *     Viewer  — custom: Payments VIEW only
 *   The office member fills the last vacant units (→ 1,000 tenants), records a
 *   payment, sends a reminder, and runs a tutorial.
 *   Four monthly cycles (Oct 2026 – Jan 2027):
 *     caretaker bulk-uploads water readings → submits for review
 *     office approves them all
 *     the month's invoices are raised — by the office's "Create this month's
 *     invoices now" (Oct, Nov), then by the owner's automatic 1st-of-month run
 *     (Dec, Jan) after the owner ticks both boxes in Settings
 *     every tenant gets ONE invoice: rent + approved water + any balance b/f
 *   Permission scenarios for the caretaker and the viewer, including the owner
 *   upgrading the viewer and the change showing up.
 *
 *   QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/team-e2e.mjs
 */
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { BASE, api, apiLogin, results, shooter, staffLogin, dismissTours } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execFileSync("psql", [DB, "-tAc", q]).toString().trim();
const R = results();
const OWNER = { email: "scale-pm@sahilpay.test", password: "ScaleTest123!" };
const LID = Number(sql(`SELECT l.id FROM landlords l JOIN users u ON u.id=l.user_id WHERE u.email='${OWNER.email}'`));
const tag = Date.now().toString().slice(-5);
const PASS = "QaTeam123!";
const who = {
  office: { email: `office.${tag}@qa.sahilpay.test`, username: `office${tag}`, first: "Office", last: `Secretary${tag}` },
  care: { email: `care.${tag}@qa.sahilpay.test`, username: `care${tag}`, first: "Caretaker", last: `Juma${tag}` },
  viewer: { email: `viewer.${tag}@qa.sahilpay.test`, username: `viewer${tag}`, first: "Viewer", last: `Payments${tag}` },
};
const CARE_BLOCKS = sql(`SELECT string_agg(name, '|' ORDER BY name) FROM (SELECT name FROM properties WHERE landlord_id=${LID} AND NOT is_deleted ORDER BY name LIMIT 2) x`).split("|");
// Four months, starting after the last month this account was invoiced for.
const lastInvoiced = sql(`SELECT to_char(max(issue_date), 'YYYY-MM') FROM invoices WHERE landlord_id=${LID} AND invoice_type='monthly'`);
const addMonths = (ym, n) => { const [y, m] = ym.split("-").map(Number); const d = new Date(Date.UTC(y, m - 1 + n, 1)); return d.toISOString().slice(0, 7); };
const MONTHS = [0, 1, 2, 3].map((k) => ({
  reading: addMonths(lastInvoiced, k),
  invoice: `${addMonths(lastInvoiced, k + 1)}-01`,
  by: k < 2 ? "office" : "automatic",
}));
console.log("cycles:", MONTHS.map((m) => m.invoice).join(", "));
const WATER_RATE = 120;

const liveTenants = () => Number(sql(`SELECT count(*) FROM tenants t JOIN units u ON u.id=t.unit_id JOIN properties p ON p.id=u.property_id
  WHERE t.landlord_id=${LID} AND NOT t.is_deleted AND NOT u.is_deleted AND NOT p.is_deleted`));
const comboBox = (page, label) => page.getByRole("combobox", { name: new RegExp(`^${label}( \\*)?$`) }).last();
async function pick(page, label, text) {
  await comboBox(page, label).click();
  await page.locator('[role="searchbox"]').last().fill(text);
  await page.locator('[role="listbox"]').last().locator('[role="option"]', { hasText: text }).first().click();
}
async function navHrefs(page) {
  // Expand every group of the VISIBLE sidebar (a hidden mobile copy also exists).
  for (let i = 0; i < 12; i++) {
    const closed = page.locator('aside:visible nav button[aria-expanded="false"]');
    if (!(await closed.count())) break;
    await closed.first().click({ timeout: 3000 }).catch(() => {});
  }
  return page.locator("aside:visible nav a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
}
function activate(email) {
  const hash = execFileSync("../server/venv/bin/python", ["-c",
    `from werkzeug.security import generate_password_hash as g; print(g("${PASS}"))`]).toString().trim();
  sql(`UPDATE users SET password_hash='${hash}', is_verified=true, must_change_password=false WHERE email='${email}'`);
}

async function createMember(page, m, { preset, blocks = [], allProps = true, perms = null, role = null }) {
  await page.goto(`${BASE}/landlord/settings/team`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByRole("button", { name: "Add team member" }).click();
  await page.getByRole("button", { name: new RegExp(preset) }).first().click();
  await page.getByLabel("Username").fill(m.username);
  await page.getByLabel("Email").fill(m.email);
  await page.getByLabel("First name").fill(m.first);
  await page.getByLabel("Last name").fill(m.last);
  if (role) await pick(page, "Role", role);
  const all = page.getByText("Access all properties");
  const allBox = page.getByRole("checkbox", { name: "Access all properties" });
  if ((await allBox.isChecked()) !== allProps) await all.click();
  for (const b of blocks) await page.locator("label", { hasText: b }).first().click();
  if (perms) {
    for (const [moduleLabel, level] of perms) {
      const row = page.locator("tr", { has: page.getByText(moduleLabel, { exact: true }) }).first();
      await row.locator("label").nth(level === "edit" ? 1 : 0).click();
    }
  }
  await page.getByRole("button", { name: "Save team member" }).click();
  await page.waitForTimeout(2500);
  const id = sql(`SELECT tm.id FROM team_members tm JOIN users u ON u.id=tm.user_id WHERE u.email='${m.email}'`);
  activate(m.email);
  return id;
}

const browser = await chromium.launch();
try {
  sql("UPDATE sms_pricing_config SET pool_balance=1000000");
  sql(`UPDATE automation_settings SET auto_generate_recurring_invoices=false, auto_invoice_queued_charges=false WHERE landlord_id=${LID}`);

  // ── Owner creates the three members in the UI ─────────────────────────────
  const ownerCtx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const owner = await ownerCtx.newPage();
  const oshot = shooter(owner, "team-owner");
  await staffLogin(owner, OWNER.email, OWNER.password);
  const officeId = await createMember(owner, who.office, { preset: "Full access" });
  const careId = await createMember(owner, who.care, { preset: "Caretaker", allProps: false, blocks: CARE_BLOCKS });
  const viewerId = await createMember(owner, who.viewer, { preset: "Custom", role: "viewer", perms: [["Payments", "view"]] });
  await owner.getByPlaceholder(/search/i).first().fill(tag).catch(() => {});
  await owner.waitForTimeout(1200);
  await oshot("three-members-created");
  const officePerms = sql(`SELECT count(*) FILTER (WHERE can_edit) || '/' || count(*) FROM team_member_permissions WHERE team_member_id=${officeId}`);
  R.check("owner created 'Full access' member: edit on every module", officePerms.split("/")[0] === officePerms.split("/")[1] && Number(officePerms.split("/")[0]) >= 15, officePerms);
  R.check("caretaker is limited to its two blocks", sql(`SELECT count(*) FROM team_member_property_access WHERE team_member_id=${careId}`) === "2");
  R.check("viewer holds Payments view only", sql(`SELECT string_agg(module||':'||can_view||'/'||can_edit, ',') FROM team_member_permissions WHERE team_member_id=${viewerId} AND (can_view OR can_edit)`) === "payments:true/false");

  // ── Office (full access) ──────────────────────────────────────────────────
  const officeCtx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const office = await officeCtx.newPage();
  const fshot = shooter(office, "team-office");
  await staffLogin(office, who.office.email, PASS);
  await office.goto(`${BASE}/team/dashboard`, { waitUntil: "domcontentloaded" });
  await office.waitForTimeout(1500);
  const hrefs = await navHrefs(office);
  await fshot("full-access-sidebar", { fullPage: false });
  for (const p of ["payments", "invoices", "tenants", "properties", "units", "utilities", "expenses", "reports", "leases", "communications", "payments/review-queue", "payouts", "tutorials"]) {
    R.check(`full access sees /team/${p}`, hrefs.some((h) => h && h.startsWith(`/team/${p}`)));
  }
  R.check("full access has NO Settings", !hrefs.some((h) => h && h.includes("settings")));
  await office.goto(`${BASE}/team/dashboard`, { waitUntil: "domcontentloaded" });
  await office.getByTestId("team-kpis").waitFor({ timeout: 15000 }).catch(() => {});
  await fshot("full-access-dashboard", { fullPage: false });
  R.check("full access dashboard shows the money cards", await office.getByTestId("team-kpis").isVisible());
  await office.goto(`${BASE}/landlord/settings/general`, { waitUntil: "domcontentloaded" });
  await office.waitForTimeout(2000);
  R.check("a team member cannot open the owner's Settings by URL", !office.url().includes("/settings"), office.url());

  // Fill the last vacant units → 1,000 tenants. One in the UI, the rest over the API as the same member.
  const officeToken = await apiLogin(who.office.email, PASS);
  if (sql(`SELECT count(*) FROM units u JOIN properties p ON p.id=u.property_id WHERE p.landlord_id=${LID} AND NOT u.is_occupied AND NOT u.is_deleted AND NOT p.is_deleted`) === "0") {
    // Already full from an earlier run: free one unit so there is something to add.
    const tid = sql(`SELECT t.id FROM tenants t WHERE t.landlord_id=${LID} AND NOT t.is_deleted ORDER BY t.id DESC LIMIT 1`);
    await api(`/tenants/${tid}`, { token: officeToken, method: "DELETE" });
  }
  const vacant = sql(`SELECT u.id||'|'||u.name||'|'||p.name FROM units u JOIN properties p ON p.id=u.property_id
    WHERE p.landlord_id=${LID} AND NOT u.is_occupied AND NOT u.is_deleted AND NOT p.is_deleted ORDER BY p.name, u.name`).split("\n").filter(Boolean);
  const [u0id, u0name, p0name] = vacant[0].split("|");
  await office.goto(`${BASE}/team/tenants`, { waitUntil: "domcontentloaded" });
  await office.getByRole("button", { name: "Add tenant" }).click();
  await pick(office, "Property", p0name);
  await pick(office, "Unit", u0name);
  await office.getByLabel("First name").fill("Neema");
  await office.getByLabel("Last name").fill(`Office${tag}`);
  await office.getByLabel(/^Phone/).first().fill(`07${tag}123`);
  await office.getByRole("button", { name: "Save tenant" }).click();
  await office.getByText(/Tenant added/).waitFor({ timeout: 20000 });
  await fshot("office-added-a-tenant", { fullPage: false });
  for (const row of vacant.slice(1)) {
    const [uid, uname] = row.split("|");
    await api("/tenants/", { token: officeToken, method: "POST", body: {
      unit_id: Number(uid), first_name: "Fill", last_name: `${uname}`, phone: `07${String(10000000 + Math.floor(Math.random() * 89999999))}` } });
  }
  const tenantsNow = liveTenants();
  R.check("office filled every vacant unit → 1,000 tenants", tenantsNow === 1000, `${tenantsNow} tenants in ${u0id ? "1,000 units" : ""}`);

  // Record a payment and send a reminder from the office account.
  const payee = sql(`SELECT t.first_name||' '||t.last_name||'|'||t.id||'|'||u.name FROM tenants t JOIN units u ON u.id=t.unit_id JOIN properties p ON p.id=u.property_id
    WHERE t.landlord_id=${LID} AND NOT t.is_deleted AND p.name='${CARE_BLOCKS[0]}' ORDER BY u.name LIMIT 1`).split("|");
  await office.goto(`${BASE}/team/payments`, { waitUntil: "domcontentloaded" });
  await office.getByRole("button", { name: "Record payment" }).first().click();
  // Two tenants can share a name; the option label carries the unit, so search by both.
  await comboBox(office, "Tenant").click();
  await office.locator('[role="searchbox"]').last().fill(`${payee[0]} ${payee[2]}`);
  await office.locator('[role="listbox"]').last().locator('[role="option"]', { hasText: payee[2] }).first().click();
  await office.getByLabel(/^Amount/).first().fill("4000");
  await fshot("office-record-payment", { fullPage: false });
  const paymentsBefore = Number(sql(`SELECT count(*) FROM payments WHERE tenant_id=${payee[1]}`));
  await office.getByRole("button", { name: /Record payment|Save payment/ }).last().click();
  await office.waitForTimeout(3000);
  R.check("office recorded a payment", Number(sql(`SELECT count(*) FROM payments WHERE tenant_id=${payee[1]}`)) === paymentsBefore + 1);

  const smsBefore = Number(sql(`SELECT sms_balance FROM landlords WHERE id=${LID}`));
  const rem = await api(`/tenants/${payee[1]}/reminder`, { token: officeToken, method: "POST", body: { channels: ["sms"] } });
  R.check("office's reminder SMS is charged to the account", rem.status === 200 && Number(sql(`SELECT sms_balance FROM landlords WHERE id=${LID}`)) < smsBefore,
    `${smsBefore} → ${sql(`SELECT sms_balance FROM landlords WHERE id=${LID}`)}`);

  // Tutorials work for a team member.
  await office.goto(`${BASE}/team/tutorials`, { waitUntil: "domcontentloaded" });
  await office.getByText("Add units to a property").waitFor({ timeout: 15000 });
  const cards = await office.getByRole("button", { name: /^(Start|Run again)$/ }).count();
  await fshot("office-tutorials", { fullPage: false });
  R.check("office sees the full tutorial library", cards >= 10, `${cards} tutorials`);
  await office.locator(".glass", { hasText: "Add units to a property" }).getByRole("button", { name: /Start|Run again/ }).click();
  await office.getByText("Open Units").waitFor({ timeout: 15000 });
  await fshot("office-tutorial-running", { fullPage: false });
  R.check("clicking Start actually runs the tutorial for a team member", true);
  await office.keyboard.press("Escape");

  // ── Caretaker ─────────────────────────────────────────────────────────────
  const careCtx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const care = await careCtx.newPage();
  const cshot = shooter(care, "team-caretaker");
  await staffLogin(care, who.care.email, PASS);
  await care.goto(`${BASE}/team/dashboard`, { waitUntil: "domcontentloaded" });
  await care.waitForTimeout(1500);
  const careHrefs = await navHrefs(care);
  await cshot("caretaker-sidebar", { fullPage: false });
  R.check("caretaker sees Utilities", careHrefs.some((h) => h?.startsWith("/team/utilities")));
  R.check("caretaker does NOT see Payments or Invoices", !careHrefs.some((h) => h?.startsWith("/team/payments") || h?.startsWith("/team/invoices")));
  await care.goto(`${BASE}/team/payments`, { waitUntil: "domcontentloaded" });
  await care.waitForTimeout(1500);
  R.check("caretaker cannot open Payments by URL", !(await care.getByRole("button", { name: "Record payment" }).isVisible().catch(() => false)));
  const careToken = await apiLogin(who.care.email, PASS);
  const moneyTry = await api("/dashboard/summary", { token: careToken });
  R.check("caretaker cannot read the account's money summary from the API", moneyTry.status === 403, `HTTP ${moneyTry.status}`);
  await care.goto(`${BASE}/team/tutorials`, { waitUntil: "domcontentloaded" });
  await care.getByText(/Record meter readings/).waitFor({ timeout: 15000 });
  const careTutorials = await care.locator(".glass h3").allTextContents();
  await cshot("caretaker-tutorials", { fullPage: false });
  R.check("caretaker gets the utilities tutorial", careTutorials.some((t) => /meter readings/i.test(t)), careTutorials.join(" | "));
  R.check("caretaker does NOT get payment / invoice tutorials", !careTutorials.some((t) => /payment|invoice|Approve/i.test(t)), careTutorials.join(" | "));
  await care.locator(".glass", { hasText: "Record meter readings" }).getByRole("button", { name: /Start|Run again/ }).click();
  await care.getByText("Open Utilities").waitFor({ timeout: 15000 });
  await cshot("caretaker-tutorial-running", { fullPage: false });
  R.check("caretaker's tutorial runs", true);
  await care.keyboard.press("Escape");

  // ── Four monthly cycles ───────────────────────────────────────────────────
  const careUnits = sql(`SELECT count(*) FROM units u JOIN properties p ON p.id=u.property_id WHERE p.name='${CARE_BLOCKS[0]}' AND p.landlord_id=${LID} AND NOT u.is_deleted`);
  let prev = {};
  for (const [i, m] of MONTHS.entries()) {
    const label = `${m.invoice.slice(0, 7)}`;
    // Caretaker: bulk upload water for block 1, then submit for review.
    await care.goto(`${BASE}/team/utilities`, { waitUntil: "domcontentloaded" });
    await care.getByRole("button", { name: "Bulk upload" }).click();
    await pick(care, "Property", CARE_BLOCKS[0]);
    await pick(care, "Utility", "Water");
    await care.getByLabel("Reading month").fill(m.reading);
    await care.getByRole("button", { name: /Next: record readings/ }).click();
    const rows = care.locator(".grid.grid-cols-12.items-center");
    await rows.first().waitFor();
    const n = await rows.count();
    for (let k = 0; k < n; k++) {
      const start = prev[k] ?? 1000 + k * 50;
      const used = 5 + ((k + i) % 7);
      await rows.nth(k).locator("input").nth(0).fill(String(start));
      await rows.nth(k).locator("input").nth(1).fill(String(start + used));
      prev[k] = start + used;
    }
    if (i === 0) await cshot("caretaker-bulk-readings", { fullPage: false });
    await care.getByRole("button", { name: "Save readings" }).click();
    await care.getByTestId("bulk-queue").waitFor({ timeout: 20000 });
    R.check(`${label}: caretaker is NOT offered "create invoices" — only submit for review`,
      !(await care.getByText("Create new invoices").isVisible()));
    await care.getByTestId("bulk-queue").click();
    await care.getByText(/sent for review/).waitFor({ timeout: 20000 });
    if (i === 0) {
      await care.waitForTimeout(800);
      await cshot("caretaker-submitted-waiting-for-review");
    }
    const pendingNow = Number(sql(`SELECT count(*) FROM queued_charges WHERE landlord_id=${LID} AND status='pending'`));
    R.check(`${label}: ${careUnits} readings waiting for review`, pendingNow === Number(careUnits), `${pendingNow} pending`);

    // Office is told on the dashboard, then approves them all.
    if (i === 0) {
      await office.goto(`${BASE}/team/dashboard`, { waitUntil: "domcontentloaded" });
      await office.getByTestId("team-review-nudge").waitFor({ timeout: 15000 }).catch(() => {});
      await fshot("office-dashboard-review-nudge", { fullPage: false });
      R.check("office dashboard says charges are waiting for review", await office.getByTestId("team-review-nudge").isVisible());
      const notified = sql(`SELECT count(*) FROM notifications n JOIN users u ON u.id=n.recipient_user_id WHERE u.email='${who.office.email}' AND n.category='queue_review'`);
      R.check("office got a notification about the submission", Number(notified) >= 1, notified);
    }
    await office.goto(`${BASE}/team/invoices?tab=queue`, { waitUntil: "domcontentloaded" });
    await office.getByTestId("approve-all").waitFor({ timeout: 20000 });
    if (i === 0) await fshot("office-review-queue", { fullPage: false });
    await office.getByTestId("approve-all").click();
    await office.getByText(/charge\(s\) approved/).waitFor({ timeout: 20000 });
    if (i === 0) await fshot("office-approved");
    R.check(`${label}: office approved every reading`,
      sql(`SELECT count(*) FROM queued_charges WHERE landlord_id=${LID} AND status='pending'`) === "0");

    // Raise the month's invoices.
    if (m.by === "office") {
      await office.getByTestId("run-monthly-open").click();
      await office.getByLabel("Invoice date").fill(m.invoice);
      if (i === 0) await fshot("office-create-month-invoices", { fullPage: false });
      await office.getByTestId("run-monthly-submit").click();
      await office.getByText(/invoice\(s\) created/).waitFor({ timeout: 600000 });
      await fshot(`office-invoiced-${label}`, { fullPage: false });
    } else {
      if (i === 2) {
        await owner.goto(`${BASE}/landlord/settings/general`, { waitUntil: "domcontentloaded" });
        await owner.getByText("Automatically invoice rent (and other fixed monthly charges)").click();
        await owner.getByText("Automatically invoice approved queued charges (utilities etc.)").click();
        await oshot("owner-ticks-automatic-invoicing", { fullPage: false });
        await owner.getByRole("button", { name: "Save changes" }).click();
        await owner.waitForTimeout(2500);
        R.check("owner switched on automatic rent + queued-charge invoicing",
          sql(`SELECT auto_generate_recurring_invoices||'/'||auto_invoice_queued_charges FROM automation_settings WHERE landlord_id=${LID}`) === "true/true");
      }
      // What Celery Beat runs at 00:05 on the 1st.
      execFileSync("../server/venv/bin/python", ["-c",
        `from app import create_app\napp=create_app()\nwith app.app_context():\n    from tasks.invoice_tasks import run_monthly_billing_all\n    print(run_monthly_billing_all.run(issue_date="${m.invoice}"))`],
        { cwd: "../server", env: { ...process.env, APP_ENV: "development", COMMS_SIMULATION_MODE: "true" } });
    }

    // Verify the month.
    const monthInvoices = Number(sql(`SELECT count(*) FROM invoices WHERE landlord_id=${LID} AND invoice_type='monthly' AND issue_date='${m.invoice}' AND NOT is_deleted`));
    R.check(`${label}: one invoice per tenant (${liveTenants()})`, monthInvoices === liveTenants(), `${monthInvoices} invoices`);
    const dupes = sql(`SELECT count(*) FROM (SELECT tenant_id FROM invoices WHERE landlord_id=${LID} AND invoice_type='monthly'
      AND date_trunc('month', issue_date)='${m.invoice}' AND NOT is_deleted GROUP BY tenant_id HAVING count(*)>1) x`);
    R.check(`${label}: nobody invoiced twice`, dupes === "0");
    const careLines = sql(`SELECT count(*) FROM invoice_line_items li JOIN invoices i ON i.id=li.invoice_id JOIN properties p ON p.id=i.property_id
      WHERE i.landlord_id=${LID} AND i.issue_date='${m.invoice}' AND p.name='${CARE_BLOCKS[0]}' AND li.item = 'Water'`);
    R.check(`${label}: every ${CARE_BLOCKS[0]} invoice carries its approved water charge`, Number(careLines) === Number(careUnits), `${careLines} water lines`);
    const sample = sql(`SELECT string_agg(li.item||'='||li.amount, ', ' ORDER BY li.id) FROM invoice_line_items li JOIN invoices i ON i.id=li.invoice_id
      WHERE i.tenant_id=${payee[1]} AND i.issue_date='${m.invoice}'`);
    R.check(`${label}: ${payee[0]}'s ONE invoice = rent + water${i > 0 ? " + balance b/f" : ""}`,
      /(^|, )Rent=/.test(sample) && /(^|, )Water=/.test(sample) && (i === 0 || /Balance b\/f/.test(sample)), sample);
    const otherBlock = sql(`SELECT string_agg(DISTINCT li.item, ',') FROM invoice_line_items li JOIN invoices i ON i.id=li.invoice_id JOIN properties p ON p.id=i.property_id
      WHERE i.landlord_id=${LID} AND i.issue_date='${m.invoice}' AND p.name NOT IN ('${CARE_BLOCKS[0]}','${CARE_BLOCKS[1]}')`);
    R.check(`${label}: blocks without readings get rent (and b/f) only`, !/Water/.test(otherBlock), otherBlock);
    const waterAmount = sql(`SELECT li.amount FROM invoice_line_items li JOIN invoices i ON i.id=li.invoice_id WHERE i.tenant_id=${payee[1]} AND i.issue_date='${m.invoice}' AND li.item = 'Water'`);
    const expected = (5 + ((0 + i) % 7)) * WATER_RATE;
    R.check(`${label}: water priced as consumption × KES ${WATER_RATE}`, Number(waterAmount) === expected, `${waterAmount} vs ${expected}`);
  }
  await care.goto(`${BASE}/team/utilities`, { waitUntil: "domcontentloaded" });
  await care.waitForTimeout(1500);
  await cshot("caretaker-readings-invoiced");
  R.check("caretaker sees each reading marked Invoiced", await care.getByText(/Invoiced · /).first().isVisible());

  // ── Viewer, then upgraded by the owner ───────────────────────────────────
  const viewCtx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const viewer = await viewCtx.newPage();
  const vshot = shooter(viewer, "team-viewer");
  await staffLogin(viewer, who.viewer.email, PASS);
  await viewer.goto(`${BASE}/team/payments`, { waitUntil: "domcontentloaded" });
  await viewer.waitForTimeout(2500);
  const vHrefs = await navHrefs(viewer);
  await vshot("viewer-payments-read-only", { fullPage: false });
  R.check("viewer sees Payments", vHrefs.some((h) => h?.startsWith("/team/payments")));
  R.check("viewer sees nothing else (no tenants, invoices, utilities)", !vHrefs.some((h) => /\/team\/(tenants|invoices|utilities|properties)/.test(h || "")));
  R.check("viewer cannot record a payment", !(await viewer.getByRole("button", { name: "Record payment" }).isVisible().catch(() => false)));
  R.check("viewer has no Help & tutorials", !vHrefs.some((h) => /tutorials|help/.test(h || "")));

  await owner.goto(`${BASE}/landlord/settings/team`, { waitUntil: "domcontentloaded" });
  await owner.getByPlaceholder(/search/i).first().fill(who.viewer.username).catch(() => {});
  await owner.waitForTimeout(1500);
  const vrow = owner.locator("tr", { hasText: who.viewer.username }).first();
  await vrow.getByRole("button").last().click();
  await owner.getByText("Edit", { exact: true }).first().click();
  const utilRow = owner.locator("tr", { has: owner.getByText("Utilities", { exact: true }) }).first();
  await utilRow.locator("label").nth(1).click();
  await owner.getByRole("button", { name: "Save team member" }).click();
  await owner.waitForTimeout(2500);
  R.check("owner upgraded the viewer to edit Utilities",
    sql(`SELECT can_edit FROM team_member_permissions WHERE team_member_id=${viewerId} AND module='utilities'`) === "t");
  await viewer.reload({ waitUntil: "domcontentloaded" });
  await viewer.waitForTimeout(2500);
  const v2 = await navHrefs(viewer);
  await viewer.goto(`${BASE}/team/tutorials`, { waitUntil: "domcontentloaded" });
  await viewer.getByText(/Record meter readings/).waitFor({ timeout: 15000 }).catch(() => {});
  await vshot("viewer-after-upgrade-tutorials", { fullPage: false });
  R.check("after the upgrade the member sees Utilities", v2.some((h) => h?.startsWith("/team/utilities")));
  R.check("…and now gets Help with the utilities tutorial", await viewer.getByText(/Record meter readings/).isVisible());
} catch (err) {
  R.check("walkthrough ran to completion", false, err.message.split("\n")[0]);
} finally {
  await browser.close();
}
process.exit(R.summary() ? 1 : 0);
