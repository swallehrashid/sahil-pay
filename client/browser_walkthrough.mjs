// Browser walkthrough: logs into landlord & admin portals, captures console
// errors, verifies the Impersonation -> Client Support rename is visible in the
// rendered UI, and screenshots key pages. Run: node browser_walkthrough.mjs
import { chromium } from 'playwright';

const BASE = 'http://localhost:5173';
const SHOT = '/tmp/claude-1000/-home-swalleh-projects-sahil-pay/c1709bcf-7acf-4a0b-b679-a08319eb0924/scratchpad';
const results = [];
const consoleErrors = [];

function ok(cond, label, detail = '') {
  results.push({ cond, label, detail });
  console.log(`   ${cond ? '✓' : '✗ FAIL'} ${label}${cond ? '' : '  ' + detail}`);
}

async function login(page, email, password) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.fill('input[type="email"], input[name="email"]', email);
  await page.fill('input[type="password"], input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(2500);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();

page.on('console', (msg) => {
  if (msg.type() === 'error') {
    const t = msg.text();
    // Ignore benign favicon / network 404 noise
    if (!/favicon|net::ERR|Failed to load resource/i.test(t)) consoleErrors.push(t);
  }
});
page.on('pageerror', (err) => consoleErrors.push('PAGEERROR: ' + err.message));

try {
  console.log('=== Landlord portal ===');
  await login(page, 'landlord@sahilpay.test', 'Landlord@123');
  const url = page.url();
  ok(!url.endsWith('/login'), 'landlord logged in (left /login)', url);
  await page.screenshot({ path: `${SHOT}/01-landlord-dashboard.png` });

  // Settings -> Client Support tab should exist; "Impersonation" should NOT.
  await page.goto(`${BASE}/landlord/settings/impersonation-requests`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const settingsText = await page.textContent('body');
  ok(/Client Support/i.test(settingsText), 'landlord Settings shows "Client Support"');
  ok(!/Impersonation/i.test(settingsText), 'landlord Settings has NO "Impersonation"',
     'found the word Impersonation');
  await page.screenshot({ path: `${SHOT}/02-landlord-settings.png` });

  console.log('\n=== Admin portal ===');
  // log out via clearing storage + navigating
  await context.clearCookies();
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await login(page, 'admin@sahilpay.test', 'Admin@123');
  const adminUrl = page.url();
  ok(!adminUrl.endsWith('/login'), 'admin logged in', adminUrl);
  await page.screenshot({ path: `${SHOT}/03-admin-dashboard.png` });

  // Admin sidebar should have "Client Support", not "Impersonation"
  const adminBody = await page.textContent('body');
  ok(/Client Support/i.test(adminBody), 'admin sidebar shows "Client Support"');
  ok(!/Impersonation/i.test(adminBody), 'admin UI has NO "Impersonation"',
     'found Impersonation');

  // Navigate to the client-support page (route path unchanged)
  await page.goto(`${BASE}/admin/impersonation`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const csBody = await page.textContent('body');
  ok(/Client Support/i.test(csBody), 'client-support page title renders "Client Support"');
  ok(!/Impersonation/i.test(csBody), 'client-support page has NO "Impersonation"', 'found Impersonation');
  await page.screenshot({ path: `${SHOT}/04-admin-client-support.png` });

  console.log('\n=== Console errors ===');
  ok(consoleErrors.length === 0, `no console errors across walkthrough`,
     consoleErrors.slice(0, 5).join(' | '));

} catch (e) {
  ok(false, 'walkthrough threw', e.message);
} finally {
  await browser.close();
}

const fails = results.filter((r) => !r.cond);
console.log(`\n=== BROWSER WALKTHROUGH: ${results.length} checks, ${fails.length} failures ===`);
if (consoleErrors.length) {
  console.log('Console errors captured:');
  consoleErrors.forEach((e) => console.log('   - ' + e));
}
process.exit(fails.length ? 1 : 0);
