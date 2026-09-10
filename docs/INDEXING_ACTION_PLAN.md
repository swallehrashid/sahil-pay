# Sahil Pay — Indexing Action Plan

> Measured against the live site on **2026-08-20**. This supersedes the parts of
> `SEO_INDEXING_GUIDE.md` that have gone stale — in particular §8, which said
> Cloudflare was not active. It is now.

## Where you actually stand today

| Check | Result |
|---|---|
| `https://sahilpay.co.ke/` | 200 OK, **2,837 bytes** |
| `/pricing`, `/faq`, `/features` titles | all `Sahil Pay — Smart Rent Collection` — the generic one |
| Prerendering | **STILL NOT RUNNING.** Same problem as 6 days ago |
| Local `client/dist/` | only `dist/index.html` — no per-route folders |
| `sitemap.xml` | live, 9 URLs |
| `og-image.png` | live, `image/png` |
| Cloudflare | **now active** (`server: cloudflare`, `cf-ray` present) |
| Googlebot / Bingbot fetch | 200, not challenged |
| `http://` → `https://` | 301, correct |
| `https://www.` → apex | **no redirect — serves a duplicate 200** |
| Cloudflare managed robots block | prepended above yours, blocks GPTBot / ClaudeBot / Google-Extended |

**The one thing that matters: your pages still contain zero words.** Do not
request indexing until that is fixed — you would be asking Google to index a
blank page and then waiting weeks for it to change its mind.

---

## Step 1 — Prerender (blocker; nothing else counts until this is done)

SSH to the VPS:

```bash
ssh sahilpay@YOUR_SERVER_IP
```

Install headless Chromium once (~400 MB):

```bash
cd /var/www/sahilpay/app/client && npx playwright install --with-deps chromium
```

If that fails on sudo, run `sudo npx playwright install-deps chromium` first,
then `npx playwright install chromium` as the `sahilpay` user.

Rebuild and deploy:

```bash
cd /var/www/sahilpay/app && ./deploy/update.sh
```

Watch for `prerendered ✔` instead of `SKIPPED`.

### Prove it — run from your laptop, not the server

```bash
curl -s https://sahilpay.co.ke/pricing | grep -o "<title>.*</title>"
```

Must read `Pricing — Per Unit, Per Month | Sahil Pay`. If it still says
`Smart Rent Collection`, the build did not reach `/var/www/sahilpay/client`.

```bash
curl -s https://sahilpay.co.ke/faq | wc -c
```

Must be tens of thousands, not 2,837.

### Cloudflare cache

Cloudflare now sits in front of the site. After deploying:
Cloudflare dashboard → **Caching → Configuration → Purge Everything**.
Otherwise crawlers keep receiving the old empty HTML.

---

## Step 2 — Cloudflare settings (click-by-click)

Verified from outside on 2026-08-20, so you only need to change **three** things:

| Setting | State | Action |
|---|---|---|
| Always Use HTTPS | already ON (http 301s correctly) | nothing |
| Rocket Loader | already OFF (nothing injected) | nothing |
| Auto Minify | **removed by Cloudflare in 2024** | does not exist, ignore |
| Bot Fight Mode | likely ON (CLOUDFLARE_SETUP.md §7 said to enable it) | turn off, or add skip rule |
| Crawler Hints | OFF | turn ON |
| www → apex redirect | missing, www serves a duplicate 200 | create |

### 2A — Get to the right screen

1. **dash.cloudflare.com**, sign in.
2. Account Home lists your sites → **click `sahilpay.co.ke`**.
3. A left sidebar appears: Overview, DNS, SSL/TLS, Security, Speed, Caching, Rules.

Cloudflare reorganises these menus regularly. If a path below does not match,
use the **search box at the top of the dashboard** — type the setting name.

### 2B — Bot Fight Mode

**Security → Bots** (or **Security → Settings**, "Bots" section).

Note: Bot Fight Mode exempts *verified* crawlers, and Googlebot + Bingbot were
both confirmed fetching at 200 on 2026-08-20. Nothing is currently broken. Either:

- Toggle **Bot Fight Mode → Off** (simplest), or
- Leave it on and exempt crawlers explicitly:
  **Security → WAF → Custom rules → Create rule**
  - Name: `Allow search engine crawlers`
  - Edit expression → paste `(cf.client.bot)`
  - Action **Skip** → tick **All remaining custom rules** → **Deploy**

### 2C — Crawler Hints → ON

**Caching → Configuration** → scroll to **Crawler Hints** → **On**.
Auto-notifies IndexNow whenever pages change.

### 2D — www → apex redirect

**Rules → Redirect Rules → Create rule**

- Name: `www to apex`
- Custom filter expression: Hostname **equals** `www.sahilpay.co.ke`
- Then → Type **Dynamic**
- Expression: `concat("https://sahilpay.co.ke", http.request.uri.path)`
- Status code **301** → **Deploy**

Verify:

```bash
curl -sI https://www.sahilpay.co.ke/ | grep -iE '^(HTTP|location)'
```

### 2E — Purge after every deploy

**Caching → Configuration → Purge Everything.**

