/**
 * Item 6 — a team member starts a tutorial and the tour highlights the right
 * thing. Uses the office / caretaker members created by team-e2e.mjs.
 *
 *   QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/team-tutorials.mjs
 */
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { BASE, results, shooter, staffLogin } from "./helpers.mjs";

const DB = process.env.QA_DATABASE_URL || "postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay";
const sql = (q) => execFileSync("psql", [DB, "-tAc", q]).toString().trim();
const R = results();
const latest = (prefix) => sql(`SELECT email FROM users WHERE email LIKE '${prefix}.%@qa.sahilpay.test' ORDER BY id DESC LIMIT 1`);

async function runTour(browser, email, cardTitle, stepTitle, anchor, folder) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  const shot = shooter(page, folder);
  await staffLogin(page, email, "QaTeam123!");
  await page.goto(`${BASE}/team/tutorials`, { waitUntil: "domcontentloaded" });
  await page.getByText(cardTitle).waitFor({ timeout: 15000 });
  await page.locator(".glass", { hasText: cardTitle }).getByRole("button", { name: /Start|Run again/ }).click();
  await page.getByText(stepTitle).waitFor({ timeout: 15000 });
  await page.waitForTimeout(1500);   // let the sidebar finish expanding
  await shot(`${folder}-tour-step-1`, { fullPage: false });
  const overlap = await page.evaluate((id) => {
    const target = [...document.querySelectorAll(`[data-tour="${id}"]`)].find((el) => el.getBoundingClientRect().width > 0);
    if (!target) return { ok: false, why: "no target" };
    const t = target.getBoundingClientRect();
    // The spotlight ring drawn around the target (TourOverlay).
    const ring = document.querySelector("div.pointer-events-none.fixed.ring-2.ring-secondary");
    if (!ring) return { ok: false, why: "no spotlight" };
    const r = ring.getBoundingClientRect();
    const cy = t.top + t.height / 2;
    return { ok: cy >= r.top && cy <= r.bottom, target: Math.round(cy), ring: [Math.round(r.top), Math.round(r.bottom)] };
  }, anchor);
  R.check(`${folder}: "${stepTitle}" spotlight is on the right menu item`, overlap.ok, JSON.stringify(overlap));
  await ctx.close();
}

const browser = await chromium.launch();
try {
  await runTour(browser, latest("office"), "Add units to a property", "Open Units", "sidebar-units", "tutorial-office");
  await runTour(browser, latest("care"), "Record meter readings", "Open Utilities", "sidebar-utilities", "tutorial-caretaker");
} catch (err) {
  R.check("walkthrough ran to completion", false, err.message.split("\n")[0]);
} finally {
  await browser.close();
}
process.exit(R.summary() ? 1 : 0);
