/**
 * prerender.mjs — bake the public pages into static HTML after a build.
 *
 * The app is a single-page build: every route ships the same near-empty
 * index.html and fills itself in with JavaScript. Google does execute JS before
 * indexing, so the site is indexable without this — but "indexable" and "well
 * indexed" are different things. A crawler that gets real HTML on the first
 * response reads the page immediately, every time, instead of waiting for a
 * render pass that is queued, occasionally skipped, and never guaranteed. Other
 * crawlers (Bing, and the link previewers in WhatsApp, Facebook and X, which
 * matter a lot in this market) don't run JavaScript at all.
 *
 * So: after `vite build`, load each public route in a real browser, wait for
 * React to finish, and write the resulting HTML to dist/<route>/index.html.
 * nginx's `try_files $uri $uri/ /index.html` serves those directory files
 * before falling back to the SPA shell, so signed-in routes are untouched.
 *
 *   npm run build && node scripts/prerender.mjs
 */

import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile, access } from "node:fs/promises";
import { extname, join, resolve } from "node:path";

const DIST = resolve("dist");
const PORT = 4178;

// Public marketing routes only. These must mirror PUBLIC_ROUTES in
// src/config/routePaths.js — add a public page there and add it here too, or it
// ships as an empty shell to every crawler that doesn't run JavaScript.
const ROUTES = [
  "/",
  "/features",
  "/pricing",
  "/about",
  "/contact",
  "/faq",
  "/privacy",
  "/terms",
  "/become-affiliate",
];

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
  ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
  ".woff": "font/woff", ".woff2": "font/woff2", ".ico": "image/x-icon",
  ".xml": "application/xml", ".txt": "text/plain",
};

async function exists(path) {
  try { await access(path); return true; } catch { return false; }
}

/** A tiny static server with SPA fallback — the same shape as production nginx. */
function serveDist() {
  return createServer(async (req, res) => {
    const url = decodeURIComponent((req.url || "/").split("?")[0]);
    let filePath = join(DIST, url);

    if (!(await exists(filePath)) || url.endsWith("/")) {
      const indexed = join(filePath, "index.html");
      filePath = (await exists(indexed)) ? indexed : join(DIST, "index.html");
    }

    try {
      const body = await readFile(filePath);
      res.writeHead(200, { "Content-Type": MIME[extname(filePath)] ?? "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404).end("Not found");
    }
  });
}

async function run() {
  if (!(await exists(join(DIST, "index.html")))) {
    console.error("prerender: dist/index.html is missing — run `npm run build` first.");
    process.exit(1);
  }

  const server = serveDist();
  await new Promise((ok) => server.listen(PORT, ok));

  const browser = await chromium.launch();
  const page = await browser.newPage();
  let written = 0;

  for (const route of ROUTES) {
    const url = `http://127.0.0.1:${PORT}${route}`;
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
      // The SEO hook sets title/meta/JSON-LD in an effect, so wait for the tags
      // themselves rather than a fixed delay — a snapshot taken too early would
      // bake in the generic fallback title and be worse than no prerender.
      await page.waitForFunction(
        () => document.title && document.querySelector('link[rel="canonical"]'),
        { timeout: 10000 },
      ).catch(() => {});
      await page.waitForTimeout(400);

      const html = await page.content();
      const title = await page.title();

      const outDir = route === "/" ? DIST : join(DIST, route);
      await mkdir(outDir, { recursive: true });
      await writeFile(join(outDir, "index.html"), html, "utf-8");

      written += 1;
      console.log(`  ✓ ${route.padEnd(20)} ${title}`);
    } catch (err) {
      // One bad page must not fail the deploy — it just falls back to the SPA
      // shell, which is exactly where it was before.
      console.warn(`  ! ${route.padEnd(20)} skipped: ${err.message.split("\n")[0]}`);
    }
  }

  await browser.close();
  server.close();

  console.log(`\nprerender: wrote ${written}/${ROUTES.length} public pages.`);
  if (written === 0) process.exit(1);
}

run().catch((err) => {
  console.error("prerender failed:", err);
  process.exit(1);
});
