/**
 * Items 1 & 8 — proper tables and the landlord's identity on every document
 * and email.
 *
 *  1. Save contact details through Settings (real form), pick theme colours.
 *  2. Render the emails a tenant receives from this landlord and screenshot
 *     them (logo/letterhead, colours, contact details, "via Sahil Pay").
 *  3. Download a receipt, a statement and a report PDF: contact details
 *     present, tables ruled.
 *  4. On-screen report table and the tenant's receipt modal.
 *
 *   node scripts/qa/branding-tables.mjs
 */
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { BASE, API, SHOTS, results, shooter, staffLogin, tenantLogin, apiLogin } from "./helpers.mjs";

const R = results();
const OUT = `${SHOTS}/branding`;
execSync(`mkdir -p ${OUT}`);
const browser = await chromium.launch();

async function getPdf(token, path, name) {
  const res = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  const buf = Buffer.from(await res.arrayBuffer());
  const file = `${OUT}/${name}.pdf`;
  writeFileSync(file, buf);
  execSync(`pdftoppm -png -r 80 -f 1 -l 1 "${file}" "${OUT}/${name}"`);
  return { status: res.status, text: execSync(`pdftotext "${file}" -`).toString() };
}

try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const shot = shooter(page, "branding");
  await staffLogin(page, "landlord@sahilpay.test", "Landlord@123");

  // 1. Contact details through the real form
  await page.goto(`${BASE}/landlord/settings/general`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Contact phone").waitFor({ timeout: 30000 });
  await page.getByLabel("Contact phone").fill("0722 555 101");
  await page.getByLabel("Contact email").fill("rent@acmeproperties.co.ke");
  await page.getByLabel("Website").fill("acmeproperties.co.ke");
  await page.locator("#document-identity").scrollIntoViewIfNeeded();
  await shot("01-settings-letterhead-contacts", { fullPage: false });
  await page.getByRole("button", { name: /^Save/ }).first().click();
  await page.waitForTimeout(2500);
  const token = await apiLogin("landlord@sahilpay.test", "Landlord@123");
  const general = await (await fetch(`${API}/settings/general`, { headers: { Authorization: `Bearer ${token}` } })).json();
  R.check("contact details saved through Settings", general.contact_email === "rent@acmeproperties.co.ke" && general.website === "https://acmeproperties.co.ke",
          `${general.contact_phone} · ${general.contact_email} · ${general.website}`);

  // Theme: teal + deep red (through the receipt-layout API the Settings page uses)
  const layout = await (await fetch(`${API}/settings/receipt-layout`, { headers: { Authorization: `Bearer ${token}` } })).json();
  const put = await fetch(`${API}/settings/receipt-layout`, {
    method: "PUT", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ layout: layout.layout ?? layout.data?.layout, theme: { primary: "#0f766e", secondary: "#9f1239" } }),
  });
  R.check("theme colours saved", put.ok, `HTTP ${put.status}`);
  await page.goto(`${BASE}/landlord/settings/receipt-layout`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await shot("02-settings-theme-colours", { fullPage: false });

  // 2. Emails sent from this landlord's account
  const html = execSync(`cd ../server && . venv/bin/activate && APP_ENV=development python - <<'PY'
from app import create_app
app = create_app()
with app.app_context():
    from extensions import db
    from models import Landlord, Tenant
    from services.reminder_content import build_reminder, KIND_PAYMENT
    from services import email_templates as T
    from services.document_brand import email_brand
    ll = db.session.get(Landlord, 1)
    t = Tenant.query.filter_by(landlord_id=1).first()
    rc = build_reminder(KIND_PAYMENT, t, ll)
    open("${OUT}/email-reminder.html", "w").write(rc.html)
    receipt = T.render_email(brand=email_brand(ll), heading="Payment received — thank you",
        intro="Hi James, we've recorded your payment. Your receipt <strong>PAY-1-000018</strong> is attached.")
    open("${OUT}/email-receipt.html", "w").write(receipt)
    print("ok")
PY`).toString();
  R.check("rendered the landlord's emails", html.includes("ok"));
  const mail = await (await browser.newContext({ viewport: { width: 600, height: 900 } })).newPage();
  for (const name of ["email-reminder", "email-receipt"]) {
    await mail.goto(`file://${OUT}/${name}.html`);
    await mail.waitForTimeout(1500);
    await mail.screenshot({ path: `${OUT}/03-${name}.png`, fullPage: true });
    const body = await mail.content();
    R.check(`${name}: carries theme colour, contact details and company`, body.includes("#0f766e") && body.includes("rent@acmeproperties.co.ke") && body.includes("Acme Properties"));
  }
  const phoneMail = await (await browser.newContext({ viewport: { width: 375, height: 812 }, isMobile: true })).newPage();
  await phoneMail.goto(`file://${OUT}/email-reminder.html`);
  await phoneMail.waitForTimeout(1000);
  await phoneMail.screenshot({ path: `${OUT}/04-email-reminder-on-phone.png`, fullPage: true });

  // 3. PDFs
  const payId = JSON.parse(execSync(`psql "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay" -tAc "SELECT json_agg(id) FROM (SELECT id FROM payments WHERE landlord_id=1 AND status='confirmed' AND is_deleted=false ORDER BY id DESC LIMIT 1) x"`).toString())[0];
  const tenantId = JSON.parse(execSync(`psql "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay" -tAc "SELECT json_agg(id) FROM (SELECT id FROM tenants WHERE landlord_id=1 AND is_deleted=false ORDER BY id LIMIT 1) x"`).toString())[0];
  for (const [path, name, label] of [
    [`/payments/${payId}/receipt/download`, "05-receipt", "receipt"],
    [`/reports/statements/tenant/${tenantId}?format=pdf`, "06-tenant-statement", "tenant statement"],
    [`/reports/statements/arrears?format=pdf`, "07-arrears-report", "arrears report"],
    [`/tenants/${tenantId}/statement/download`, "08-statement-legacy", "tenant statement (tenant page)"],
  ]) {
    const pdf = await getPdf(token, path, name);
    R.check(`${label}: PDF carries the landlord's contact details`, pdf.status === 200 && pdf.text.includes("rent@acmeproperties.co.ke"), `HTTP ${pdf.status}`);
  }

  // 4. On-screen tables
  await page.goto(`${BASE}/landlord/reports/statements`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await page.getByRole("button", { name: "Arrears" }).first().click();
  await page.waitForTimeout(1200);
  const gen = page.getByRole("button", { name: /Generate/ }).first();
  if (await gen.isEnabled().catch(() => false)) {
    await gen.click();
    await page.waitForTimeout(4000);
  }
  await shot("09-onscreen-report-table", { fullPage: false });
  R.check("on-screen report uses ruled tables", (await page.locator("table.doc-table").count()) > 0);

  const tenant = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true })).newPage();
  await tenantLogin(tenant, "+254711000001");
  await tenant.goto(`${BASE}/portal/pay`, { waitUntil: "domcontentloaded" });
  await tenant.waitForTimeout(2500);
  const receiptBtn = tenant.getByRole("button", { name: /receipt/i }).first();
  if (await receiptBtn.isVisible().catch(() => false)) {
    await receiptBtn.click();
    await tenant.waitForTimeout(2500);
    await tenant.screenshot({ path: `${OUT}/10-tenant-receipt-modal.png`, fullPage: false });
    R.check("tenant receipt modal uses ruled tables", (await tenant.locator("table.doc-table").count()) >= 2);
  } else {
    R.check("tenant has a receipt to open", false, "no confirmed payment row visible");
  }
} catch (err) {
  console.error(err);
  R.check("script completed without errors", false, err.message.split("\n")[0]);
} finally {
  await browser.close();
  process.exit(R.summary() ? 1 : 0);
}
