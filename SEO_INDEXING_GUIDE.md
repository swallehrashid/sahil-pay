# Sahil Pay — Getting the Public Pages Indexed

> **Written against your LIVE site on 2026-08-14.** Everything in §1 is what I
> actually found by fetching `https://sahilpay.co.ke`, not an assumption.
>
> **The headline:** your SEO infrastructure is genuinely good — per-page titles,
> descriptions, canonicals, OpenGraph, JSON-LD, a sitemap and a robots.txt all
> exist and are correct. But **none of it reaches a crawler**, because the
> prerender step never ran on the server. Your homepage currently serves
> **zero words of text**.
>
> Fixing that is one 15-minute job on the VPS, and it is by far the highest-value
> thing in this document. Everything else is follow-up.

---

## Table of contents

1. [What I found on your live site](#1-audit)
2. [Why an empty page is the whole problem](#2-why)
3. [Step 1 — Turn on prerendering (do this first)](#3-prerender)
4. [Step 2 — Deploy the social preview image](#4-og)
5. [Step 3 — Google Search Console](#5-gsc)
6. [Step 4 — Bing Webmaster Tools](#6-bing)
7. [Step 5 — Google Business Profile](#7-gbp)
8. [Step 6 — Cloudflare settings that affect indexing](#8-cloudflare)
9. [Getting found for the right searches](#9-keywords)
10. [Off-site: the links that actually matter in Kenya](#10-offsite)
11. [Monitoring — what to check and when](#11-monitor)
12. [Adding a new public page later](#12-newpage)
13. [Realistic timeline](#13-timeline)

---

<a name="1-audit"></a>
## 1. What I found on your live site

I fetched your production pages exactly as a crawler would. Here is the honest
state of things.

### ✅ What is already right

| Thing | Status |
|---|---|
| `https://sahilpay.co.ke` responds | **200 OK** |
| `robots.txt` | **Live and correct** — allows the marketing pages, blocks `/landlord`, `/admin`, `/tenant`, `/team`, `/affiliate`, every auth flow and `/api/` |
| `sitemap.xml` | **Live**, lists all 9 public pages, referenced from robots.txt |
| Per-page SEO code | All 9 public pages call `useSeo()` with real titles and descriptions |
| Structured data code | Organization, SoftwareApplication with live prices, and a full FAQPage over your question bank |
| Private areas hidden | Correct — no tenant data is crawlable |

### 🔴 What is broken

**Every public page serves the same generic title, no description of its own,
no social image, and no body text at all.**

Measured on your live site:

| Page | Title served to a crawler | Body text |
|---|---|---|
| `/` | "Sahil Pay — Smart Rent Collection" | **0 characters** |
| `/pricing` | "Sahil Pay — Smart Rent Collection" | **0 characters** |
| `/features` | "Sahil Pay — Smart Rent Collection" | **0 characters** |
| `/faq` | "Sahil Pay — Smart Rent Collection" | **0 characters** |

`og:image`: **absent entirely.**

### Why — and it is a single cause

Your site is a React single-page app. The server sends an empty HTML shell, and
JavaScript draws the page in the visitor's browser. `useSeo()` sets the correct
title *after* that JavaScript runs.

The repo already contains the fix — a **prerender** step that loads each public
page in a real browser at build time and saves the finished HTML. It has simply
never been run on the server, because it needs a headless Chromium that isn't
installed there.

**Everything in the broken table above is fixed by one step: §3.**

---

<a name="2-why"></a>
## 2. Why an empty page is the whole problem

It matters differently depending on who is looking.

| Who | Runs JavaScript? | What they see today |
|---|---|---|
| **Google** | Yes, eventually | Can index you, but on a slow second pass. Ranking suffers. |
| **Bing** | Barely | Close to nothing. |
| **WhatsApp** | **No** | No preview — your link looks like bare text |
| **Facebook / Instagram** | **No** | No preview |
| **LinkedIn** | **No** | No preview |
| **X / Twitter** | **No** | No preview |
| **AI assistants** | Mostly no | Cannot describe your product |

For a Kenyan product that spreads by **WhatsApp**, that fourth row is arguably
more commercially important than Google. Right now, when a landlord forwards
`sahilpay.co.ke` to another landlord, it arrives as a naked blue link with no
title, no description and no image — indistinguishable from spam.

After §3 and §4, the same forward arrives with your logo, a headline and a
sentence explaining what it is.

---

<a name="3-prerender"></a>
## 3. Step 1 — Turn on prerendering (do this first)

**Time: ~15 minutes. Impact: everything below depends on it.**

### What this does

`npm run prerender` starts your built site locally, loads each of the 9 public
pages in a headless Chromium, waits for React to finish, and writes the
resulting HTML to `dist/<route>/index.html`. nginx then serves *that* file —
already full of text — to crawlers and humans alike.

I ran it on my machine to be certain it works. Results:

| Page | Text after prerendering | Structured data |
|---|---|---|
| `/` | 6,030 characters | Organization |
| `/features` | 5,896 characters | Organization |
| `/pricing` | 3,555 characters | SoftwareApplication + Organization |
| `/faq` | **12,145 characters** | FAQPage + Organization |
| `/about` | 3,595 characters | Organization |
| `/contact` | 2,999 characters | Organization |
| `/become-affiliate` | 1,233 characters | Organization |
| `/privacy` | 1,234 characters | Organization |
| `/terms` | 1,220 characters | Organization |

And real per-page titles, e.g.
*"Pricing — Per Unit, Per Month | Sahil Pay"*,
*"Rental Management FAQs for Kenyan Landlords | Sahil Pay"*.

### Do it

```bash
ssh sahilpay@YOUR_SERVER_IP
cd /var/www/sahilpay/app/client
```

**3a. Install the headless browser (one time, ~400 MB):**

```bash
npx playwright install --with-deps chromium
```

> `--with-deps` also installs the Linux system libraries Chromium needs. On
> Ubuntu it may ask for your sudo password. If it refuses because it cannot use
> sudo, run `sudo npx playwright install-deps chromium` first, then
> `npx playwright install chromium` as the `sahilpay` user.

**3b. Rebuild and prerender:**

```bash
cd /var/www/sahilpay/app
./deploy/update.sh
```

The deploy script already tries the prerender and now prints `prerendered ✔`
instead of `SKIPPED` once Chromium is present.

> If you prefer to do only the frontend, without touching the backend:
> ```bash
> cd /var/www/sahilpay/app/client
> npm run build && npm run prerender
> sudo rm -rf /var/www/sahilpay/client && sudo cp -r dist /var/www/sahilpay/client
> sudo systemctl reload nginx
> ```

### 🔴 3c. Prove it worked

This is the check that matters. Run it from **your laptop**, not the server:

```bash
curl -s https://sahilpay.co.ke/pricing | grep -o "<title>.*</title>"
```

- **Before:** `<title>Sahil Pay — Smart Rent Collection</title>`
- **After:** `<title>Pricing — Per Unit, Per Month | Sahil Pay</title>`

And confirm there is real text in the HTML:

```bash
curl -s https://sahilpay.co.ke/ | wc -c
```

Before it was **1,815 bytes**. After prerendering it should be **tens of
thousands**.

If the title has not changed, the new build did not reach `/var/www/sahilpay/client`.
Check that `dist/pricing/index.html` exists on the server and was copied across.

### One thing to know about nginx

Your config has:

```nginx
location / { try_files $uri $uri/ /index.html; }
```

The `$uri/` part is what makes this work: a request for `/pricing` finds the
directory `pricing/` and serves `pricing/index.html`. **No nginx change is
needed** — it already does the right thing once the files exist.

---

<a name="4-og"></a>
## 4. Step 2 — Deploy the social preview image

**Time: included in the same deploy. Impact: every WhatsApp share.**

### What was wrong

`og:image` pointed at `/favicon.svg`. **No social platform renders SVG previews**
— not WhatsApp, Facebook, LinkedIn or X. And `twitter:card` was set to
`summary_large_image`, which expects a 1200×630 raster image. So the tag was
present and useless.

### What I changed

1. Created **`client/public/og-image.png`** — a real 1200×630 branded card
   (deep indigo, the Sahil Pay wordmark, "Collect rent on M-Pesa. Invoices,
   receipts and reports in one place." and "Built for Kenyan landlords and
   property managers"). 40 KB.
2. Pointed `useSeo()`'s default image at it.
3. Added **baseline OpenGraph tags directly into `client/index.html`**, so even
   a scraper that never runs JavaScript — and even if prerendering is off — gets
   a title, description and image.
4. Wired up `ORGANIZATION_JSON_LD`, which had been written and exported months
   ago but **never imported by anything**. It now renders on every public page,
   which is what lets Google associate your brand name, logo and contact details
   with the site.

All of this ships with the same `./deploy/update.sh` from §3.

### Test the preview after deploying

Paste `https://sahilpay.co.ke` into each of these. They each keep their own
cache, so you must ask each one to re-scrape.

| Tool | URL |
|---|---|
| Facebook / WhatsApp | https://developers.facebook.com/tools/debug/ |
| LinkedIn | https://www.linkedin.com/post-inspector/ |
| X / Twitter | https://cards-dev.twitter.com/validator |

> **WhatsApp uses Facebook's cache.** Run the Facebook debugger and press
> **Scrape Again** — that is what refreshes WhatsApp previews. Otherwise
> WhatsApp may keep showing the old empty preview for days.

Then send yourself the link on WhatsApp and confirm the card appears.

---

<a name="5-gsc"></a>
## 5. Step 3 — Google Search Console

**Time: 20 minutes. This is how you tell Google you exist.**

Submitting a sitemap does not *make* Google index you, but without it you are
waiting to be discovered by accident.

### 5.1 Add and verify the property

1. Go to **https://search.google.com/search-console**
2. Sign in with the Google account you want to own this permanently — **not a
   personal account you might lose access to.**
3. Click **Add property**.
4. Choose **Domain** (the left box), enter `sahilpay.co.ke`, click **Continue**.

> **Domain vs URL prefix:** *Domain* covers `http`, `https`, `www` and every
> subdomain in one property. It needs a DNS record. *URL prefix* is easier to
> verify but only covers the exact prefix. **Choose Domain** — it is the right
> long-term answer and you will not have to redo it.

5. Google shows you a **TXT record** like:

   ```
   google-site-verification=AbCdEf1234...
   ```

6. Add it to your DNS:

   - **If Cloudflare is active** (see §8): Cloudflare dashboard → your domain →
     **DNS → Records → Add record**. Type `TXT`, Name `@`, Content the string
     Google gave you. Save.
   - **If you are still on your registrar's DNS**: log in at HostPinnacle,
     find DNS/Zone management, add the same TXT record.

7. Wait 5–15 minutes, then click **Verify** in Search Console.

> If verification fails, check propagation first:
> ```bash
> dig TXT sahilpay.co.ke +short
> ```
> Your verification string must appear. If it does not, the record has not
> propagated yet — wait and retry rather than adding it twice.

### 5.2 Submit the sitemap

1. In Search Console, left sidebar → **Sitemaps**.
2. Under *Add a new sitemap*, type: `sitemap.xml`
3. Click **Submit**.

Status should become **Success** with **9 discovered URLs**. If it says
*Couldn't fetch*, open `https://sahilpay.co.ke/sitemap.xml` in a browser — it
works today, so the usual cause is a typo or a Cloudflare rule blocking Google.

### 5.3 Request indexing for your key pages

Do not wait to be crawled. For each of these, paste the full URL into the search
bar at the top of Search Console, then click **Request indexing**:

```
https://sahilpay.co.ke/
https://sahilpay.co.ke/features
https://sahilpay.co.ke/pricing
https://sahilpay.co.ke/faq
https://sahilpay.co.ke/about
```

Each takes about a minute. There is a daily quota of roughly 10, which is why
the list above is the five that matter.

> 🔴 **Do this AFTER §3.** If you request indexing while the pages are still
> empty, Google indexes an empty page and you then have to wait for it to
> re-crawl and change its mind. Order matters.

### 5.4 Check the rendered page

Still in Search Console, use **URL Inspection** on `https://sahilpay.co.ke/`,
then click **View crawled page**. You should see your real HTML with visible
text. That is Google confirming §3 worked.

---

<a name="6-bing"></a>
## 6. Step 4 — Bing Webmaster Tools

**Time: 5 minutes. Worth it because Bing barely runs JavaScript** — before §3 it
could see essentially nothing of your site, and Bing also feeds DuckDuckGo and
several AI assistants.

1. Go to **https://www.bing.com/webmasters**
2. Sign in.
3. Choose **Import from Google Search Console** — this copies the property and
   the sitemap in two clicks, and is much faster than verifying again.
4. If you would rather not link accounts, add `sahilpay.co.ke` manually and
   verify with the same TXT-record method as §5.1.
5. Confirm the sitemap is listed under **Sitemaps**.
6. Use **URL Submission** to submit your five key pages. Bing's quota is
   generous — you can submit all nine.

---

<a name="7-gbp"></a>
## 7. Step 5 — Google Business Profile

**Time: 15 minutes, plus postcard verification. High value locally.**

For a Kenyan B2B product, a Business Profile is often worth more than a
first-page ranking: it puts you in Google Maps and in the panel on the right of
a branded search.

1. Go to **https://business.google.com**
2. **Add your business** → name it exactly **Sahil Pay** (identical to your
   site — inconsistent naming dilutes the association).
3. **Category:** *Software company*. Add *Property management company* as a
   secondary category.
4. **Service area:** if you have no walk-in office, choose *I deliver goods and
   services to my customers* and set your service area to Nairobi / Kenya. You
   do not have to publish a home address.
5. **Website:** `https://sahilpay.co.ke`
6. **Phone:** the number on your contact page — **the same one**, formatted the
   same way.
7. Verify (usually a postcard, sometimes phone or email).
8. Once verified, add: a description mentioning M-Pesa rent collection, your
   logo, and 3–5 screenshots of the product.

> **Keep name, address and phone identical** across your website, Business
> Profile and any directory listing. Google uses that consistency as a
> confidence signal, and small differences quietly cost you.

---

<a name="8-cloudflare"></a>
## 8. Step 6 — Cloudflare settings that affect indexing

**Current status: Cloudflare is NOT active on your domain.** I checked — your
site responds with `Server: nginx` and no `cf-ray` header, which means traffic
goes straight to your VPS.

**That is fine.** Cloudflare is not required for indexing and nothing here
blocks you. But when you do switch it on (see `REDEPLOY_2026-08.md` §5), three
settings can silently break your SEO:

| Setting | Set to | Why |
|---|---|---|
| **Bot Fight Mode** | **OFF** | It challenges automated traffic — including Googlebot and Bingbot. This is the classic way a site vanishes from search after moving to Cloudflare. |
| **Security Level** | Medium or lower | *High* / *I'm Under Attack* challenges crawlers. |
| **Rocket Loader** | **OFF** | Rewrites your JavaScript and can break a React app in hard-to-diagnose ways. |
| **Auto Minify → JavaScript** | **OFF** | Same risk. |
| **Always Use HTTPS** | ON | One canonical scheme; avoids duplicate-content splits. |
| **Caching Level** | Standard | Fine for a static frontend. |

After any content change with Cloudflare on, **Caching → Purge Everything** —
otherwise crawlers keep getting the old cached HTML.

### The bot rule to add

If you must keep Bot Fight Mode on, exempt the crawlers explicitly:

Security → WAF → Custom rules → Create rule:

- **Name:** `Allow search engine crawlers`
- **Expression:** `(cf.client.bot)`
- **Action:** `Skip` → all remaining custom rules

`cf.client.bot` is Cloudflare's own list of *verified* bots, so this lets real
Googlebot through without opening the door to anything impersonating it.

---

<a name="9-keywords"></a>
## 9. Getting found for the right searches

Once §3 is done, your pages are competing on their content. Here is what they
already say, and where the gaps are.

### What you currently target

| Page | Title served after prerendering |
|---|---|
| `/` | Rental & Property Management Software for Kenya |
| `/features` | Features — M-Pesa Rent Collection, Invoicing & Reports |
| `/pricing` | Pricing — Per Unit, Per Month |
| `/faq` | Rental Management FAQs for Kenyan Landlords |
| `/about` | About Sahil Pay — Built in Kenya for Kenyan Landlords |
| `/become-affiliate` | Become an Affiliate — Earn Recurring Commission |

These are good. They are specific, they name the market, and they are not
stuffed with keywords.

### The realistic searches to win

You will not outrank international property software on generic terms, and you
should not try. Win the **local, specific, high-intent** searches:

- *rent collection software Kenya*
- *M-Pesa rent collection system*
- *property management software Nairobi*
- *how to collect rent through M-Pesa paybill*
- *landlord software Kenya*
- *rental management system Kenya*
- *KRA rental income tax software* ← nobody local is competing here, and you
  have a whole eTIMS/MRI feature
- *eTIMS for landlords*

### Your biggest untapped asset

**The FAQ page prerenders to 12,145 characters with full `FAQPage` structured
data.** That is the single strongest page you have for search, because Google
can lift individual questions straight into results.

Two things to do with it:

1. **Make sure the questions are phrased the way people actually type them.**
   "How do I collect rent through M-Pesa?" beats "Payment collection methods".
2. **Consider splitting the biggest topics into their own pages** later —
   a dedicated page on filing rental income tax with eTIMS would rank on its
   own, and you already have the expertise written down.

### The content gap worth filling

You have no blog or guides section on the public site. You *do* have a Help
Content CMS with real articles — but it lives behind a login, so search engines
never see it.

The highest-leverage SEO work available to you is publishing a few of those
guides publicly:

- *How to file rental income tax (MRI) in Kenya — a landlord's guide*
- *Setting up an M-Pesa paybill for rent collection*
- *What eTIMS means for landlords*

These are searched for, nobody local answers them well, and you have already
written the content. That would need a new public route plus sitemap and
prerender entries — see §12.

---

<a name="10-offsite"></a>
## 10. Off-site: the links that actually matter in Kenya

Google ranks you partly on who links to you. For a new Kenyan SaaS, these are
worth more than any amount of on-page tweaking:

1. **Kenyan business directories** — BusinessList.co.ke, Yellow Pages Kenya,
   Kenya Business Directory. Free, and each is a real citation.
2. **Product directories** — Product Hunt, AlternativeTo, SaaSHub, Capterra.
   Capterra in particular is where people compare property software.
3. **LinkedIn** — a company page linking to the site. Also the most likely place
   a property manager finds you.
4. **Kenyan property and landlord Facebook/WhatsApp groups** — share genuinely
   useful guides, not adverts. This is how products actually spread here.
5. **University and SACCO property forums** — many landlords are members.
6. **Local press** — Business Daily, Techweez, and similar cover Kenyan fintech.
   A short pitch about M-Pesa rent automation is a real story.

**Keep the name, phone and website identical everywhere.** Consistency is itself
a ranking signal.

---

<a name="11-monitor"></a>
## 11. Monitoring — what to check and when

### Week 1, daily

```bash
# Are your pages in the index yet?
# Paste into Google:
site:sahilpay.co.ke
```

Zero results in the first few days is normal. After two weeks with nothing,
open Search Console → **Pages** and read the exclusion reason.

### Weekly

| Where | What you are looking for |
|---|---|
| Search Console → **Pages** | Indexed count climbing toward 9 |
| Search Console → **Performance** | Which queries you appear for |
| Search Console → **Experience** | Core Web Vitals — a slow site ranks lower |
| Bing Webmaster | Same, on the Bing side |

### Monthly

- Re-run the Facebook debugger if you have changed the homepage copy.
- Update `lastmod` in `client/public/sitemap.xml` for any page whose copy has
  materially changed. A stale `lastmod` teaches crawlers to ignore it.

### A quick self-check you can run any time

```bash
# Title should be page-specific, not the generic sitewide one
curl -s https://sahilpay.co.ke/pricing | grep -o "<title>.*</title>"

# Should be tens of thousands of bytes, not ~1,800
curl -s https://sahilpay.co.ke/faq | wc -c

# Sitemap reachable
curl -s -o /dev/null -w "%{http_code}\n" https://sahilpay.co.ke/sitemap.xml

# robots.txt reachable and points at the sitemap
curl -s https://sahilpay.co.ke/robots.txt | grep -i sitemap
```

---

<a name="12-newpage"></a>
## 12. Adding a new public page later

Four files, and **missing any one of them means the page is invisible**. Both
the sitemap and the prerender list carry a comment saying exactly this, because
it is the easy thing to forget.

1. **`client/src/config/routePaths.js`** — add the path to `PUBLIC_ROUTES`.
2. **`client/src/routes/AppRoutes.jsx`** — mount the route inside `PublicLayout`.
3. **`client/public/sitemap.xml`** — add a `<url>` block, or Google never learns
   the page exists.
4. **`client/scripts/prerender.mjs`** — add the path to `ROUTES`, or the page
   ships as an empty shell to every crawler that does not run JavaScript.

In the page component itself, call `useSeo({ title, description, path })` with a
title unique to that page.

Then rebuild, prerender, deploy, and request indexing for the new URL in Search
Console.

---

<a name="13-timeline"></a>
## 13. Realistic timeline

Search indexing is slow, and anyone promising otherwise is selling something.

| When | What to expect |
|---|---|
| **Immediately after §3–4** | WhatsApp, Facebook and LinkedIn previews work. This is the fastest visible win. |
| **2–7 days** | Google indexes the pages you explicitly requested. `site:sahilpay.co.ke` starts returning results. |
| **2–4 weeks** | All 9 pages indexed. You start appearing for your own brand name. |
| **1–3 months** | You rank for long-tail terms like *M-Pesa rent collection software*. |
| **3–6 months** | Competitive terms become reachable — but mostly on the strength of §9's content work and §10's links. |

### If you do only three things

1. **§3 — turn on prerendering.** Nothing else matters until the pages have
   words in them.
2. **§5 — Search Console**, submit the sitemap, request indexing for five pages.
3. **§9's content gap** — publish two or three of your existing help guides as
   public pages. That is where durable traffic comes from.

---

## Appendix — a one-page summary of the current infrastructure

For anyone picking this up cold.

```
client/public/robots.txt        Allows marketing pages; blocks portals + /api
client/public/sitemap.xml       9 public URLs, referenced from robots.txt
client/public/og-image.png      1200x630 social card  ← added 2026-08-14
client/index.html               Baseline OG tags for non-JS scrapers  ← added
client/src/features/public/useSeo.js
                                Per-page title/description/canonical/OG/JSON-LD
                                + ORGANIZATION_JSON_LD (now rendered by the
                                  public layout — it previously was not)
client/scripts/prerender.mjs    Renders the 9 public routes to static HTML
deploy/update.sh                Runs the prerender; warns but does not fail
                                  if headless Chromium is missing
deploy/nginx/sahilpay.conf      `try_files $uri $uri/ /index.html` — already
                                  serves prerendered directories correctly
```

**Structured data in place:** `Organization` (every page),
`SoftwareApplication` with live pricing (`/pricing`), `FAQPage` over the full
question bank (`/faq`).
