/**
 * responsive-audit.mjs — find pages that scroll sideways on a phone.
 *
 * Two faults, both invisible on a desktop monitor and both fatal on the
 * handsets this product is actually used on:
 *
 *   1. PAGE-LEVEL HORIZONTAL SCROLL. Something inside the page is wider than
 *      the viewport, so the whole layout slides left and right. The usual
 *      causes are a fixed min-width, a long unbroken string, a negative
 *      margin, or a `w-screen` inside a padded container.
 *
 *   2. A TABLE THAT IS NOT IN ITS OWN SCROLLER. A table with real columns
 *      cannot fit a 390px screen, and it must NOT be squashed — the answer is
 *      to let the table scroll horizontally INSIDE a container while the page
 *      itself stays put.
 *
 * For any page that overflows, the script names the specific elements sticking
 * out, so the fix targets the real cause instead of a guessed one.
 *
 *   node scripts/responsive-audit.mjs [--base URL] [--profile dev] [--out DIR]
 */

import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const args = process.argv.slice(2);
const argOf = (flag, fallback) => {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : fallback;
};

const BASE = argOf("--base", "http://127.0.0.1:5173");
const OUT = argOf("--out", "./responsive-audit");
const TENANT_TOKEN = process.env.TENANT_TOKEN;

// The narrowest handset still in common use in Kenya. If it works here it
// works on everything wider.
const PHONE = { width: 360, height: 780 };
const TABLET = { width: 768, height: 1024 };

const PUBLIC_PAGES = [
  ["home", "/"], ["features", "/features"], ["pricing", "/pricing"],
  ["faq", "/faq"], ["about", "/about"], ["contact", "/contact"],
  ["privacy", "/privacy"], ["terms", "/terms"],
  ["become-affiliate", "/become-affiliate"],
  ["login", "/login"], ["register", "/register"],
];

const LANDLORD = { email: "landlord@sahilpay.test", password: "Landlord@123" };
const TEAM = { email: "caretaker@sahilpay.test", password: "Caretaker@123" };

const LANDLORD_PAGES = [
  ["dashboard", "/landlord/dashboard"],
  ["properties", "/landlord/properties"],
  ["units", "/landlord/units"],
  ["tenants", "/landlord/tenants"],
  ["tenants-deleted", "/landlord/tenants/deleted"],
  ["invoices", "/landlord/invoices"],
  ["payments", "/landlord/payments"],
  ["review-queue", "/landlord/payments/review-queue"],
  ["payout-runs", "/landlord/payouts"],
  ["owner-payouts", "/landlord/owner-payouts"],
  ["expenses", "/landlord/expenses"],
  ["utilities", "/landlord/utilities"],
  ["maintenance", "/landlord/maintenance"],
  ["groups", "/landlord/groups"],
  ["leases", "/landlord/leases"],
  ["reports-statements", "/landlord/reports/statements"],
  ["reports-insights", "/landlord/reports/insights"],
  ["reports-penalties", "/landlord/reports/penalties"],
  ["etims-register", "/landlord/etims-register"],
  ["kra-monthly", "/landlord/reports/kra-monthly"],
  ["communications", "/landlord/communications"],
  ["messages", "/landlord/messages"],
  ["notifications", "/landlord/notifications"],
  ["tutorials", "/landlord/tutorials"],
  ["help", "/landlord/help"],
  ["settings-general", "/landlord/settings/general"],
  ["settings-account", "/landlord/settings/account"],
  ["settings-alerts", "/landlord/settings/alerts"],
  ["settings-documents", "/landlord/settings/documents"],
  ["settings-receipt-layout", "/landlord/settings/receipt-layout"],
  ["settings-team", "/landlord/settings/team"],
  ["settings-billing", "/landlord/settings/billing"],
  ["settings-sms", "/landlord/settings/sms-provider"],
  ["settings-mpesa", "/landlord/settings/mpesa"],
  ["settings-copilot", "/landlord/settings/copilot"],
  ["settings-tax-compliance", "/landlord/settings/tax-compliance"],
  ["settings-allocation", "/landlord/settings/allocation"],
  ["settings-penalties", "/landlord/settings/penalties"],
  ["settings-audit", "/landlord/settings/audit"],
];

