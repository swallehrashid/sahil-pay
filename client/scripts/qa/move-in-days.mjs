/**
 * Move-in billing, every day of the month — end to end.
 *
 * On the scale estate (100 properties, ~1,000 units, ~950 tenants, five months
 * of history), FIVE tenants move in on EACH day of September 2026 (150 in all):
 *
 *   day 1–19   box UNticked — bill for September: "Rent — This month" at the
 *              part-month amount (rent × days left ÷ 30), deposit, lease fee.
 *   day 20–30  box TICKED, month = October — rent in full, deposit, lease fee,
 *              every line FOR October although raised and paid in September.
 *
 * Six of them (days 1, 15, 19, 20, 26, 30) are added through the real Add
 * Tenant form and paid through Record payment, with screenshots; the rest go
 * through the same API the form calls. Everyone pays their whole bill on the
 * day they move in. Then, for EVERY tenant:
 *
 *   • the receipt PDF names the right month on every line (lease: none),
 *     the right amounts, and the payment date;
 *   • a September run on the 30th bills none of them September rent again;
 *   • the October run bills the before-20th movers October in full, and the
 *     from-20th movers NOTHING more for October;
 *   • November would bill every one of them full rent;
 *   • the Payments Report moved by exactly the expected amounts, per month.
 *
 *   QA_SHOTS=../.qa/2026-09-30-move-in-days node scripts/qa/move-in-days.mjs
 */
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { BASE, API, SHOTS, results, shooter, staffLogin, dismissTours, api, apiLogin } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execSync(`psql "${DB}" -tAc "${q.replace(/"/g, '\\"')}"`).toString().trim();
const EMAIL = "scale-pm@sahilpay.test";
const PASSWORD = "ScaleTest123!";
const TMP = process.env.QA_TMP || "/tmp/sahilpay-qa-movein";
mkdirSync(TMP, { recursive: true });
const SERVER = `${process.cwd()}/../server`;
const PER_DAY = 5;
const UI_DAYS = new Set([1, 15, 19, 20, 26, 30]);
const LEASE_FEE = 1000;
const RENTS = [10000, 12000, 15000];
const FIRST = ["Wanjiku", "Otieno", "Akinyi", "Kiprono", "Muthoni", "Baraka", "Nafula", "Chege", "Atieno", "Njoroge"];

