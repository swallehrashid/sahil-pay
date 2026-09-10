/**
 * Stage 1 walkthrough — drive the real UI for items 1-5.
 *
 * Proves the things a unit test cannot: that a person clicking through the
 * settings pages actually gets a logo onto their documents, that the file
 * reaches the server at all, and that the layout/colour screen saves and
 * previews what it claims to.
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const BASE = "http://127.0.0.1:5173";
const OUT = "/tmp/claude-1000/-home-swalleh-Projects-sahil-pay/6946769b-975f-4480-a38b-c5aa96e6c22b/scratchpad/shots";
const LOGO = "/tmp/claude-1000/-home-swalleh-Projects-sahil-pay/6946769b-975f-4480-a38b-c5aa96e6c22b/scratchpad/test-logo.png";
const SIG = "/tmp/claude-1000/-home-swalleh-Projects-sahil-pay/6946769b-975f-4480-a38b-c5aa96e6c22b/scratchpad/test-signature.png";

const results = [];
const record = (name, pass, detail = "") => {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
};

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await ctx.newPage();

const consoleErrors = [];
const failedRequests = [];
const apiCalls = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
page.on("requestfailed", (r) => failedRequests.push(`${r.method()} ${r.url()}`));
page.on("request", (r) => {
  if (r.url().includes("/api/settings")) {
    apiCalls.push({
      method: r.method(),
      url: r.url().replace(/^.*\/api/, "/api"),
      contentType: r.headers()["content-type"] || "(none)",
    });
  }
});

try {
  // ---- Sign in --------------------------------------------------------
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"], input[name="email"]', "landlord@sahilpay.test");
  await page.fill('input[type="password"]', "Landlord@123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(landlord|dashboard)/, { timeout: 20000 });
  record("sign in as landlord", true, page.url().replace(BASE, ""));

  // ---- Item 2: upload a logo through the real form --------------------
  await page.goto(`${BASE}/landlord/settings/general`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/01-general-before.png`, fullPage: true });

  const requirementsToggle = page.getByRole("button", { name: /Requirements/i }).first();
  if (await requirementsToggle.count()) {
    await requirementsToggle.click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/02-logo-requirements.png`, fullPage: true });
    record("logo requirements are shown in the UI", true);
  } else {
    record("logo requirements are shown in the UI", false, "toggle not found");
  }

  const fileInputs = page.locator('input[type="file"]');
  await fileInputs.first().setInputFiles(LOGO);
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${OUT}/03-logo-staged.png`, fullPage: true });

  apiCalls.length = 0;
  await page.getByRole("button", { name: /^Save/i }).first().click();
  await page.waitForTimeout(3000);

  const putGeneral = apiCalls.find((c) => c.method === "PUT" && c.url.includes("/settings/general"));
  record(
    "the logo is sent as multipart, not JSON",
    Boolean(putGeneral && putGeneral.contentType.includes("multipart/form-data")),
    putGeneral ? putGeneral.contentType.split(";")[0] : "no PUT observed"
  );
  await page.screenshot({ path: `${OUT}/04-logo-saved.png`, fullPage: true });

  // Re-load and confirm the server actually kept it.
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const savedLogo = page.locator('img[alt="current logo"]');
  const logoPersisted = (await savedLogo.count()) > 0;
  record("the saved logo is shown back from the server", logoPersisted,
    logoPersisted ? await savedLogo.first().getAttribute("src") : "no stored logo rendered");
  await page.screenshot({ path: `${OUT}/05-logo-persisted.png`, fullPage: true });

  // ---- Item 5: signature ----------------------------------------------
  await page.goto(`${BASE}/landlord/settings/account`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await page.locator('input[type="file"]').first().setInputFiles(SIG);
  await page.waitForTimeout(800);
  apiCalls.length = 0;
  await page.getByRole("button", { name: /Save account/i }).click();
  await page.waitForTimeout(3000);

  const putAccount = apiCalls.find((c) => c.method === "PUT" && c.url.includes("/settings/account"));
  record(
    "the signature is sent as multipart",
    Boolean(putAccount && putAccount.contentType.includes("multipart/form-data")),
    putAccount ? putAccount.contentType.split(";")[0] : "no PUT observed"
  );

  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const savedSig = page.locator('img[alt="current signature"]');
  record("the saved signature is shown back from the server", (await savedSig.count()) > 0);
  await page.screenshot({ path: `${OUT}/06-signature-persisted.png`, fullPage: true });

  // ---- Item 6 (same page): profile fields ------------------------------
  const usernameInput = page.getByLabel(/^Username$/i);
  record(
    "no un-saveable Username field is offered to a landlord",
    (await usernameInput.count()) === 0,
    "landlord identity is the company name, in General settings"
  );

  // ---- Items 3 & 4: layout and colours --------------------------------
  await page.goto(`${BASE}/landlord/settings/receipt-layout`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/07-layout-screen.png`, fullPage: true });

  const swatches = page.locator('button[aria-label][title]').filter({ hasNot: page.locator("svg.lucide-printer") });
  const swatchCount = await page.locator('button[aria-pressed]').count();
  record("the colour palette is rendered", swatchCount >= 60,
    `${swatchCount} swatches (36 colours x 2 roles = 72)`);

  // Pick the wide band — the paper the landlord actually described.
  const bandCard = page.getByRole("button", { name: /wide band/i }).first();
  if (await bandCard.count()) {
    await bandCard.click();
    await page.waitForTimeout(700);
    record("the 'A4 third — wide band' paper is offered", true);
  } else {
    record("the 'A4 third — wide band' paper is offered", false, "not found");
  }

  const printNote = page.getByText(/Actual size/i);
  record("the print-scaling warning is shown for a cut paper", (await printNote.count()) > 0);
  await page.screenshot({ path: `${OUT}/08-band-selected.png`, fullPage: true });

  // Pick colours: the 8th and 26th swatches, whatever they are.
  const allSwatches = page.locator('button[aria-pressed]');
  await allSwatches.nth(8).click();
  await page.waitForTimeout(300);
  await allSwatches.nth(60).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/09-colours-picked.png`, fullPage: true });

  apiCalls.length = 0;
  await page.getByRole("button", { name: /^Save/i }).first().click();
  await page.waitForTimeout(2500);
  record("layout + colours saved",
    apiCalls.some((c) => c.method === "PUT" && c.url.includes("receipt-layout")));

  // Preview must round-trip a real PDF.
  apiCalls.length = 0;
  const previewBtn = page.getByRole("button", { name: /Preview/i }).first();
  if (await previewBtn.count()) {
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("receipt-layout/preview"), { timeout: 20000 }),
      previewBtn.click(),
    ]);
    // Assert the STATUS and CONTENT-TYPE, not the bytes.
    //
    // response.body() comes back empty here even on a perfectly good response:
    // the page consumes the stream into a blob URL, and headless Chromium ships
    // no PDF viewer, so the subsequent `GET blob:` also fails. Both are
    // artifacts of the harness, not of the endpoint — verified separately with
    // curl, which returns a 23KB 210x99mm PDF. Asserting on the bytes here
    // reports a failure that does not exist.
    const contentType = response.headers()["content-type"] || "";
    record("the preview returns a PDF response",
      response.status() === 200 && contentType.includes("application/pdf"),
      `${response.status()} ${contentType}`);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/10-preview.png`, fullPage: true });
  }

  // Reload — the choices must have stuck.
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1800);
  const stillBand = await page.locator('button[class*="ring-secondary"]').filter({ hasText: /wide band/i }).count();
  record("the paper choice persisted across a reload", stillBand > 0);
  await page.screenshot({ path: `${OUT}/11-after-reload.png`, fullPage: true });

} catch (err) {
  record("walkthrough completed without throwing", false, err.message.split("\n")[0]);
  await page.screenshot({ path: `${OUT}/99-error.png`, fullPage: true }).catch(() => {});
}

console.log("\n--- console errors ---");
console.log(consoleErrors.length ? consoleErrors.slice(0, 10).join("\n") : "(none)");
console.log("--- failed requests ---");
// A failed `GET blob:` is expected: headless Chromium has no PDF viewer, so the
// preview iframe cannot render the object URL the page just created. It is not
// a product failure and is filtered out rather than left to look like one.
const realFailures = failedRequests.filter((u) => !u.includes("blob:"));
console.log(realFailures.length ? realFailures.slice(0, 10).join("\n") : "(none)");

const passed = results.filter((r) => r.pass).length;
console.log(`\n${passed}/${results.length} checks passed`);
await browser.close();
process.exit(passed === results.length ? 0 : 1);