const TEAM_PAGES = [
  ["dashboard", "/team/dashboard"],
  ["tenants", "/team/tenants"],
  ["units", "/team/units"],
  ["utilities", "/team/utilities"],
  ["help", "/team/help"],
  ["tutorials", "/team/tutorials"],
  ["leases", "/team/leases"],
];

const TENANT_PAGES = [
  ["dashboard", "/portal/dashboard"],
  ["pay", "/portal/pay"],
  ["statement", "/portal/statement"],
  ["maintenance", "/portal/maintenance"],
  ["messages", "/portal/messages"],
  ["profile", "/portal/profile"],
  ["help", "/portal/help"],
  ["lease", "/portal/lease"],
];

const findings = [];

/**
 * Measure a page for sideways scroll and name whatever is sticking out.
 * Runs in the browser: only the DOM knows the real laid-out geometry.
 */
async function measure(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const viewport = doc.clientWidth;
    const overflowBy = doc.scrollWidth - viewport;

    // Elements whose right edge lies beyond the viewport. Walk everything and
    // keep the outermost offenders — a child sticking out usually drags its
    // parents with it, and reporting all of them buries the actual cause.
    const culprits = [];
    if (overflowBy > 1) {
      for (const el of document.querySelectorAll("body *")) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.right <= viewport + 1) continue;

        const style = getComputedStyle(el);
        if (style.position === "fixed") continue;   // off-canvas drawers are fine
        if (style.visibility === "hidden" || style.display === "none") continue;

        // Inside something that scrolls horizontally on purpose? Then it is
        // contained, and not a page-level fault.
        let contained = false;
        for (let p = el.parentElement; p; p = p.parentElement) {
          const ps = getComputedStyle(p);
          if (ps.overflowX === "auto" || ps.overflowX === "scroll") { contained = true; break; }
        }
        if (contained) continue;

        culprits.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className && String(el.className).slice(0, 120)) || "",
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          text: (el.textContent || "").trim().slice(0, 60),
        });
      }
    }

    // Tables that are not inside a horizontal scroller. Squashing a table is
    // not an acceptable answer — it must scroll instead.
    const unscrollableTables = [];
    for (const table of document.querySelectorAll("table")) {
      let scroller = null;
      for (let p = table.parentElement; p; p = p.parentElement) {
        const ps = getComputedStyle(p);
        if (ps.overflowX === "auto" || ps.overflowX === "scroll") { scroller = p; break; }
      }
      if (!scroller) {
        unscrollableTables.push({
          cols: table.querySelector("tr")?.children.length ?? 0,
          width: Math.round(table.getBoundingClientRect().width),
          text: (table.textContent || "").trim().slice(0, 50),
        });
      }
    }

    return {
      viewportWidth: viewport,
      scrollWidth: doc.scrollWidth,
      overflowBy: Math.max(0, overflowBy),
      culprits: culprits.slice(0, 6),
      unscrollableTables,
      tableCount: document.querySelectorAll("table").length,
    };
  });
}

async function dismissTour(page) {
  try {
    const skip = page.getByRole("button", { name: /skip for now|explore on my own/i });
    if (await skip.isVisible({ timeout: 1000 })) await skip.click();
  } catch { /* not showing */ }
  await page.waitForTimeout(250);
}

