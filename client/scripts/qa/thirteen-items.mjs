/**
 * September-2026 thirteen-item release — end-to-end walkthrough with screenshots.
 *
 * Runs against the scale estate (seed_scale.py --months 5): 100 properties,
 * 1,000 units, ~950 tenants, five months of billing and payments driven through
 * the production engine.
 *
 *   QA_SHOTS=../.qa/2026-09-29-thirteen-items node scripts/qa/thirteen-items.mjs
 *
 * Every numbered folder is one item. Receipts are the real PDFs from the API,
 * rasterised exactly as a printer receives them (pdftoppm) and shown next to
 * the in-app preview, so "what you preview is what prints" is visible.
 */
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { BASE, API, SHOTS, results, shooter, staffLogin, dismissTours, api, apiLogin } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execSync(`psql "${DB}" -tAc "${q.replace(/"/g, '\\"')}"`).toString().trim();
const EMAIL = "scale-pm@sahilpay.test";
const PASSWORD = "ScaleTest123!";
const TMP = process.env.QA_TMP || "/tmp/sahilpay-qa-13";
mkdirSync(TMP, { recursive: true });
const LOGO = process.env.QA_LOGO;

const R = results();
const LID = sql(`SELECT l.id FROM landlords l JOIN users u ON u.id=l.user_id WHERE u.email='${EMAIL}'`);
console.log(`scale landlord #${LID}: ${sql(`SELECT count(*) FROM properties WHERE landlord_id=${LID} AND NOT is_deleted`)} properties, `
  + `${sql(`SELECT count(*) FROM units u JOIN properties p ON p.id=u.property_id WHERE p.landlord_id=${LID} AND NOT u.is_deleted`)} units, `
  + `${sql(`SELECT count(*) FROM tenants WHERE landlord_id=${LID} AND NOT is_deleted`)} tenants, `
  + `${sql(`SELECT count(*) FROM invoices WHERE landlord_id=${LID}`)} invoices, `
  + `${sql(`SELECT count(*) FROM payments WHERE landlord_id=${LID}`)} payments`);

const token = await apiLogin(EMAIL, PASSWORD);
const H = { Authorization: `Bearer ${token}` };

