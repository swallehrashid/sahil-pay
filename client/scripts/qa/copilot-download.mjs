/**
 * The Co-pilot download page on a phone with a throttled connection: progress
 * is visible, the file arrives intact (size + SHA-256 match the manifest), and
 * the success state and install steps appear.
 *
 *   node scripts/qa/copilot-download.mjs
 */
import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { BASE, SHOTS, results, shooter, noSideScroll } from "./helpers.mjs";

const R = results();
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, acceptDownloads: true,
    userAgent: "Mozilla/5.0 (Linux; Android 13; SM-A135F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Mobile Safari/537.36",
  });
  const page = await ctx.newPage();
  const shot = shooter(page, "copilot");
  const cdp = await ctx.newCDPSession(page);

  await page.goto(`${BASE}/copilot`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("copilot-download").waitFor({ timeout: 30000 });
  await page.waitForTimeout(1000);
  await shot("01-phone-download-page");
  R.check("download page: no sideways scroll on a phone", await noSideScroll(page));
  const manifest = await (await fetch(`${BASE}/downloads/copilot.json`)).json();

  // ~8 Mbit/s so the 19 MB file takes long enough to see the progress.
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 40, downloadThroughput: 1_000_000, uploadThroughput: 250_000 });
  const downloadPromise = page.waitForEvent("download", { timeout: 180000 });
  await page.getByTestId("copilot-download").click();
  await page.getByTestId("copilot-progress").waitFor();
  await page.waitForTimeout(6000);
  await shot("02-phone-downloading-progress", { fullPage: false });
  const pct = await page.getByRole("progressbar").getAttribute("aria-valuenow");
  R.check("progress is shown while downloading", Number(pct) > 0 && Number(pct) < 100, `${pct}%`);

  const download = await downloadPromise;
  const path = `${SHOTS}/copilot/${download.suggestedFilename()}`;
  await download.saveAs(path);
  await page.getByTestId("copilot-done").waitFor({ timeout: 30000 });
  await shot("03-phone-downloaded-success");
  const bytes = readFileSync(path);
  const sha = createHash("sha256").update(bytes).digest("hex");
  R.check("downloaded APK is intact (size and SHA-256 match)", bytes.length === manifest.size_bytes && sha === manifest.sha256,
          `${download.suggestedFilename()} ${bytes.length} bytes`);
  R.check("APK is a real Android package (zip)", bytes[0] === 0x50 && bytes[1] === 0x4b);

  const desk = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
  await desk.goto(`${BASE}/copilot`, { waitUntil: "domcontentloaded" });
  await desk.getByTestId("copilot-download").waitFor({ timeout: 30000 });
  await desk.waitForTimeout(2000);
  await desk.screenshot({ path: `${SHOTS}/copilot/04-desktop-download-page.png`, timeout: 90000 });
} catch (err) {
  console.error(err);
  R.check("script completed without errors", false, err.message.split("\n")[0]);
} finally {
  await browser.close();
  process.exit(R.summary() ? 1 : 0);
}
