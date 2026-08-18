/**
 * prerender.mjs — turn the public marketing pages into real HTML files.
 *
 * WHY THIS EXISTS
 *
 * The app is a single-page build: one index.html, an empty <div id="root">, and
 * everything else assembled by JavaScript. Google will usually execute that and
 * index the result, eventually. Nothing else will:
 *
 *   Bing, DuckDuckGo and most smaller crawlers index the HTML they are served.
 *   WhatsApp, Facebook, LinkedIn, X and Slack read og: tags from the raw
 *     response and never run scripts — which matters here more than the search
 *     engines do, because this product spreads by WhatsApp link. An unfurled
 *     link with no title and no image looks like spam.
 *
 * So after `vite build`, this walks the built site with a real browser and saves
 * what the browser produced. Each public route becomes dist/<route>/index.html,
 * containing the finished markup AND the per-page <title>, description, canonical
 * and og: tags that useSeo() sets at runtime.
 *
 * The SPA still works exactly as before: these files are what a crawler (or a
 * cold first visit) receives, and React hydrates over them.
 *
 *   npm run build   → vite build && node scripts/prerender.mjs
 */

import { chromium } from "playwright";
import { preview } from "vite";
import fs from "node:fs/promises";
import path from "node:path";

// Mirrors PUBLIC_ROUTES in src/config/routePaths.js. A page added there and not
// here is simply not prerendered — it still works, it is just invisible to the
// crawlers that do not run JavaScript.
const ROUTES = [
  "/",
  "/about",
  "/features",
  "/pricing",
  "/contact",
  "/faq",
  "/privacy",
  "/terms",
  "/become-affiliate",
];

const DIST = path.resolve("dist");
const PORT = 4178;

function outputPathFor(route) {
  return route === "/"
    ? path.join(DIST, "index.html")
    : path.join(DIST, route.replace(/^\//, ""), "index.html");
}

const server = await preview({
  preview: { port: PORT, strictPort: true },
  logLevel: "warn",
});

const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();

let written = 0;
const failures = [];

for (const route of ROUTES) {
  try {
    const response = await page.goto(`http://localhost:${PORT}${route}`, {
      waitUntil: "networkidle",
      timeout: 30000,
    });
    if (!response || response.status() >= 400) {
      failures.push(`${route} → HTTP ${response?.status()}`);
      continue;
    }

    // useSeo() writes the title in an effect, so wait for it to stop being the
    // shell's default before capturing — otherwise every page is saved with
    // the same generic title, which is the exact problem this is fixing.
    await page
      .waitForFunction(() => document.title && document.title.length > 0, { timeout: 5000 })
      .catch(() => {});

    const html = await page.content();

    // A page whose body never rendered is worse than no prerender at all: it
    // would serve a crawler an empty shell and look deliberate.
    const bodyText = await page.locator("body").innerText();
    if (bodyText.trim().length < 200) {
      failures.push(`${route} → rendered almost nothing (${bodyText.trim().length} chars)`);
      continue;
    }

    const outPath = outputPathFor(route);
    await fs.mkdir(path.dirname(outPath), { recursive: true });
    await fs.writeFile(outPath, html, "utf8");

    const title = await page.title();
    console.log(`  ${route.padEnd(20)} → ${path.relative(DIST, outPath).padEnd(28)} "${title}"`);
    written += 1;
  } catch (error) {
    failures.push(`${route} → ${error.message.split("\n")[0]}`);
  }
}

await browser.close();
await server.close();

console.log(`\nprerendered ${written}/${ROUTES.length} public pages`);
if (failures.length) {
  console.error("\nfailed:");
  for (const failure of failures) console.error(`  ${failure}`);
  // Fail the build. A silently half-prerendered site is worse than an obviously
  // broken one, because nobody discovers it until a shared link looks wrong.
  process.exit(1);
}