async function apiRaw(path, init = {}) {
  return fetch(`${API}${path}`, { ...init, headers: { ...H, ...(init.headers || {}) } });
}
async function pdfToPng(pdfBytes, name, dpi = 110) {
  const pdf = `${TMP}/${name}.pdf`;
  writeFileSync(pdf, Buffer.from(pdfBytes));
  execSync(`pdftoppm -png -r ${dpi} -singlefile "${pdf}" "${TMP}/${name}"`);
  const info = execSync(`pdfinfo "${pdf}"`).toString();
  return { png: `${TMP}/${name}.png`, info, pdf };
}
async function showImages(page, title, images, note = "") {
  const tiles = images.map(({ label, png, width = 620 }) => `
    <figure style="margin:0;display:inline-block;vertical-align:top;margin-right:18px">
      <figcaption style="font:600 14px system-ui;margin:0 0 6px;color:#222">${label}</figcaption>
      <img src="data:image/png;base64,${readFileSync(png).toString("base64")}"
           style="width:${width}px;border:1px solid #999;box-shadow:0 2px 10px #0003;background:#fff">
    </figure>`).join("");
  await page.setContent(`<html><body style="margin:18px;background:#e9e9ee;font-family:system-ui">
    <h2 style="margin:0 0 4px">${title}</h2><p style="margin:0 0 14px;color:#444">${note}</p>${tiles}</body></html>`);
}
async function toastText(page) {
  // Toasts stack bottom-right; read the newest.
  const toasts = page.locator("div.fixed.bottom-6 p");
  await toasts.last().waitFor({ timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(300);
  return (await toasts.allTextContents().catch(() => [])).join(" | ");
}
const combo = (page, label) => page.getByRole("combobox", { name: new RegExp(`^${label}( \\*)?$`) }).last();
async function pick(page, label, text) {
  await combo(page, label).click();
  const box = page.locator('[role="listbox"]').last();
  await box.waitFor({ timeout: 15000 });
  await page.locator('[role="searchbox"]').last().fill(text);
  await page.waitForTimeout(300);
  await box.locator('[role="option"]').first().click();
  await page.waitForTimeout(300);
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message));

try {
  // ------------------------------------------------------------------ setup
  // A real letterhead: logo, company name, contacts — and the top-third paper.
  {
    const fd = new FormData();
    fd.append("company_name", "Raa Property Management");
    fd.append("company_address", "Anju Plaza, Opp Mathai Supermarket\nP.O Box 2932-10140, Nyeri");
    fd.append("contact_phone", "0710 351 891");
    fd.append("contact_email", "info@raaproperty.co.ke");
    fd.append("website", "https://raaproperty.co.ke");
    if (LOGO) fd.append("logo", new Blob([readFileSync(LOGO)], { type: "image/png" }), "logo.png");
    const r = await apiRaw("/settings/general", { method: "PUT", body: fd });
    R.check("setup: letterhead + logo saved", r.ok, `${r.status}`);
    const cur = await (await apiRaw("/settings/receipt-layout")).json();
    const put = await apiRaw("/settings/receipt-layout", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout: { ...cur.layout, paper: "a4_third_band", letterhead: { logo: 1, title: 1, contact: 1, title_align: "left" } }, theme: cur.theme }),
    });
    R.check("setup: receipt paper = A4 third (portrait, top third)", put.ok, `${put.status}`);
  }

  await staffLogin(page, EMAIL, PASSWORD);

  // ============================================ 3 + 8 receipt layout & letterhead
  {
    const shot = shooter(page, "03-receipt-layout-portrait-third");
    await page.goto(`${BASE}/landlord/settings/receipt-layout`, { waitUntil: "domcontentloaded" });
    await dismissTours(page);
    await page.waitForSelector("text=Letterhead size", { timeout: 30000 });
    await page.getByText("A4 third — portrait (top third of the page)").click();
    await shot("settings-paper-choice", { fullPage: false });

    // The real receipt for a real payment, as the printer receives it.
    const pid = sql(`SELECT p.id FROM payments p JOIN payment_allocations a ON a.payment_id=p.id
      JOIN invoice_line_items li ON li.id=a.line_item_id WHERE p.landlord_id=${LID} AND p.status='confirmed'
      AND li.subcategory='balance' GROUP BY p.id HAVING count(*)>=1 ORDER BY p.id DESC LIMIT 1`);
    const res = await apiRaw(`/payments/${pid}/receipt/download`);
    const band = await pdfToPng(await res.arrayBuffer(), "receipt-band");
    const portrait = /595\.\d+ x 841\.\d+ pts \(A4\)/.test(band.info);
    R.check("3: the top-third receipt PDF is an A4 PORTRAIT page (prints as previewed)", portrait,
      band.info.match(/Page size:.*$/m)?.[0]);
    R.check("3: one page only", /Pages:\s+1\b/.test(band.info));

    // The in-app preview of the same layout — drawn from the PDF itself.
    await page.getByRole("button", { name: "Update preview" }).click();
    await page.getByTestId("receipt-preview").locator("canvas").first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(800);
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot("settings-preview-portrait-third", { fullPage: false });
    await page.getByTestId("receipt-preview").screenshot({ path: `${TMP}/preview-el.png` });
    const layoutNow = await (await apiRaw("/settings/receipt-layout")).json();
    const samplePdf = await apiRaw("/settings/receipt-layout/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout: { ...layoutNow.layout, paper: "a4_third_band" }, theme: layoutNow.theme }) });
    const printed = await pdfToPng(await samplePdf.arrayBuffer(), "preview-printed", 70);
    await showImages(page, "Item 3 — the preview on screen IS the page that prints",
      [{ label: "In the app: Settings → Receipts → Preview", png: `${TMP}/preview-el.png`, width: 560 },
       { label: "The PDF the printer receives (A4 portrait)", png: printed.png, width: 560 }],
      "Both are the same file. The page is an upright A4 sheet with the receipt in its top third, so a print dialog has nothing to turn to landscape.");
    await shot("preview-equals-print", { fullPage: true });
    await page.goto(`${BASE}/landlord/settings/receipt-layout`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("text=Letterhead size", { timeout: 30000 });

    await showImages(page, "Item 3 — what prints: the actual receipt PDF (A4 portrait, receipt in the top third)",
      [{ label: `Receipt for payment #${pid} — full A4 sheet as sent to the printer`, png: band.png, width: 700 }],
      "Every A4 paper is now generated as a real A4 page with the receipt already in place, so the print dialog has nothing to rotate or rescale. Cut along the dashed line.");
    await shot("printed-a4-sheet-top-third", { fullPage: true });
    execSync(`pdftoppm -png -r 200 -singlefile -y 0 -H 800 -W 1654 "${band.pdf}" "${TMP}/receipt-band-zoom"`);
    await showImages(page, "Item 3 / 13 — the receipt itself at print resolution (top third)",
      [{ label: "Top third of the sheet, 200 dpi", png: `${TMP}/receipt-band-zoom.png`, width: 1300 }],
      "Big logo, bold title and company name, contacts on the right, tight rows, bigger type, and a month on every line.");
    await shot("receipt-top-third-zoom", { fullPage: true });

    // 8 — letterhead sizes: 100% vs bigger logo/name/contacts
    const shot8 = shooter(page, "08-letterhead-sizes");
    await page.goto(`${BASE}/landlord/settings/receipt-layout`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("text=Letterhead size", { timeout: 30000 });
    await page.locator("#lh-logo").scrollIntoViewIfNeeded();
    await shot8("letterhead-sliders-100", { fullPage: false });
    const cur = await (await apiRaw("/settings/receipt-layout")).json();
    const previews = [];
    for (const [label, lh] of [["100% (standard)", { logo: 1, title: 1, contact: 1 }],
                               ["Logo 150%, name 125%, contacts 120%", { logo: 1.5, title: 1.25, contact: 1.2 }],
                               ["Logo 70%, name 90%, contacts 90%", { logo: 0.7, title: 0.9, contact: 0.9 }]]) {
      const r = await apiRaw("/settings/receipt-layout/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ layout: { ...cur.layout, paper: "a4_third_band", letterhead: { ...lh, title_align: "left" } }, theme: cur.theme }),
      });
      const img = await pdfToPng(await r.arrayBuffer(), `lh-${previews.length}`);
      execSync(`pdftoppm -png -r 110 -singlefile -y 0 -H 440 "${img.pdf}" "${TMP}/lh-${previews.length}-top"`);
      previews.push({ label, png: `${TMP}/lh-${previews.length}-top.png`, width: 900 });
    }
    // Drive the real slider too, so the setting is saved through the UI.
    await page.locator("#lh-logo").fill("1.5");
    await page.locator("#lh-title").fill("1.25");
    await page.getByRole("button", { name: "Save layout" }).click();
    R.check("8: letterhead sizes saved from Settings", /Saved/.test(await toastText(page)));
    await shot8("letterhead-sliders-saved-150", { fullPage: false });
    const saved = await (await apiRaw("/settings/receipt-layout")).json();
    R.check("8: saved layout carries the logo/title sizes", saved.layout.letterhead.logo === 1.5 && saved.layout.letterhead.title === 1.25,
      JSON.stringify(saved.layout.letterhead));
    await showImages(page, "Item 8 — letterhead sizes (logo · company name · contact info)", previews.map((p) => ({ ...p, width: 900 })));
    await shot8("letterhead-size-comparison", { fullPage: true });
  }

  // ======================================================= 7 search with spaces
  {
    const shot = shooter(page, "07-search-with-spaces");
    const [fn, ln] = sql(`SELECT first_name||'|'||last_name FROM tenants WHERE landlord_id=${LID} AND NOT is_deleted
      AND first_name<>'Multi' ORDER BY id DESC LIMIT 1`).split("|");
    const expected = Number(sql(`SELECT count(*) FROM tenants t JOIN units u ON u.id=t.unit_id JOIN properties p ON p.id=u.property_id
      WHERE t.landlord_id=${LID} AND NOT t.is_deleted AND NOT u.is_deleted AND NOT p.is_deleted
      AND t.first_name ILIKE '%${fn}%' AND t.last_name ILIKE '%${ln}%'`));
    await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "domcontentloaded" });
    await dismissTours(page);
    const box = page.getByRole("searchbox", { name: "Search tenants" });
    // Type it the way a person does: a word, a pause, a space, a pause, the next word.
    await box.click();
    await box.pressSequentially(`${fn} `, { delay: 60 });
    await page.waitForTimeout(900);                       // the old bug ate the space here
    await box.pressSequentially(ln, { delay: 60 });
    await page.waitForTimeout(1500);
    const value = await box.inputValue();
    R.check("7: the space survives typing (box still reads 'First Last')", value === `${fn} ${ln}`, `"${value}"`);
    const count = await page.locator("tbody tr").count();
    await shot("tenants-search-first-space-last", { fullPage: false });
    R.check(`7: "${fn} ${ln}" finds the tenant(s)`, count === expected && count > 0, `${count} row(s), expected ${expected}`);

    await box.fill(`${ln} ${fn}`);
    await page.waitForTimeout(1500);
    await shot("tenants-search-reversed-order", { fullPage: false });
    R.check("7: words in any order", (await page.locator("tbody tr").count()) === expected);

    await page.goto(`${BASE}/landlord/payments`, { waitUntil: "domcontentloaded" });
    await page.getByRole("searchbox", { name: "Search payments" }).fill(`${fn} ${ln}`);
    await page.waitForTimeout(1500);
    await shot("payments-search-full-name", { fullPage: false });
    R.check("7: payments search with a space finds rows", (await page.locator("tbody tr").count()) > 0);

    const propName = sql(`SELECT name FROM properties WHERE landlord_id=${LID} AND name LIKE '% %' AND NOT is_deleted ORDER BY id LIMIT 1`);
    await page.goto(`${BASE}/landlord/properties`, { waitUntil: "domcontentloaded" });
    await page.getByRole("searchbox", { name: "Search properties" }).fill(propName);
    await page.waitForTimeout(1500);
    await shot("properties-search-multi-word", { fullPage: false });
    R.check(`7: property search "${propName}"`, (await page.locator("tbody tr").count()) >= 1);

    await page.goto(`${BASE}/landlord/units`, { waitUntil: "domcontentloaded" });
    await page.getByRole("searchbox", { name: /Search units/ }).fill(`${propName.split(" ")[0]} ${sql(`SELECT u.name FROM units u JOIN properties p ON p.id=u.property_id WHERE p.name='${propName.replace(/'/g, "''")}' AND p.landlord_id=${LID} ORDER BY u.id LIMIT 1`)}`);
    await page.waitForTimeout(1500);
    await shot("units-search-property-and-unit", { fullPage: false });
    R.check("7: units search 'Property Unit' finds the unit", (await page.locator("tbody tr").count()) >= 1);

    // A dropdown search (record payment → tenant) with a space.
    await page.goto(`${BASE}/landlord/payments`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Record payment" }).first().click();
    await combo(page, "Tenant").click();
    await page.locator('[role="searchbox"]').last().fill(`${ln} ${fn}`);
    await page.waitForTimeout(400);
    await shot("dropdown-search-with-space", { fullPage: false });
    R.check("7: dropdown search with a space", (await page.locator('[role="listbox"]').last().locator('[role="option"]').count()) >= 1);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");

    // Team portal (accountant) uses the same boxes.
    const tctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const tpage = await tctx.newPage();
    await staffLogin(tpage, "accountant001@scale.sahilpay.test", PASSWORD);
    await tpage.goto(`${BASE}/team/tenants`, { waitUntil: "domcontentloaded" });
    await dismissTours(tpage);
    const tbox = tpage.getByRole("searchbox", { name: "Search tenants" });
    await tbox.pressSequentially(`${fn} ${ln}`, { delay: 60 });
    await tpage.waitForTimeout(1600);
    await shooter(tpage, "07-search-with-spaces")("team-portal-tenants-search", { fullPage: false });
    R.check("7: team portal search with a space", (await tpage.locator("tbody tr").count()) === expected);
    await tctx.close();
  }

  // ============================================ 10 property page: units / tenants
  {
    const shot = shooter(page, "10-property-units-and-tenants");
    const [pid, pname] = sql(`SELECT id||'|'||name FROM properties WHERE landlord_id=${LID} AND NOT is_deleted ORDER BY name LIMIT 1`).split("|");
    await page.goto(`${BASE}/landlord/properties`, { waitUntil: "domcontentloaded" });
    await dismissTours(page);
    await page.locator("tbody tr", { hasText: pname }).first().click();
    await page.waitForURL(/\/properties\/\d+\/units/, { timeout: 15000 });
    await page.waitForTimeout(1500);
    await shot("property-units-tab", { fullPage: false });
    const banner = (await page.getByTestId("property-scope-banner").innerText()).replace(/\s+/g, " ");
    R.check("10: clicking a property opens its page — units sub-page", /viewing units for property/i.test(banner) && banner.includes(pname), banner);
    const units = await page.locator("tbody tr").count();
    const expectedUnits = Number(sql(`SELECT count(*) FROM units WHERE property_id=${pid} AND NOT is_deleted`));
    R.check("10: lists exactly this property's units", units === Math.min(expectedUnits, 20), `${units} vs ${expectedUnits}`);
    await page.getByTestId("property-tabs").getByRole("button", { name: /^Tenants/ }).click();
    await page.waitForURL(/\/tenants$/, { timeout: 15000 });
    await page.waitForTimeout(1500);
    await shot("property-tenants-tab", { fullPage: false });
    const banner2 = (await page.getByTestId("property-scope-banner").innerText()).replace(/\s+/g, " ");
    const expectedTenants = Number(sql(`SELECT count(*) FROM tenants t JOIN units u ON u.id=t.unit_id WHERE u.property_id=${pid} AND NOT t.is_deleted AND NOT u.is_deleted`));
    R.check("10: tenants sub-page for the same property", /viewing tenants for property/i.test(banner2)
      && (await page.locator("tbody tr").count()) === Math.min(expectedTenants, 20), `${expectedTenants} tenants`);
  }

  // ============================================== 1 + 12 add tenant: NOK + move-in
  let movedIn = null;
  {
    const shot = shooter(page, "01-12-add-tenant-next-of-kin-and-move-in");
    // Another walkthrough may have filled every unit — add one if none is free.
    if (sql(`SELECT count(*) FROM units u JOIN properties p ON p.id=u.property_id WHERE p.landlord_id=${LID}
      AND NOT u.is_occupied AND NOT u.is_deleted AND NOT p.is_deleted`) === "0") {
      const pid0 = Number(sql(`SELECT id FROM properties WHERE landlord_id=${LID} AND NOT is_deleted ORDER BY name LIMIT 1`));
      await api("/units/", { token, method: "POST", body: { property_id: pid0, name: `QA-${Date.now().toString(36)}`, rent_amount: 12000 } });
    }
    const [propName, unitName, unitId, rent] = sql(`SELECT p.name||'|'||u.name||'|'||u.id||'|'||u.rent_amount FROM units u
      JOIN properties p ON p.id=u.property_id WHERE p.landlord_id=${LID} AND NOT u.is_occupied AND NOT u.is_deleted
      AND NOT p.is_deleted ORDER BY p.name LIMIT 1`).split("|");
    await page.goto(`${BASE}/landlord/tenants`, { waitUntil: "domcontentloaded" });
    await dismissTours(page);
    await page.getByRole("button", { name: "Add tenant" }).click();
    await pick(page, "Property", propName);
    await pick(page, "Unit", unitName);
    await page.getByLabel("First name").fill("Grace");
    await page.getByLabel("Last name").fill("Wanjiru Kirui");
    await page.getByLabel(/^Phone/).first().fill("0712 998 877");
    await page.getByLabel("Email").fill(`grace.${Date.now()}@example.com`);
    await page.locator('input[name="next_of_kin_name"]').fill("Peter Kirui");
    await page.locator('input[name="next_of_kin_relationship"]').fill("Brother");
    await page.locator('input[name="next_of_kin_phone"]').fill("0722 334 455");
    await page.getByTestId("next-of-kin-section").scrollIntoViewIfNeeded();
    await shot("next-of-kin-section-filled", { fullPage: false });
    await page.getByLabel("Move-in date").fill("2026-09-28");
    // The move-in bill: tick "next month", include the first month's rent,
    // add the deposit and the lease fee — a normal invoice, all for October.
    await page.getByText("Bill the next month's move-in now").click();
    await page.getByText(/^Include the first month's rent/).click();
    await pick(page, "Add an item", "Rent Deposit");
    await page.getByLabel("Amount for Rent Deposit").fill(String(Number(rent)));
    await pick(page, "Add an item", "Lease Agreement This month");
    await page.getByLabel("Amount for Lease Agreement").fill("1000");
    await page.waitForTimeout(1500);
    await page.getByTestId("move-in-billing").scrollIntoViewIfNeeded();
    await shot("move-in-billing-preview-october", { fullPage: false });
    const prev = await page.getByTestId("move-in-preview").innerText();
    R.check("12: move-in on 28 Sep bills 'Rent — October 2026'", /Rent — October 2026/.test(prev), prev.replace(/\n/g, " · "));
    await page.getByRole("button", { name: "Save tenant" }).click();
    const t = await toastText(page);
    await shot("tenant-added-move-in-invoice", { fullPage: false });
    R.check("1+12: tenant saved with a move-in invoice", /Move-in invoice/.test(t), t);
    const row = sql(`SELECT id||'|'||coalesce(next_of_kin_name,'')||'|'||coalesce(next_of_kin_relationship,'')||'|'||coalesce(next_of_kin_phone,'')||'|'||coalesce(lease_start_date::text,'')
      FROM tenants WHERE landlord_id=${LID} AND first_name='Grace' AND last_name='Wanjiru Kirui' ORDER BY id DESC LIMIT 1`).split("|");
    R.check("1: next of kin saved to the tenant (name, relationship, phone)",
      row[1] === "Peter Kirui" && row[2] === "Brother" && row[3] === "254722334455", row.slice(1, 4).join(" / "));
    R.check("12: lease starts with the first rent month", row[4] === "2026-10-01", row[4]);
    movedIn = { id: row[0], unitId, propName, rent: Number(rent) };

    await page.goto(`${BASE}/landlord/tenants/${movedIn.id}/transactions`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot("tenant-page-shows-next-of-kin", { fullPage: false });
    R.check("1: next of kin shown on the tenant's page", /Peter Kirui/.test(await page.getByTestId("tenant-next-of-kin").innerText()));
  }

  // ========================================= 4 allocate once + 5 receipt gating
  {
    const shot = shooter(page, "04-05-allocate-once-and-receipt-gating");
    const code = `QA${Math.random().toString(36).slice(2, 10).toUpperCase()}`;
    const total = movedIn.rent * 2 + 1000;
    // The move-in money arrives twice: typed on the Payments page AND read from
    // the SMS by Co-pilot — two pending payments carrying the same M-Pesa code.
    const p1 = await api("/payments/", { token, method: "POST", body: {
      tenant_id: Number(movedIn.id), amount: total, payment_date: "2026-09-28", status: "pending",
      source: "mpesa", payment_method: "M-Pesa", mpesa_reference: code } });
    const p2 = await api("/payments/", { token, method: "POST", body: {
      tenant_id: Number(movedIn.id), amount: total, payment_date: "2026-09-28", status: "pending",
      source: "co_pilot", payment_method: "M-Pesa", mpesa_reference: code } });
    R.check("setup: two pending copies of one M-Pesa payment", p1.status === 201 && p2.status === 201);

    await page.goto(`${BASE}/landlord/payments?status=pending`, { waitUntil: "domcontentloaded" });
    await dismissTours(page);
    await page.getByRole("searchbox", { name: "Search payments" }).fill(code);
    await page.waitForTimeout(1800);
    // 5: a pending payment offers no receipt.
    const pendingRow = page.locator("tbody tr", { hasText: "Grace" }).first();
    await pendingRow.locator("td").last().locator("button").last().click();
    await page.locator('[role="menu"]').waitFor({ timeout: 10000 });
    await page.waitForTimeout(300);
    await shot("pending-payment-menu-has-no-receipt", { fullPage: false });
    const menu = await page.locator('[role="menuitem"]').allTextContents().catch(() => []);
    R.check("5: pending payment — no Send/Download receipt in the menu",
      menu.length > 0 && !/Send receipt|Download receipt/.test(menu.join(" ")), menu.join(" · "));
    await page.keyboard.press("Escape");
    const dl = await apiRaw(`/payments/${p1.json.id}/receipt/download`);
    R.check("5: API refuses a receipt for a pending payment (409)", dl.status === 409, `${dl.status} ${(await dl.json()).error}`);

    // 4: review & allocate the first copy.
    await pendingRow.getByRole("button", { name: "Review" }).click();
    await page.waitForTimeout(1500);
    await shot("review-modal", { fullPage: false });
    await page.getByRole("button", { name: /Confirm/ }).last().click();
    const ok = await toastText(page);
    await shot("allocated-success-message", { fullPage: false });
    R.check("4: success message after review & allocate", /reviewed and allocated to Grace/.test(ok), ok);

    // …the Co-pilot copy of the same money is refused.
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("searchbox", { name: "Search payments" }).fill(code);
    await page.waitForTimeout(1800);
    await page.locator("tbody tr", { hasText: "Grace" }).first().getByRole("button", { name: "Review" }).click();
    await page.waitForTimeout(1500);
    await page.getByRole("button", { name: /Confirm/ }).last().click();
    const refused = await toastText(page);
    await shot("second-copy-refused-already-allocated", { fullPage: false });
    R.check("4: the same M-Pesa code cannot be allocated a second time (Co-pilot copy)", /already allocated/.test(refused), refused);
    // Whichever copy the reviewer opened first is the one on the books.
    const winner = Number(sql(`SELECT id FROM payments WHERE mpesa_reference='${code}' AND status='confirmed'`));
    const again = await api(`/payments/${winner}/confirm`, { token, method: "POST", body: { mode: "auto" } });
    R.check("4: re-confirming the allocated payment is refused (409)", again.status === 409 && /already been reviewed and allocated/.test(again.json?.error), again.json?.error);
    const split = await api(`/payments/${winner}/allocate`, { token, method: "POST", body: { splits: [{ tenant_id: Number(movedIn.id), amount: 100 }] } });
    R.check("4: split/allocate endpoint refuses it too (409)", split.status === 409, split.json?.error);

    // Record the same code by hand on the Payments page.
    await page.goto(`${BASE}/landlord/payments`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Record payment" }).first().click();
    await pick(page, "Tenant", "Grace Wanjiru");
    await page.getByLabel("Amount").fill(String(total));
    await page.getByLabel("M-Pesa reference").fill(code);
    await page.getByRole("button", { name: /Save|Record/ }).last().click();
    const dup = await toastText(page);
    await shot("record-same-code-refused", { fullPage: false });
    R.check("4: recording the same M-Pesa code again is refused, with the reason", /already allocated/.test(dup), dup);
    await page.keyboard.press("Escape");
    const allocated = sql(`SELECT coalesce(sum(a.amount_allocated),0) FROM payment_allocations a JOIN payments p ON p.id=a.payment_id WHERE p.mpesa_reference='${code}'`);
    R.check("4: the money is on the books exactly once", Number(allocated) === total, `allocated ${allocated} of ${total}`);

    // 5: the allocated one now has its receipt actions.
    await page.goto(`${BASE}/landlord/payments`, { waitUntil: "domcontentloaded" });
    await page.getByRole("searchbox", { name: "Search payments" }).fill(code);
    await page.waitForTimeout(1500);
    await page.locator("tbody tr", { hasText: "confirmed" }).first().locator("td").last().locator("button").last().click();
    await page.locator('[role="menu"]').waitFor({ timeout: 10000 });
    await page.waitForTimeout(300);
    await shot("allocated-payment-menu-has-receipt", { fullPage: false });
    R.check("5: confirmed + allocated payment offers the receipt",
      (await page.getByText("Send receipt").count()) > 0 && (await page.getByText("Download receipt").count()) > 0);
    await page.keyboard.press("Escape");
    movedIn.paymentId = winner;
  }

  // ========================================================= 2 send receipt dialog
  {
    const shot = shooter(page, "02-send-receipt-channels");
    await page.goto(`${BASE}/landlord/tenants/${movedIn.id}/transactions`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot("tenant-ledger-payment-row", { fullPage: false });
    await page.locator("tbody tr", { hasText: "Payment" }).filter({ hasText: "confirmed" }).first()
      .locator("td").last().locator("button").click();
    await page.getByText("Send receipt").click();
    await page.getByTestId("send-receipt-modal").waitFor();
    await shot("channel-picker-nothing-sent-yet", { fullPage: false });
    const before = Number(sql(`SELECT count(*) FROM notifications WHERE entity_type='payment' AND entity_id=${movedIn.paymentId} AND category='payment_receipt'`));
    R.check("2: opening the dialog sends nothing", before === 0);
    R.check("2: Send is disabled until a channel is ticked", await page.getByTestId("send-receipt-confirm").isDisabled());
    await page.getByText("Email", { exact: true }).click();
    await page.getByText("SMS", { exact: true }).click();
    await page.getByText("In-app", { exact: true }).click();
    await shot("email-sms-inapp-ticked", { fullPage: false });
    await page.getByTestId("send-receipt-confirm").click();
    const sent = await toastText(page);
    await shot("receipt-sent", { fullPage: false });
    R.check("2: sent on the ticked channels", /Receipt sent via/.test(sent), sent);
  }

  // ============================== 12 + 13 the move-in receipt, dated October
  {
    const shot = shooter(page, "12-13-receipt-months");
    const res = await apiRaw(`/payments/${movedIn.paymentId}/receipt/download`);
    const img = await pdfToPng(await res.arrayBuffer(), "receipt-move-in", 150);
    const text = execSync(`pdftotext -layout "${img.pdf}" -`).toString();
    R.check("12: receipt dated 28/09/2026 says 'Rent — Oct 2026'", /28\/09\/2026/.test(text) && /Rent\s+—\s+Oct 2026/.test(text), text.split("\n").filter((l) => /Rent|Lease|Deposit/.test(l)).join(" | "));
    const raw = execSync(`pdftotext -raw "${img.pdf}" -`).toString();
    R.check("13: lease agreement has no month; deposit and rent do",
      /Lease Agreement KES/.test(raw) && !/Lease Agreement —/.test(raw) && /Rent Deposit — Oct 2026/.test(raw),
      raw.split("\n").filter((l) => /Lease|Deposit/.test(l)).join(" | "));
    execSync(`pdftoppm -png -r 170 -singlefile -y 0 -H 700 -W 1420 "${img.pdf}" "${TMP}/move-in-top"`);
    await showImages(page, "Item 12 — joined 28 September, paid October's rent: the receipt is dated 28/09/2026 and says Rent — Oct 2026",
      [{ label: "Top third of the printed A4 sheet", png: `${TMP}/move-in-top.png`, width: 1300 }]);
    await shot("move-in-receipt-october", { fullPage: true });

    // A tenant clearing old arrears: the receipt splits by month and says what is still owed.
    // A payment that cleared a multi-month "Balance b/f": the largest such
    // allocation is the one that reaches back across several months.
    const candidates = sql(`SELECT a.payment_id FROM payment_allocations a JOIN invoice_line_items li ON li.id=a.line_item_id
      JOIN payments p ON p.id=a.payment_id
      WHERE p.landlord_id=${LID} AND li.subcategory='balance' AND p.source<>'credit'
      AND (SELECT count(*) FROM balance_rollovers b WHERE b.target_line_item_id=li.id) >= 2
      ORDER BY a.amount_allocated DESC, p.payment_date DESC LIMIT 15`).split("\n");
    let pid, arrears, months = [];
    for (const cand of candidates) {
      const r2 = await apiRaw(`/payments/${cand}/receipt/download`);
      const got = await pdfToPng(await r2.arrayBuffer(), `receipt-arrears-${cand}`, 170);
      const raw2 = execSync(`pdftotext -raw "${got.pdf}" -`).toString();
      const ms = [...raw2.matchAll(/(Rent|Water|Security|Garbage) — (\w{3} \d{4})/g)].map((m) => `${m[1]} ${m[2]}`);
      if (new Set(ms.filter((m) => m.startsWith("Rent"))).size >= 2) { pid = cand; arrears = got; months = ms; break; }
      if (!arrears) { pid = cand; arrears = got; months = ms; }
    }
    R.check("13: an arrears payment is itemised month by month", new Set(months.map((m) => m.split(" ").slice(1).join(" "))).size >= 2, months.join(", "));
    execSync(`pdftoppm -png -r 170 -singlefile -y 0 -H 700 -W 1420 "${arrears.pdf}" "${TMP}/arrears-top"`);
    await showImages(page, `Item 13 — payment #${pid} cleared arrears: every line names its month, and what is still owed is listed`,
      [{ label: "Top third of the printed A4 sheet", png: `${TMP}/arrears-top.png`, width: 1300 }]);
    await shot("arrears-receipt-months", { fullPage: true });

    // The same receipt on the full A4 layout (four money columns).
    const cur = await (await apiRaw("/settings/receipt-layout")).json();
    await apiRaw("/settings/receipt-layout", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout: { ...cur.layout, paper: "a4" }, theme: cur.theme }) });
    const full = await pdfToPng(await (await apiRaw(`/payments/${pid}/receipt/download`)).arrayBuffer(), "receipt-full", 90);
    await apiRaw("/settings/receipt-layout", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout: { ...cur.layout, paper: "a4_third_band" }, theme: cur.theme }) });
    await showImages(page, "Item 13 — the same payment on the full-page layout: due / paid / balance c/f per month",
      [{ label: "A4 full page", png: full.png, width: 760 }]);
    await shot("arrears-receipt-full-a4", { fullPage: true });
  }

  // ================================================= 11 invoice by property
  {
    const shot = shooter(page, "11-invoice-by-property");
    await page.goto(`${BASE}/landlord/invoices`, { waitUntil: "domcontentloaded" });
    await dismissTours(page);
    await shot("invoices-page-invoice-by-property-button", { fullPage: false });
    await page.getByTestId("invoice-by-property").click();
    await page.waitForURL(/by-property/);
    await page.getByRole("textbox", { name: "Month" }).fill("2026-10");
    await page.waitForTimeout(2500);
    await shot("october-overview", { fullPage: false });
    // Grace's property first: October's rent is already billed on her move-in invoice.
    await page.getByTestId("by-property-list").getByText(movedIn.propName, { exact: true }).click();
    await page.waitForTimeout(2500);
    await shot("property-preview-with-move-in-tenant", { fullPage: false });
    const prevText = await page.getByTestId("by-property-preview").innerText();
    R.check("12: October run will not bill Grace's October rent again", /already billed \(move-in bill/.test(prevText));
    // Already done for October (an earlier run)? Generating is correctly
    // disabled — move on to the next property that still needs it.
    if (await page.getByTestId("by-property-generate").isDisabled()) {
      await page.getByTestId("by-property-next").click();
      await page.waitForTimeout(2500);
    }
    const firstName = (await page.getByTestId("by-property-preview").locator("h3").innerText()).trim();
    const genStart = sql("SELECT (now() AT TIME ZONE 'utc')");   // created_at is stored in UTC
    await page.getByTestId("by-property-generate").click();
    await page.waitForTimeout(500);
    await shot("confirm-generate", { fullPage: false });
    await page.getByRole("button", { name: "Confirm & generate" }).click();
    const t = await toastText(page);
    await page.waitForTimeout(2000);
    await shot("generated-property-marked-invoiced", { fullPage: false });
    R.check("11: invoices generated for ONE property", /invoice\(s\) created/.test(t), t);
    const graceOct = sql(`SELECT count(*) FROM invoice_line_items li JOIN invoices i ON i.id=li.invoice_id
      WHERE i.tenant_id=${movedIn.id} AND li.item='Rent' AND li.period_month='2026-10-01'`);
    R.check("12: Grace has exactly ONE October rent line", graceOct === "1", graceOct);
    // Only invoices this step created: every one of them in ONE property.
    const otherProps = sql(`SELECT count(DISTINCT property_id) FROM invoices WHERE landlord_id=${LID} AND invoice_type='monthly' AND created_at >= '${genStart}'`);
    R.check("11: only that property was invoiced for October", otherProps === "1", `${otherProps} property(ies) invoiced in this step`);
    await page.getByTestId("by-property-next").click();
    await page.waitForTimeout(2000);
    await shot("next-property-ready", { fullPage: false });
    R.check("11: 'Next' moves to the next property to do", !(await page.getByTestId("by-property-preview").innerText()).includes(firstName));
  }

  // ======================================================= 6 reports
  {
    const shot = shooter(page, "06-reports-accuracy");
    await page.goto(`${BASE}/landlord/reports/statements`, { waitUntil: "domcontentloaded" });
    await dismissTours(page);
    await page.getByRole("button", { name: /^Payments/ }).or(page.getByRole("tab", { name: /Payments/ })).first().click();
    await page.getByLabel("Paid from").fill("2026-05-01");
    await page.getByLabel("Paid to").fill("2026-09-30");
    await page.getByTestId("report-reconciliation").waitFor({ timeout: 60000 });
    await page.waitForTimeout(3000);
    await shot("summary-and-reconciliation", { fullPage: true });
    const recon = await page.getByTestId("report-reconciliation").innerText();
    R.check("6: cash received = allocated + advance (nothing unexplained)", /nothing unexplained/.test(recon), recon.replace(/\n/g, " · "));
    await page.getByRole("button", { name: "By month" }).or(page.getByRole("tab", { name: "By month" })).first().click();
    await page.waitForTimeout(800);
    await shot("by-month-the-charge-is-for", { fullPage: true });
    await page.getByRole("button", { name: "Per tenant" }).or(page.getByRole("tab", { name: "Per tenant" })).first().click();
    await page.waitForTimeout(800);
    await shot("per-tenant-by-category", { fullPage: false });
    await page.getByRole("button", { name: /Allocation ledger/ }).or(page.getByRole("tab", { name: /Allocation ledger/ })).first().click();
    await page.waitForTimeout(800);
    await shot("allocation-ledger", { fullPage: false });

    // Instant: record a payment, come straight back — the numbers moved.
    const api1 = await api(`/reports/payments?date_from=2026-05-01&date_to=2026-09-30&ledger_page=1`, { token });
    const tid = sql(`SELECT id FROM tenants WHERE landlord_id=${LID} AND balance<0 AND NOT is_deleted ORDER BY balance LIMIT 1`);
    const pay = await api("/payments/", { token, method: "POST", body: { tenant_id: Number(tid), amount: 3210, payment_date: "2026-09-29", payment_method: "M-Pesa", mpesa_reference: `QI${Date.now().toString(36).toUpperCase().slice(-8)}` } });
    // The payment came from outside this browser (like Co-pilot or a
    // colleague): the open report picks it up on its own within 30 s.
    await page.getByRole("button", { name: "Summary" }).or(page.getByRole("tab", { name: "Summary" })).first().click();
    await page.waitForTimeout(34000);
    await shot("after-new-payment-cash-received-updated", { fullPage: false });
    const api2 = await api(`/reports/payments?date_from=2026-05-01&date_to=2026-09-30&ledger_page=1`, { token });
    const diff = Math.round((api2.json.reconciliation.cash_received - api1.json.reconciliation.cash_received) * 100) / 100;
    R.check("6: a payment shows in the report immediately", pay.status === 201 && diff === 3210, `cash received +${diff}`);
    const uiRecon = await page.getByTestId("report-reconciliation").innerText();
    const shown = Number((uiRecon.match(/KES\s*([\d,]+\.\d\d)/) || [])[1]?.replace(/,/g, ""));
    R.check("6: the open report shows it by itself within 30 s (no reload)", shown === api2.json.reconciliation.cash_received, `${shown}`);

    // Independent check straight from the database.
    const dbCash = Number(sql(`SELECT coalesce(sum(amount),0) FROM payments WHERE landlord_id=${LID} AND NOT is_deleted AND status='confirmed' AND source<>'credit' AND payment_date BETWEEN '2026-05-01' AND '2026-09-30'`));
    R.check("6: report cash received matches the database", Math.abs(dbCash - api2.json.reconciliation.cash_received) < 0.01, `${dbCash}`);
    const dbOwed = Number(sql(`SELECT coalesce(sum(li.amount-li.amount_paid),0) FROM invoice_line_items li JOIN invoices i ON i.id=li.invoice_id
      WHERE i.landlord_id=${LID} AND NOT i.is_deleted AND i.status<>'void' AND li.status='open' AND li.subcategory IN ('current','balance')`));
    R.check("6: report 'still owed' matches the database", Math.abs(dbOwed - api2.json.grand_total.outstanding) < 1, `${dbOwed} vs ${api2.json.grand_total.outstanding}`);

    // Excel
    const [dlx] = await Promise.all([
      page.waitForEvent("download", { timeout: 120000 }),
      page.getByRole("button", { name: "Download Excel" }).click(),
    ]);
    const xlsx = `${TMP}/payments-report.xlsx`;
    await dlx.saveAs(xlsx);
    const sheets = execSync(`cd ${process.cwd()}/../server && venv/bin/python -c "
import openpyxl,json;wb=openpyxl.load_workbook('${xlsx}');print(json.dumps({ws.title:[[c for c in r] for r in ws.iter_rows(min_row=4,max_row=12,values_only=True)] for ws in wb}, default=str))"`).toString();
    const book = JSON.parse(sheets);
    R.check("6: Excel has Summary / By month / Per tenant / Allocation ledger / Reconciliation sheets",
      ["Summary by category", "By month", "Per tenant", "Allocation ledger", "Reconciliation"].every((s) => s in book), Object.keys(book).join(", "));
    const html = Object.entries(book).map(([name, rows]) => `<h3>${name}</h3><table border=1 cellpadding=4 style="border-collapse:collapse;font:12px system-ui;background:#fff">${rows.map((r) => `<tr>${r.map((c) => `<td>${c ?? ""}</td>`).join("")}</tr>`).join("")}</table>`).join("");
    await page.setContent(`<body style="margin:16px;font-family:system-ui;background:#eee"><h2>payments-report.xlsx — first rows of every sheet (opened with openpyxl)</h2>${html}</body>`);
    await shot("excel-export-sheets", { fullPage: true });
  }

  // ================================================= 9 third-party SMS sender
  {
    const shot = shooter(page, "09-third-party-sender-id");
    const key = execSync(`grep '^FLUXSMS_API_KEY=' ${process.cwd()}/../server/.env | cut -d= -f2-`).toString().trim();
    await page.goto(`${BASE}/landlord/settings/sms-provider`, { waitUntil: "domcontentloaded" });
    await dismissTours(page);
    await page.getByTestId("sms-mode-own_account").click();
    await page.locator('input[name="sms_sender_id"]').fill("SAHILPAY");
    await page.locator('input[name="sms_api_key"]').fill("not-a-real-key-000");
    await page.getByTestId("sms-connect").click();
    await page.getByTestId("sms-connect-result").waitFor({ timeout: 30000 });
    await shot("wrong-key-rejected-by-fluxsms", { fullPage: false });
    R.check("9: a wrong key is rejected by FluxSMS, not connected", /rejected/i.test(await page.getByTestId("sms-connect-result").innerText()));
    await page.locator('input[name="sms_api_key"]').fill(key);
    await page.getByTestId("sms-connect").click();
    await page.waitForTimeout(4000);
    await shot("sahil-pay-key-connected-as-third-party", { fullPage: false });
    const ok = await page.getByTestId("sms-connect-result").innerText();
    R.check("9: Sahil Pay's own key connects as a third-party account (live balance check)", /Key accepted by FluxSMS/.test(ok), ok);
    const conf = await (await apiRaw("/settings/sms-provider")).json();
    R.check("9: mode = own FluxSMS account, key stored encrypted and masked",
      conf.provider?.mode === "own_account" && conf.sms_api_key_masked?.startsWith("••••") && !JSON.stringify(conf).includes(key),
      `${conf.provider?.mode} ${conf.sms_api_key_masked}`);
    const stored = sql(`SELECT left(sms_api_key,4) FROM landlord_settings WHERE landlord_id=${LID}`);
    R.check("9: key encrypted at rest", stored === "enc:", stored);
    // Leave the account as it was: shared sender.
    await page.getByRole("button", { name: "Disconnect" }).click();
    await page.waitForTimeout(1500);
    await api("/settings/sms-provider", { token, method: "PUT", body: { sms_api_key: "", sms_sender_id: "" } });
  }
} catch (err) {
  console.error("WALKTHROUGH ERROR:", err);
  R.check("walkthrough ran to completion", false, err.message);
  await page.screenshot({ path: `${SHOTS}/zz-error.png`, fullPage: false }).catch(() => {});
} finally {
  await browser.close();
}

const failed = R.summary();
writeFileSync(`${SHOTS}/results.json`, JSON.stringify(R.list, null, 2));
process.exit(failed ? 1 : 0);