const R = results();
const LID = sql(`SELECT l.id FROM landlords l JOIN users u ON u.id=l.user_id WHERE u.email='${EMAIL}'`);
const token = await apiLogin(EMAIL, PASSWORD);
const H = { Authorization: `Bearer ${token}` };
const apiRaw = (p, init = {}) => fetch(`${API}${p}`, { ...init, headers: { ...H, ...(init.headers || {}) } });
const money = (n) => `KES ${Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pad = (n) => String(n).padStart(2, "0");
const prorata = (rent, day) => Math.round((rent * (30 - day + 1)) / 30 / 100) * 100;
const run = `R${Date.now().toString(36).slice(-4).toUpperCase()}`;   // makes names unique per run

// ------------------------------------------------------------------ units
const need = 30 * PER_DAY;
let vacant = Number(sql(`SELECT count(*) FROM units u JOIN properties p ON p.id=u.property_id WHERE p.landlord_id=${LID} AND NOT u.is_deleted AND NOT u.is_occupied AND NOT p.is_deleted`));
const props = sql(`SELECT id FROM properties WHERE landlord_id=${LID} AND NOT is_deleted ORDER BY id`).split("\n").map(Number);
for (let i = 0; vacant < need; i++) {
  const r = await api("/units/", { token, method: "POST", body: { property_id: props[i % props.length], name: `MV-${run}-${pad(i + 1)}`, rent_amount: RENTS[i % 3] } });
  if (r.status !== 201) throw new Error(`could not add a unit: ${JSON.stringify(r.json)}`);
  vacant += 1;
}
const units = sql(`SELECT u.id||'|'||u.name||'|'||p.name||'|'||u.rent_amount FROM units u JOIN properties p ON p.id=u.property_id
  WHERE p.landlord_id=${LID} AND NOT u.is_deleted AND NOT u.is_occupied AND NOT p.is_deleted ORDER BY p.id, u.id LIMIT ${need}`)
  .split("\n").map((l) => { const [id, name, prop, rent] = l.split("|"); return { id: Number(id), name, prop, rent: Number(rent) }; });
R.check(`setup: ${need} vacant units ready`, units.length === need, `${units.length}`);

const cats = (await api("/charge-categories", { token })).json.categories;
const RENT = cats.find((c) => c.name === "Rent").id;
const LEASE = cats.find((c) => c.name === "Lease Agreement").id;

function billFor(day, rent) {
  const next = day >= 20;
  const rentAmount = next ? rent : prorata(rent, day);
  return {
    next, rentAmount,
    month: next ? "2026-10" : "2026-09",
    total: rentAmount + rent + LEASE_FEE,
    payload: {
      enabled: true, bill_next_month: next, bill_month: next ? "2026-10" : undefined,
      lines: [
        { category_id: RENT, subcategory: "current", amount: rentAmount },
        { category_id: RENT, subcategory: "deposit", amount: rent },
        { category_id: LEASE, subcategory: "current", amount: LEASE_FEE },
      ],
    },
  };
}

// Report snapshots — September by payment date, and Sep–Oct for what was invoiced.
const reportSep = async () => (await api(`/reports/payments?date_from=2026-09-01&date_to=2026-09-30&ledger_page=1&ledger_per_page=1`, { token })).json;
const reportSepOct = async () => (await api(`/reports/payments?date_from=2026-09-01&date_to=2026-10-31&ledger_page=1&ledger_per_page=1`, { token })).json;
const byMonth = (rep) => Object.fromEntries(rep.by_month.map((m) => [`${m.month?.slice(0, 7)}|${m.category_name}`, m]));
const before = await reportSep();
const beforeInv = await reportSepOct();

// ------------------------------------------------------------------ tenants
const plan = [];
let u = 0;
for (let day = 1; day <= 30; day++) {
  for (let k = 0; k < PER_DAY; k++) {
    const unit = units[u++];
    plan.push({ day, k, unit, first: FIRST[(day + k) % FIRST.length], last: `${run}D${pad(day)}N${k + 1}`, ui: UI_DAYS.has(day) && k === 0, ...billFor(day, unit.rent) });
  }
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message));
const combo = (label) => page.getByRole("combobox", { name: new RegExp(`^${label}( \\*)?$`) }).last();
async function pick(label, text) {
  await combo(label).click();
  const box = page.locator('[role="listbox"]').last();
  await box.waitFor({ timeout: 15000 });
  await page.locator('[role="searchbox"]').last().fill(text);
  await page.waitForTimeout(300);
  await box.locator('[role="option"]').first().click();
  await page.waitForTimeout(300);
}
async function toast() {
  const t = page.locator("div.fixed.bottom-6 p");
  await t.last().waitFor({ timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(300);
  return (await t.allTextContents()).join(" | ");
}

try {
  await staffLogin(page, EMAIL, PASSWORD);

  for (const p of plan) {
    const mpesa = `QM${run}${pad(p.day)}${p.k}`.slice(0, 12);
    p.mpesa = mpesa;
    if (p.ui) {
      // ---------------- through the real Add Tenant form ----------------
      const shot = shooter(page, `day-${pad(p.day)}-${p.next ? "next-month" : "this-month"}`);
      await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "domcontentloaded" });
      await dismissTours(page);
      await page.getByRole("button", { name: "Add tenant" }).click();
      await pick("Property", p.unit.prop);
      await pick("Unit", p.unit.name);
      await page.getByLabel("First name").fill(p.first);
      await page.getByLabel("Last name").fill(p.last);
      await page.getByLabel(/^Phone/).first().fill(`07${String(10000000 + p.day * 100 + p.k).slice(-8)}`);
      await page.getByLabel("Move-in date").fill(`2026-09-${pad(p.day)}`);
      await page.getByTestId("move-in-bill").scrollIntoViewIfNeeded();
      if (p.next) {
        if (p.day >= 20) await shot("hint-to-bill-next-month", { fullPage: false });
        await page.getByText("Bill the next month's move-in now").click();
      }
      await page.getByText(/^Include the first month's rent/).click();
      await page.getByLabel("Amount for Rent", { exact: true }).fill(String(p.rentAmount));
      await pick("Add an item", "Rent Deposit");
      await page.getByLabel("Amount for Rent Deposit").fill(String(p.unit.rent));
      await pick("Add an item", "Lease Agreement This month");
      await page.getByLabel("Amount for Lease Agreement").fill(String(LEASE_FEE));
      await page.waitForTimeout(1200);
      await page.getByTestId("move-in-billing").scrollIntoViewIfNeeded();
      await shot("move-in-bill-filled", { fullPage: false });
      const prev = (await page.getByTestId("move-in-preview").innerText()).replace(/\s+/g, " ");
      const wantRent = `Rent — ${p.next ? "October" : "September"} 2026`;
      R.check(`UI day ${p.day}: bill preview says "${wantRent}" ${money(p.rentAmount)}`, prev.includes(wantRent) && prev.includes(money(p.rentAmount)) && /Lease Agreement KES/.test(prev), prev);
      await page.getByRole("button", { name: "Save tenant" }).click();
      const t = await toast();
      R.check(`UI day ${p.day}: tenant saved with its move-in invoice`, /Move-in invoice/.test(t), t);
      p.tenantId = Number(sql(`SELECT id FROM tenants WHERE landlord_id=${LID} AND last_name='${p.last}'`));

      // Pay it through Record payment.
      await page.goto(`${BASE}/landlord/payments`, { waitUntil: "domcontentloaded" });
      await page.getByRole("button", { name: "Record payment" }).first().click();
      await pick("Tenant", `${p.first} ${p.last}`);
      await page.getByLabel("Amount").fill(String(p.total));
      await page.getByLabel("Payment date").fill(`2026-09-${pad(p.day)}`);
      await page.getByLabel("Payment method").fill("M-Pesa");
      await page.getByLabel("M-Pesa reference").fill(mpesa);
      await page.getByRole("button", { name: "Record payment" }).last().click();
      R.check(`UI day ${p.day}: payment recorded`, /Payment recorded/.test(await toast()));
    } else {
      // ---------------- through the same API the form calls ----------------
      const r = await api("/tenants/", { token, method: "POST", body: {
        unit_id: p.unit.id, first_name: p.first, last_name: p.last,
        phone: `07${String(20000000 + p.day * 100 + p.k).slice(-8)}`,
        move_in_date: `2026-09-${pad(p.day)}`, move_in_billing: p.payload } });
      if (r.status !== 201 || !r.json.move_in_invoice) { R.check(`API day ${p.day}/${p.k}: tenant + bill`, false, JSON.stringify(r.json)); continue; }
      p.tenantId = r.json.id;
      const pay = await api("/payments/", { token, method: "POST", body: {
        tenant_id: p.tenantId, amount: p.total, payment_date: `2026-09-${pad(p.day)}`,
        payment_method: "M-Pesa", mpesa_reference: mpesa } });
      if (pay.status !== 201) R.check(`API day ${p.day}/${p.k}: payment`, false, JSON.stringify(pay.json));
    }
    p.paymentId = Number(sql(`SELECT id FROM payments WHERE landlord_id=${LID} AND mpesa_reference='${mpesa}' AND NOT is_deleted`));
  }
  R.check(`all ${plan.length} tenants added and paid`, plan.every((p) => p.tenantId && p.paymentId), `${plan.filter((p) => p.paymentId).length}/${plan.length}`);

  // ---------------- every receipt ----------------
  let good = 0;
  const bad = [];
  for (const p of plan) {
    const res = await apiRaw(`/payments/${p.paymentId}/receipt/download`);
    const pdf = `${TMP}/r-${p.paymentId}.pdf`;
    writeFileSync(pdf, Buffer.from(await res.arrayBuffer()));
    const txt = execSync(`pdftotext -raw "${pdf}" -`).toString();
    const mon = p.next ? "Oct 2026" : "Sep 2026";
    const strict = txt.includes(`Rent — ${mon} ${money(p.rentAmount)}`) && txt.includes(`Rent Deposit — ${mon} ${money(p.unit.rent)}`)
      && txt.includes(`Lease Agreement ${money(LEASE_FEE)}`) && !txt.includes("Lease Agreement —") && txt.includes(`${pad(p.day)}/09/2026`)
      && /Balance KES 0\.00/.test(txt);
    if (strict) good += 1; else bad.push(`day ${p.day}: ${txt.split("\n").filter((l) => /Rent|Lease|Date|Balance/.test(l)).join(" · ")}`);
    if (p.ui) {
      execSync(`pdftoppm -png -r 150 -singlefile -y 0 -H 620 "${pdf}" "${TMP}/ui-${p.day}"`);
      await page.setContent(`<body style="margin:18px;background:#e9e9ee;font-family:system-ui">
        <h2 style="margin:0 0 6px">Moved in ${pad(p.day)}/09/2026 — ${p.next ? "box ticked: billed for October" : "box unticked: billed for September (part month)"}</h2>
        <p style="margin:0 0 12px;color:#444">Rent ${money(p.unit.rent)}/month · this bill's rent ${money(p.rentAmount)} · paid ${money(p.total)} on ${pad(p.day)}/09/2026 (M-Pesa ${p.mpesa})</p>
        <img style="width:1240px;border:1px solid #999;background:#fff" src="data:image/png;base64,${readFileSync(`${TMP}/ui-${p.day}.png`).toString("base64")}"></body>`);
      await shooter(page, `day-${pad(p.day)}-${p.next ? "next-month" : "this-month"}`)("receipt", { fullPage: true });
    }
  }
  R.check(`every receipt (${plan.length}) names the right month and amount on every line; lease has no month; dated the move-in day; balance 0`,
    good === plan.length, `${good}/${plan.length}${bad.length ? ` — first problem: ${bad[0]}` : ""}`);

  // ---------------- the report moved by exactly what was paid ----------------
  const after = await reportSep();
  const bB = byMonth(before), bA = byMonth(after);
  const delta = (key, field) => Math.round(((bA[key]?.[field] || 0) - (bB[key]?.[field] || 0)) * 100) / 100;
  const early = plan.filter((p) => !p.next), late = plan.filter((p) => p.next);
  const sum = (xs, f) => xs.reduce((s, x) => s + f(x), 0);
  R.check("report: Rent collected FOR September grew by exactly the part-month rents (days 1–19)",
    delta("2026-09|Rent", "collected") === sum(early, (p) => p.rentAmount), `${delta("2026-09|Rent", "collected")} vs ${sum(early, (p) => p.rentAmount)}`);
  R.check("report: Rent collected FOR October grew by exactly the full rents paid in advance (days 20–30)",
    delta("2026-10|Rent", "collected") === sum(late, (p) => p.rentAmount), `${delta("2026-10|Rent", "collected")} vs ${sum(late, (p) => p.rentAmount)}`);
  R.check("report: lease fees filed under the billed month (September / October)",
    delta("2026-09|Lease Agreement", "collected") === early.length * LEASE_FEE && delta("2026-10|Lease Agreement", "collected") === late.length * LEASE_FEE,
    `${delta("2026-09|Lease Agreement", "collected")} / ${delta("2026-10|Lease Agreement", "collected")}`);
  const cashDelta = Math.round((after.reconciliation.cash_received - before.reconciliation.cash_received) * 100) / 100;
  R.check("report: cash received grew by exactly what the 150 tenants paid", cashDelta === sum(plan, (p) => p.total), `${cashDelta} vs ${sum(plan, (p) => p.total)}`);
  const rentSum = (rep) => rep.summary.find((s) => s.category_name === "Rent");
  R.check("report: rent deposits paid grew by the deposits", Math.round((rentSum(after).deposit_paid - rentSum(before).deposit_paid) * 100) / 100 === sum(plan, (p) => p.unit.rent));
  R.check("report: nothing unexplained (cash = allocated + advance)", after.reconciliation.difference === 0, `${after.reconciliation.difference}`);

  // ---------------- September and October runs, November preview ----------------
  const out = JSON.parse(execSync(`cd ${SERVER} && APP_ENV=development PYTHONPATH=. venv/bin/python scripts/qa_move_in_billing.py ${plan.map((p) => p.tenantId).join(" ")} 2>/dev/null`).toString());
  let sepOk = 0, octOk = 0, novOk = 0;
  const probs = [];
  for (const p of plan) {
    const t = out.tenants[String(p.tenantId)];
    const sep = t.rent_lines["2026-09"] || [], oct = t.rent_lines["2026-10"] || [];
    if ((p.next && sep.length === 0) || (!p.next && sep.length === 1 && sep[0].amount === p.rentAmount)) sepOk += 1; else probs.push(`Sep day ${p.day}: ${JSON.stringify(sep)}`);
    if (oct.length === 1 && oct[0].amount === p.unit.rent && oct[0].type === (p.next ? "move_in" : "monthly")) octOk += 1; else probs.push(`Oct day ${p.day}: ${JSON.stringify(oct)}`);
    if (t.november_rent === p.unit.rent) novOk += 1; else probs.push(`Nov day ${p.day}: ${t.november_rent}`);
  }
  R.check("September run on the 30th: nobody billed September rent twice (days 1–19 keep only the part month; 20–30 none)", sepOk === plan.length, `${sepOk}/${plan.length} ${probs.filter((x) => x.startsWith("Sep"))[0] || ""}`);
  R.check("October run: days 1–19 billed October in full once; days 20–30 NOT billed again (their October rent is the move-in line)", octOk === plan.length, `${octOk}/${plan.length} ${probs.filter((x) => x.startsWith("Oct"))[0] || ""}`);
  R.check("November: every one of them would be billed the full rent", novOk === plan.length, `${novOk}/${plan.length}`);
  R.check("October run created invoices only for the before-20th movers", out.october_run.created === early.length, JSON.stringify(out.october_run));

  const afterInv = await reportSepOct();
  const iB = byMonth(beforeInv), iA = byMonth(afterInv);
  const invDelta = Math.round(((iA["2026-10|Rent"]?.invoiced || 0) - (iB["2026-10|Rent"]?.invoiced || 0)) * 100) / 100;
  R.check("report: October rent invoiced for these tenants = exactly one month's rent each (no double billing)",
    invDelta === sum(plan, (p) => p.unit.rent), `${invDelta} vs ${sum(plan, (p) => p.unit.rent)}`);

  // ---------------- the report on screen ----------------
  const shot = shooter(page, "report");
  await page.goto(`${BASE}/landlord/reports/statements`, { waitUntil: "domcontentloaded" });
  await dismissTours(page);
  await page.getByRole("button", { name: /^Payments$/ }).first().click();
  await page.getByLabel("Paid from").fill("2026-09-01");
  await page.getByLabel("Paid to").fill("2026-09-30");
  await page.getByTestId("report-reconciliation").waitFor({ timeout: 60000 });
  await page.waitForTimeout(2500);
  await page.getByRole("button", { name: "By month" }).first().click();
  await page.waitForTimeout(800);
  await shot("by-month-september-and-october", { fullPage: true });
  await page.getByRole("button", { name: /Allocation ledger/ }).first().click();
  await page.waitForTimeout(800);
  await shot("allocation-ledger", { fullPage: false });

  writeFileSync(`${SHOTS}/plan.json`, JSON.stringify(plan.map(({ payload, ...p }) => p), null, 2));
} catch (err) {
  console.error("MOVE-IN WALKTHROUGH ERROR:", err);
  R.check("walkthrough ran to completion", false, err.message);
  await page.screenshot({ path: `${SHOTS}/zz-error.png` }).catch(() => {});
} finally {
  await browser.close();
}
const failed = R.summary();
writeFileSync(`${SHOTS}/results.json`, JSON.stringify(R.list, null, 2));
process.exit(failed ? 1 : 0);