async function audit(page, role, name, url, viewportName) {
  try {
    await page.goto(`${BASE}${url}`, { waitUntil: "networkidle", timeout: 30000 });
  } catch { /* record whatever rendered */ }
  await dismissTour(page);
  await page.waitForTimeout(700);

  const result = await measure(page);
  const bad = result.overflowBy > 1 || result.unscrollableTables.length > 0;

  findings.push({ role, name, url, ...result, viewport: viewportName, ok: !bad });

  if (bad) {
    const bits = [];
    if (result.overflowBy > 1) bits.push(`overflows by ${result.overflowBy}px`);
    if (result.unscrollableTables.length) {
      bits.push(`${result.unscrollableTables.length} table(s) with no horizontal scroll`);
    }
    console.log(`[ FAIL ] ${viewportName} ${role}/${name} — ${bits.join("; ")}`);
    for (const c of result.culprits) {
      console.log(`           ↳ <${c.tag} class="${c.cls}"> right=${c.right} w=${c.width} "${c.text}"`);
    }
    for (const t of result.unscrollableTables) {
      console.log(`           ↳ <table> ${t.cols} cols, ${t.width}px — "${t.text}"`);
    }
    const dir = path.join(OUT, viewportName, role);
    await mkdir(dir, { recursive: true });
    await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: true });
  } else {
    console.log(`[  ok  ] ${viewportName} ${role}/${name}`);
  }
}

async function login(page, { email, password }) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(2500);
  return !page.url().includes("/login");
}

async function run() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();

  for (const [viewportName, viewport] of Object.entries({ phone: PHONE, tablet: TABLET })) {
    // ---- Public ----
    let ctx = await browser.newContext({ viewport });
    let page = await ctx.newPage();
    for (const [name, url] of PUBLIC_PAGES) {
      await audit(page, "public", name, url, viewportName);
    }
    await ctx.close();

    // ---- Landlord ----
    ctx = await browser.newContext({ viewport });
    page = await ctx.newPage();
    if (await login(page, LANDLORD)) {
      await dismissTour(page);
      for (const [name, url] of LANDLORD_PAGES) {
        await audit(page, "landlord", name, url, viewportName);
      }
    } else {
      console.log("could not sign in as the landlord — skipping that portal");
    }
    await ctx.close();

    // ---- Team member ----
    ctx = await browser.newContext({ viewport });
    page = await ctx.newPage();
    if (await login(page, TEAM)) {
      for (const [name, url] of TEAM_PAGES) {
        await audit(page, "team", name, url, viewportName);
      }
    }
    await ctx.close();

    // ---- Tenant ----
    if (TENANT_TOKEN) {
      ctx = await browser.newContext({ viewport });
      page = await ctx.newPage();
      await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
      await page.evaluate((t) => localStorage.setItem("sahilpay_access_token", t), TENANT_TOKEN);
      for (const [name, url] of TENANT_PAGES) {
        await audit(page, "tenant", name, url, viewportName);
      }
      await ctx.close();
    }
  }

  await browser.close();
  await writeFile(path.join(OUT, "results.json"), JSON.stringify(findings, null, 2));

  const failed = findings.filter((f) => !f.ok);
  const overflowing = failed.filter((f) => f.overflowBy > 1);
  const tableIssues = failed.filter((f) => f.unscrollableTables.length);

  console.log(`\n${"=".repeat(72)}`);
  console.log(`Checked: ${findings.length}   Clean: ${findings.length - failed.length}   Problems: ${failed.length}`);
  console.log(`  pages scrolling sideways : ${overflowing.length}`);
  console.log(`  tables without a scroller: ${tableIssues.length}`);
  if (failed.length) {
    console.log("\nWORST OFFENDERS:");
    for (const f of [...overflowing].sort((a, b) => b.overflowBy - a.overflowBy).slice(0, 12)) {
      console.log(`  ${f.viewport} ${f.role}/${f.name}: +${f.overflowBy}px`);
    }
  }
  console.log(`\nScreenshots of failures in ${path.resolve(OUT)}`);
  process.exit(failed.length ? 1 : 0);
}

run().catch((err) => {
  console.error("responsive-audit crashed:", err);
  process.exit(2);
});
