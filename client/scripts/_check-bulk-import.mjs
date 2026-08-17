/**
 * Drive the bulk-import wizard the way a person does: upload a spreadsheet with
 * the customer's own column names, check the mapping was guessed, look at the
 * preview, and commit.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const WEB = "http://localhost:5173";
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 1100 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

const results = [];
function say(ok, label, detail = "") {
  results.push(ok);
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
}

// A file using the customer's words, not ours — plus messy money and a
// deliberate duplicate account number.
const stamp = Date.now();
const csv = path.join(os.tmpdir(), `units-${stamp}.csv`);
fs.writeFileSync(csv, [
  "Estate,House No.,Monthly Rent,Acc No",
  `Riverside Apartments,IMP${stamp}A,"KES 25,000",`,
  `Riverside Apartments,IMP${stamp}B,30000,DUPE-${stamp}`,
  `Riverside Apartments,IMP${stamp}C,30000,DUPE-${stamp}`,
].join("\n"));

await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
await page.locator('input[name="email"]').fill("landlord@sahilpay.test");
await page.locator('input[name="password"]').fill("Landlord@123");
await page.getByRole("button", { name: "Log in" }).click();
await page.waitForURL(/\/landlord/, { timeout: 20000 });

// Discoverability was the actual complaint: "I cannot find the bulk upload".
const sidebar = await page.locator("aside").innerText();
say(/Bulk import/.test(sidebar), "Bulk import is in the sidebar");

await page.getByRole("link", { name: "Bulk import" }).click();
await page.waitForTimeout(1500);
let body = await page.locator("main").innerText();
say(/Properties/.test(body) && /Units/.test(body) && /Tenants/.test(body),
    "All three imports are offered");
say(/Step 1 of 3/.test(body), "The order is spelled out");

// Units tab.
await page.getByRole("button", { name: "Units", exact: true }).click();
await page.waitForTimeout(600);

await page.locator('input[type="file"]').setInputFiles(csv);
await page.waitForTimeout(400);
await page.getByRole("button", { name: "Read the file" }).click();
await page.waitForTimeout(2000);

body = await page.locator("main").innerText();
say(/3 rows found/.test(body), "The file was read", body.match(/\d+ rows? found/)?.[0] || "");

// The mapping should already be right for ordinary column names.
const selected = await page.locator("main select").evaluateAll((els) =>
  els.map((e) => e.value).filter(Boolean));
say(selected.includes("Estate") && selected.includes("House No.") &&
    selected.includes("Monthly Rent"),
    "Columns were matched automatically", selected.join(", "));

await page.getByRole("button", { name: "Check the file" }).click();
await page.waitForTimeout(2500);

body = await page.locator("main").innerText();
// The summary labels are CSS-uppercased, and innerText reflects that.
say(/will import/i.test(body), "Preview renders");
say(/used twice in this file/.test(body),
    "The duplicate account number is caught before anything is written");
say(/Rejected/.test(body) && /Ready/.test(body),
    "Good and bad rows are shown side by side");

const importBtn = page.getByRole("button", { name: /^Import \d+ rows?$/ });
say(await importBtn.count() > 0, "Commit button offers only the valid rows",
    (await importBtn.innerText().catch(() => "")).trim());

await importBtn.click();
await page.waitForTimeout(3000);
body = await page.locator("main").innerText();
say(/imported/.test(body), "Import completed", body.split("\n").find((l) => /imported/.test(l)) || "");
say(/Next: Tenants/.test(body), "It offers the next step in the sequence");

say(errors.length === 0, "No uncaught page errors", errors[0] || "");

fs.unlinkSync(csv);
await browser.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
process.exit(results.every(Boolean) ? 0 : 1);
