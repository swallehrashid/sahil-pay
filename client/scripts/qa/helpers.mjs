// Shared helpers for the QA walkthroughs in this folder.
import { execSync } from "node:child_process";
import { mkdirSync } from "node:fs";

export const BASE = process.env.QA_BASE || "http://127.0.0.1:5173";
export const API = process.env.QA_API || "http://127.0.0.1:5000/api";
export const SHOTS = process.env.QA_SHOTS || "/tmp/sahilpay-qa-shots";
export const API_LOG = process.env.QA_API_LOG || "/tmp/sahilpay-api.log";

export function results() {
  const list = [];
  return {
    list,
    check(name, pass, detail = "") {
      list.push({ name, pass, detail });
      console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
    },
    summary() {
      const failed = list.filter((r) => !r.pass);
      console.log(`\n${list.length - failed.length}/${list.length} checks passed`);
      return failed.length;
    },
  };
}

export function shooter(page, folder) {
  const dir = `${SHOTS}/${folder}`;
  mkdirSync(dir, { recursive: true });
  let n = 0;
  return async (name, opts = {}) => {
    n += 1;
    const file = `${dir}/${String(n).padStart(2, "0")}-${name}.png`;
    await page.screenshot({ path: file, fullPage: opts.fullPage ?? true, timeout: 120000 });
    return file;
  };
}

export async function dismissTours(page) {
  for (const re of [/skip for now/i, /explore on my own/i, /maybe later/i, /not now/i, /skip tour/i, /^close$/i]) {
    try {
      const b = page.getByRole("button", { name: re }).first();
      if (await b.isVisible({ timeout: 400 })) await b.click();
    } catch { /* none */ }
  }
}

export async function staffLogin(page, email, password) {
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForSelector('input[type="email"]', { timeout: 60000 });
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
  await dismissTours(page);
}

export function lastOtp(phone) {
  const out = execSync(`grep "login code is" ${API_LOG} | grep -F "${phone}" | tail -1 || true`).toString();
  const m = out.match(/login code is (\d{6})/);
  return m && m[1];
}

export async function tenantLogin(page, phone) {
  await page.goto(`${BASE}/tenant/login`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForSelector("input", { timeout: 60000 });
  await page.locator("input").first().fill(phone);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(2500);
  const code = lastOtp(phone.replace(/^0/, "+254"));
  if (!code) throw new Error(`No OTP found in ${API_LOG} for ${phone}`);
  const digits = page.locator('input[inputmode="numeric"]');
  for (let i = 0; i < 6; i++) await digits.nth(i).fill(code[i]);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/portal\//, { timeout: 15000 });
  await page.waitForTimeout(1500);
}

export async function api(path, { token, method = "GET", body } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let json = null;
  try { json = await res.json(); } catch { /* binary */ }
  return { status: res.status, json };
}

export async function apiLogin(email, password) {
  const r = await api("/auth/login", { method: "POST", body: { email, password } });
  return r.json?.access_token || r.json?.data?.access_token;
}

export function noSideScroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth <= 1);
}