Run this immediately after Step 1's `./deploy/update.sh`. Cloudflare is caching
the current empty pages; without a purge, crawlers keep receiving old blank HTML.

---

## Step 3 — Google Search Console

**https://search.google.com/search-console** — sign in with an account you will
not lose (not a personal throwaway).

1. **Add property** → choose **Domain** (left box) → type `sahilpay.co.ke`
2. Google gives you a TXT record: `google-site-verification=...`
3. Cloudflare → **DNS → Records → Add record**
   - Type `TXT`, Name `@`, Content = the exact string Google gave you
4. Wait 5–15 min, confirm with:

```bash
dig TXT sahilpay.co.ke +short
```

5. Click **Verify**.

### Submit the sitemap

Sidebar → **Sitemaps** → type `sitemap.xml` → **Submit**.
Expect **Success**, **9 discovered URLs**.

---

## Step 4 — Force the crawl (as close to immediate as exists)

Only after Step 1 verifies.

In Search Console, paste each URL into the search bar at the very top, wait for
the inspection, then click **Request indexing**:

```
https://sahilpay.co.ke/
https://sahilpay.co.ke/faq
https://sahilpay.co.ke/pricing
https://sahilpay.co.ke/features
https://sahilpay.co.ke/about
```

Quota is roughly 10/day. Those five are the ones that matter — `/faq` is second
because it prerenders to ~12,000 characters with `FAQPage` structured data,
which is your strongest page.

Then **URL Inspection → View crawled page** on the homepage. You should see real
HTML with visible text. That is Google confirming Step 1 worked.

### Bing — this one really is fast

**https://www.bing.com/webmasters**

1. **Import from Google Search Console** (two clicks, copies property + sitemap)
2. **URL Submission** → submit all 9 URLs. Bing's quota is generous.
3. **IndexNow** → generate a key. With Cloudflare Crawler Hints on (Step 2),
   changes get pushed automatically from then on.

Bing/IndexNow submissions are typically picked up within hours. Bing also feeds
DuckDuckGo and several AI assistants.

---

## Step 5 — Social scrapers (the fastest visible win)

These never run JavaScript, so Step 1 is what makes them work. Each caches
separately and must be re-scraped by hand:

| Platform | Tool |
|---|---|
| Facebook / **WhatsApp** | https://developers.facebook.com/tools/debug/ |
| LinkedIn | https://www.linkedin.com/post-inspector/ |
| X | https://cards-dev.twitter.com/validator |

Paste `https://sahilpay.co.ke`, press **Scrape Again** on the Facebook one —
that is what refreshes WhatsApp previews. Then send yourself the link on
WhatsApp and confirm the card renders.

For a product that spreads by WhatsApp forward, this is arguably worth more than
the Google ranking.

---

## Step 6 — Google Business Profile

**https://business.google.com** → Add business

- Name: **Sahil Pay** (character-for-character identical to the site)
- Category: *Software company*; secondary *Property management company*
- No walk-in office → "I deliver goods and services to my customers", service
  area Nairobi / Kenya
- Website: `https://sahilpay.co.ke`
- Phone: exactly the number on your contact page, formatted the same
- Verify (usually postcard), then add description mentioning M-Pesa rent
  collection, your logo, and 3–5 product screenshots

Name, phone and URL must match everywhere. Inconsistency quietly costs you.

---

## Step 7 — Citations, same week

Free and each is a real signal: BusinessList.co.ke, Yellow Pages Kenya, a
LinkedIn company page, Product Hunt, AlternativeTo, SaaSHub, Capterra.

---

## A decision you should make consciously

Cloudflare has prepended a managed block to your `robots.txt` that sets
`ai-train=no` and disallows **GPTBot, ClaudeBot, Google-Extended, CCBot,
Bytespider, Amazonbot, meta-externalagent**.

- **Googlebot and Bingbot are unaffected** — normal search indexing is fine.
- But no AI assistant can read your site to describe your product when someone
  asks it about Kenyan rent software.

If you want AI assistants to be able to recommend Sahil Pay, turn that off:
Cloudflare → **AI Crawl Control** (or Security → Bots → AI Scrapers). If you'd
rather your content not train models, leave it. Your call — just make it
deliberately.

---

## Honest timeline

Nobody can force immediate Google indexing. What is actually achievable:

| When | What |
|---|---|
| Minutes after Step 5 | WhatsApp / Facebook / LinkedIn previews work |
| Hours after Step 4 | Bing indexes |
| 2–7 days | Google indexes the 5 URLs you requested; `site:sahilpay.co.ke` returns results |
| 2–4 weeks | All 9 pages indexed; you rank for your own brand name |
| 1–3 months | Long-tail terms — *M-Pesa rent collection software* |
| 3–6 months | Competitive terms, on the strength of content + links |

Anyone promising faster than the Google column is selling something.

---

## Self-check, any time

```bash
curl -s https://sahilpay.co.ke/pricing | grep -o "<title>.*</title>"
curl -s https://sahilpay.co.ke/faq | wc -c
curl -s -o /dev/null -w "%{http_code}\n" https://sahilpay.co.ke/sitemap.xml
curl -s https://sahilpay.co.ke/robots.txt | grep -i sitemap
```
