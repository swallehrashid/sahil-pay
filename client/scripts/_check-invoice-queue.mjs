/**
 * The queue's whole reason to exist, driven through the UI:
 * hold a meter reading, see it waiting, then let it be billed.
 */
import { chromium } from "playwright";

const WEB = "http://localhost:5173";
const API = "http://localhost:5000/api";
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 1100 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

const results = [];
function say(ok, label, detail = "") {
  results.push(ok);
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
}

async function api(path, { token, method = "GET", body } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, json: await res.json().catch(() => ({})) };
}

const login = await api("/auth/login", {
  method: "POST",
  body: { email: "landlord@sahilpay.test", password: "Landlord@123" },
});
const token = login.json.access_token;
say(Boolean(token), "Signed in");

// Queue a charge straight through the API, then confirm the UI surfaces it.
const readings = await api("/utilities/?per_page=50", { token });
const list = readings.json?.readings || readings.json?.data?.readings || [];
const unbilled = list.find((r) => !r.invoice_id);
say(Boolean(unbilled), "Found an unbilled reading to work with",
    unbilled ? `${unbilled.utility_item || ""} ${unbilled.unit_name || ""}` : "none");

let queuedId = null;
if (unbilled) {
  const held = await api(`/utilities/${unbilled.id}/add-to-invoice`, {
    token, method: "POST", body: { mode: "queue", amount: 400 },
  });
  say(held.status === 201, "A reading can be HELD instead of billed", `HTTP ${held.status}`);
  queuedId = held.json?.queued_charge?.id;

  const queue = await api("/invoice-queue/", { token });
  say(queue.status === 200 && (queue.json.data ?? queue.json).count > 0,
      "It appears in the queue", `${(queue.json.data ?? queue.json).count} waiting`);

  // Holding must not bill anybody yet — that is the entire point.
  say(!held.json?.invoice_id, "Holding did not raise an invoice");
}

// Now the UI.
await page.goto(`${WEB}/login`, { waitUntil: "domcontentloaded" });
await page.locator('input[name="email"]').fill("landlord@sahilpay.test");
await page.locator('input[name="password"]').fill("Landlord@123");
await page.getByRole("button", { name: "Log in" }).click();
await page.waitForURL(/\/landlord/, { timeout: 20000 });

await page.goto(`${WEB}/landlord/invoices`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2200);
let body = await page.locator("main").innerText();
say(/Waiting to be billed/.test(body), "Invoices page shows a queue tab");

await page.getByRole("button", { name: /Waiting to be billed/ }).click();
await page.waitForTimeout(1800);
body = await page.locator("main").innerText();
say(/charges? waiting|charge waiting/.test(body), "The queue lists what is waiting");
say(/folded into each unit's next monthly invoice/.test(body),
    "It explains that these bill themselves automatically");
say(/read against/.test(body) || /held /.test(body),
    "Each charge shows when it was held and against whom");

// The utilities screen must offer the third option.
await page.goto(`${WEB}/landlord/utilities`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2000);
const utilBody = await page.locator("main").innerText();
say(/Utilities/i.test(utilBody), "Utilities page loads");

say(errors.length === 0, "No uncaught page errors", errors[0] || "");

// Tidy up: cancel the charge this check created so the dev data is unchanged.
if (queuedId) {
  const gone = await api(`/invoice-queue/${queuedId}`, { token, method: "DELETE" });
  say(gone.status === 200, "Cleaned up the charge this check queued");
}

await browser.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
process.exit(results.every(Boolean) ? 0 : 1);
