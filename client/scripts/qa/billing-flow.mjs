/**
 * Billing walkthrough: installments, lock/unlock, confirmation-only payments,
 * receipts. Runs against local dev in MPESA simulation mode, where the M-Pesa
 * reply is played through the real callback handler.
 *
 *   node scripts/qa/billing-flow.mjs
 */
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import { BASE, SHOTS, results, shooter, staffLogin } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execSync(`psql "${DB}" -tAc "${q.replace(/"/g, '\\"')}"`).toString().trim();
const R = results();
const browser = await chromium.launch();

async function pdfInfo(download, name) {
  const path = `${SHOTS}/billing/${name}.pdf`;
  await download.saveAs(path);
  execSync(`pdftoppm -png -r 70 -f 1 -l 1 "${path}" "${SHOTS}/billing/${name}"`);
  return execSync(`pdftotext "${path}" -`).toString();
}

async function payFlow(page, shot, { amount, label, purpose = "subscription" }) {
  await page.getByTestId(purpose === "sms" ? "buy-sms-btn" : "pay-subscription").click().catch(async () => {
    await page.getByRole("button", { name: purpose === "sms" ? /Buy SMS/ : /Pay subscription/ }).first().click();
  });
  await page.waitForTimeout(600);
  if (purpose === "sms") await page.getByRole("tab", { name: "SMS credits" }).click();
  await page.getByTestId("pay-amount").fill(String(amount));
  await page.getByLabel(/M-Pesa phone number/).fill("0716827390");
  await shot(`${label}-form`, { fullPage: false });
  await page.getByTestId("send-prompt").click();
  await page.getByTestId("payment-waiting").waitFor({ timeout: 20000 });
  await shot(`${label}-waiting-for-mpesa`, { fullPage: false });
  const pendingRow = sql("SELECT status||'/'||is_verified FROM billing_transactions WHERE landlord_id=1 ORDER BY id DESC LIMIT 1");
  R.check(`${label}: transaction is pending and unverified before M-Pesa confirms`, pendingRow === "pending/false", pendingRow);
  await page.getByTestId("simulate-success").click();
  await page.getByTestId("payment-confirmed").waitFor({ timeout: 20000 });
  await shot(`${label}-confirmed`, { fullPage: false });
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("modal-receipt").click()]);
  const text = await pdfInfo(dl, `${label}-receipt`);
  R.check(`${label}: receipt downloads, branded Sahil Pay, marked PAID`, /Sahil Pay/i.test(text) && /PAID/.test(text) && text.includes(String(amount.toLocaleString("en-US"))), `${text.length} chars`);
  await page.getByRole("button", { name: "Done" }).click();
  await page.waitForTimeout(1200);
}

try {
  // Arrange: KES 10,000 owed, overdue past grace → locked.
  sql("UPDATE subscriptions SET amount_due=10000, balance_due_since=CURRENT_DATE-20, access_override_until=NULL, status='past_due', next_billing_date=CURRENT_DATE+10 WHERE landlord_id=1");
  sql("UPDATE landlords SET is_on_trial=false WHERE id=1");

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const shot = shooter(page, "billing");
  await staffLogin(page, "landlord@sahilpay.test", "Landlord@123");
  await page.goto(`${BASE}/landlord/dashboard`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("subscription-locked").waitFor({ timeout: 20000 });
  await shot("01-locked-dashboard", { fullPage: false });
  R.check("locked account shows the lock screen instead of the dashboard", true);

  await page.getByRole("button", { name: /Go to Billing and pay/ }).click();
  await page.getByTestId("account-card").waitFor({ timeout: 20000 });
  await shot("02-billing-page-locked");
  R.check("billing page stays reachable while locked", await page.getByText("Account locked — unpaid balance").isVisible());

  await payFlow(page, shot, { amount: 6000, label: "03-installment-6000" });
  const after6000 = sql("SELECT amount_due FROM subscriptions WHERE landlord_id=1");
  R.check("paying 6,000 of 10,000 leaves 4,000", Number(after6000) === 4000, after6000);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByTestId("account-card").waitFor();
  await shot("04-after-installment-still-locked", { fullPage: false });
  R.check("account is still locked with 4,000 owing", await page.getByText("Account locked — unpaid balance").isVisible());

  await payFlow(page, shot, { amount: 4000, label: "05-clear-balance-4000" });
  const cleared = sql("SELECT amount_due||'/'||status FROM subscriptions WHERE landlord_id=1");
  R.check("balance cleared and account active", cleared.startsWith("0.00/active"), cleared);
  await page.goto(`${BASE}/landlord/dashboard`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  R.check("dashboard opens again after the balance is cleared", !(await page.getByTestId("subscription-locked").isVisible()));
  await shot("06-dashboard-open-again", { fullPage: false });

  await page.goto(`${BASE}/landlord/settings/billing`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("account-card").waitFor();
  const smsBefore = Number(sql("SELECT sms_balance FROM landlords WHERE id=1"));
  await payFlow(page, shot, { amount: 150, label: "07-sms-150", purpose: "sms" });
  const smsAfter = Number(sql("SELECT sms_balance FROM landlords WHERE id=1"));
  R.check("SMS credits added only after confirmation", smsAfter > smsBefore, `${smsBefore} → ${smsAfter}`);

  // A paybill code M-Pesa never reported stays pending.
  await page.getByLabel("M-Pesa code").fill("SJK9FAKE123");
  await page.getByRole("button", { name: "Check payment" }).click();
  await page.waitForTimeout(2500);
  await shot("08-unseen-paybill-code-pending", { fullPage: false });
  const claim = sql("SELECT status||'/'||is_verified FROM billing_transactions WHERE payment_reference='SJK9FAKE123' ORDER BY id DESC LIMIT 1");
  R.check("an M-Pesa code that never landed is saved as pending, not confirmed", claim === "pending/false", claim);

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByTestId("account-card").waitFor();
  await page.waitForTimeout(1500);
  await shot("09-billing-page-payments-table");
  const firstReceipt = page.locator('[data-testid^="receipt-"]').first();
  const [dl] = await Promise.all([page.waitForEvent("download"), firstReceipt.click()]);
  const txt = await pdfInfo(dl, "10-receipt-from-table");
  R.check("receipt downloads from the payments table", txt.includes("Payment Receipt"));

  // Phone view
  const phone = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true })).newPage();
  const pshot = shooter(phone, "billing");
  await staffLogin(phone, "landlord@sahilpay.test", "Landlord@123");
  await phone.goto(`${BASE}/landlord/settings/billing`, { waitUntil: "domcontentloaded" });
  await phone.getByTestId("account-card").waitFor();
  await pshot("11-phone-billing");
  R.check("billing page has no sideways scroll on a phone",
    await phone.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1));
} catch (err) {
  console.error(err);
  R.check("script completed without errors", false, err.message.split("\n")[0]);
} finally {
  sql("DELETE FROM billing_transactions WHERE payment_reference='SJK9FAKE123'");
  await browser.close();
  process.exit(R.summary() ? 1 : 0);
}
