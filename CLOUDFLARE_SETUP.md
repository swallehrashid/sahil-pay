# Moving sahilpay.co.ke to Cloudflare

**For:** the Sahil Pay operator. No code changes — this is all done in a browser.
**Cost:** KES 0. Everything below is on Cloudflare's Free plan, permanently free.
**Your time:** ~30 minutes, plus waiting.
**Downtime:** none expected, if you do the steps in this order.

Do this **after** the application changes are deployed, not before.

---

## Why bother

Right now every request from the public internet hits your server directly. That
means your server personally absorbs every bot, every scanner, and every attempt
to guess a password — and its IP address is public, so anyone who wants to attack
it knows exactly where to aim.

With Cloudflare in front, traffic lands on their network first. Bad traffic is
dropped before it ever reaches you, your real server IP stops being public, and
static files are served from a machine near the visitor instead of from Nairobi.

This is the single biggest security improvement available to you, and it needs no
code.

---

## What the FREE plan actually gives you

Be clear-eyed about this — the free tier is generous but not unlimited.

### You get, free, forever

| Feature | What it means in practice |
|---|---|
| **Unmetered DDoS protection** | No cap. A flood aimed at you is absorbed by Cloudflare's network, not your server. This is genuinely the same protection paid plans get. |
| **Global CDN** | Your JS, CSS and images are cached and served from a nearby city. Pages load noticeably faster, and your server does less work. |
| **Free SSL certificate** | Cloudflare issues and auto-renews one. Yours from certbot keeps working too — you want both (see "Full (strict)" below). |
| **Your server's IP hidden** | Attackers see Cloudflare's addresses, not yours. |
| **Bot Fight Mode** | Challenges obvious bots and scrapers automatically. |
| **5 WAF custom rules** | You write these yourself — e.g. "block anything that isn't from Kenya from reaching /admin". Enough for what you need. |
| **Always Online** | If your server goes down, Cloudflare serves a cached copy of your pages so visitors don't see a dead site. |
| **Analytics** | Real traffic numbers, attacks blocked, bandwidth saved. |
| **Page Rules (3)** | Per-URL behaviour, e.g. "never cache /api/*". |
| **Rate limiting (1 rule)** | One free rule — put it on the login endpoint. |

### You do NOT get on free

| Not included | Does it matter to you? |
|---|---|
| **Managed WAF rulesets** (the big pre-written OWASP rule packs) | Somewhat. You get 5 custom rules instead, which covers the important cases. The paid tier is $20/month if you later want the managed packs. |
| **Bot Management** (the advanced ML one) | No — Bot Fight Mode is enough at your size. |
| **Image optimisation / Polish** | No. |
| **Uptime SLA** | No — free has no guarantee. In practice it is extremely reliable. |
| **More than 1 rate-limiting rule** | Mildly. Your application now does its own rate limiting and account lockout, so Cloudflare's is a bonus layer, not the only one. |
| **WAF rules that run before caching on every plan feature** | Fine at your scale. |

**Honest summary:** free gives you the DDoS protection, the hidden IP, the CDN and
basic bot filtering. It does not give you an enterprise firewall. For a product at
your stage that is the right trade, and you can upgrade to Pro ($20/month) at any
time without redoing any of this.

---

## Before you start

Have ready:

1. Your Cloudflare account (create one free at dash.cloudflare.com).
2. Login for wherever **sahilpay.co.ke is registered** — your KeNIC registrar
   (Truehost, Kenya Website Experts, Safaricom, HostPinnacle, whoever you bought
   it from). You need to change nameservers there.
3. Your server's public IP address.

⚠️ **The one thing that can break M-Pesa:** Safaricom posts payment
confirmations to `https://sahilpay.co.ke/api/webhooks/daraja/...`. Those URLs are
registered with Safaricom and cannot be changed. Step 6 below creates a rule so
Cloudflare never challenges or blocks Safaricom. **Do not skip it.**

---

## Step-by-step

### 1. Add your site (2 minutes)

1. Sign in at **dash.cloudflare.com**.
2. Click **Add a site**.
3. Type `sahilpay.co.ke` (no `www`, no `https://`). Continue.
4. Choose the **Free** plan. Continue.

### 2. Check the DNS records Cloudflare imported (5 minutes)

Cloudflare scans your existing DNS and shows what it found. Check carefully:

- There must be an **A** record for `sahilpay.co.ke` → your server's IP.
- There must be a record for `www` (A record to the same IP, or CNAME to
  `sahilpay.co.ke`).
- Both must show an **orange cloud** (Proxied). Orange = protected by Cloudflare.
  Grey = DNS only, no protection. Click the cloud to toggle it orange.
- **Leave your email records (MX, TXT/SPF/DKIM) exactly as they are, grey.** Mail
  must not be proxied or your email stops working.

If a record is missing, add it manually before continuing.

### 3. Set SSL mode BEFORE switching nameservers (2 minutes)

**This step prevents the most common outage.** Do it now, not later.

1. Go to **SSL/TLS → Overview**.
2. Set encryption mode to **Full (strict)**.

Why: your server already has a valid certbot certificate. "Full (strict)" means
Cloudflare talks to your server over HTTPS and verifies that certificate. The
wrong setting here ("Flexible") causes an infinite redirect loop and your site
appears broken to everyone.

3. Go to **SSL/TLS → Edge Certificates** and turn on **Always Use HTTPS**.

### 4. Copy your two nameservers

Cloudflare shows two nameservers, something like:

```
dana.ns.cloudflare.com
rick.ns.cloudflare.com
```

Copy both exactly. Yours will have different names.

### 5. Change the nameservers at your registrar (5 minutes)

This is the actual switch. At your **registrar** (not Cloudflare):

1. Sign in and find your domain `sahilpay.co.ke`.
2. Look for **Nameservers**, **DNS Management**, or **Manage DNS**.
3. Choose **Custom nameservers** / **Use my own nameservers**.
4. **Delete the existing ones** and enter the two Cloudflare gave you.
5. Save.

Then go back to Cloudflare and click **Done, check nameservers**.

**Now you wait.** Cloudflare emails you when the site is active — usually under an
hour, occasionally up to 24. **Your site keeps working the whole time**; visitors
are served by whichever nameserver they reach.

### 6. 🔴 Protect the M-Pesa webhook (do this as soon as the site is active)

Safaricom's servers are not browsers. If Cloudflare challenges them, payment
confirmations stop arriving and tenants' payments will not appear in Sahil Pay.

1. Go to **Security → WAF → Custom rules**.
2. Click **Create rule**.
3. Rule name: `Allow Safaricom M-Pesa webhooks`
4. Set the expression — use the **Edit expression** box and paste:
   ```
   (starts_with(http.request.uri.path, "/api/webhooks/") or starts_with(http.request.uri.path, "/api/mpesa/"))
   ```
5. Action: **Skip**, and tick:
   - All remaining custom rules
   - Rate limiting
   - Managed rules
   - Bot Fight Mode (under "Skip specific components" if shown)
6. **Deploy**.

### 7. Turn on the protection (5 minutes)

- **Security → Bots →** turn on **Bot Fight Mode**.
- **Security → Settings →** Security Level: **Medium**.
- **Speed → Optimization →** leave **Auto Minify OFF**. Your build already
  minifies; doing it twice occasionally breaks scripts.
- **Caching → Configuration →** Caching Level: **Standard**, Browser Cache TTL:
  **Respect Existing Headers** (your nginx config already sets good ones).

### 8. Make sure the API is never cached

An API response cached and served to a different user would show one landlord
another landlord's data. Cloudflare does not cache API responses by default, but
make it explicit:

1. **Rules → Page Rules → Create Page Rule**.
2. URL: `*sahilpay.co.ke/api/*`
3. Setting: **Cache Level → Bypass**.
4. Save and Deploy.

### 9. Add the free rate-limiting rule (optional, 3 minutes)

You get one. Spend it on login:

1. **Security → WAF → Rate limiting rules → Create rule**.
2. Expression: `http.request.uri.path eq "/api/auth/login"`
3. Rate: **10 requests per 1 minute** per IP.
4. Action: **Block**, duration 10 minutes.

(The application already enforces its own login limits and account lockout, so
this is defence in depth, not the only guard.)

---

## Verify it worked

Run these once Cloudflare says the site is active:

```bash
# Should show "server: cloudflare"
curl -sI https://sahilpay.co.ke | grep -i server

# Should load normally
curl -sI https://sahilpay.co.ke | head -1

# The API should answer and NOT be cached
curl -sI https://sahilpay.co.ke/api/health | grep -iE "cf-cache-status|HTTP/"
```

Then, in a browser:

1. Open https://sahilpay.co.ke — the marketing site loads.
2. Sign in to your admin account — it works.
3. **Make one small real M-Pesa payment to your paybill** and confirm it appears
   in Sahil Pay within a minute. This is the test that matters most. If it does
   not arrive, check **Security → Events** in Cloudflare for a blocked request to
   `/api/webhooks/` and re-check Step 6.

---

## If something goes wrong

**Undo is easy and complete.** Nothing on your server changed.

1. Go back to your **registrar**.
2. Replace the Cloudflare nameservers with the original ones (write them down in
   Step 5 before you overwrite them — do this now if you haven't).
3. Save. Traffic returns to direct-to-server within the hour.

**Common problems:**

| Symptom | Cause | Fix |
|---|---|---|
| "Too many redirects" | SSL mode is Flexible | Set **Full (strict)** (Step 3) |
| M-Pesa payments stop arriving | Safaricom being challenged | Check Step 6's rule exists and is deployed |
| Email stopped working | MX records got proxied | Set MX/TXT records to **grey cloud** (DNS only) |
| Site shows Cloudflare error 521/522 | Cloudflare can't reach your server | Check your server is up and that your firewall isn't blocking Cloudflare's IPs |
| Login says "too many attempts" | Rate-limit rule too tight | Raise the limit in Step 9, or delete the rule |

---

## One thing to do afterwards

Once traffic comes through Cloudflare, your server should **only** accept traffic
from Cloudflare — otherwise an attacker who learns your IP can bypass all of this
by connecting directly. On the server:

```bash
# Allow only Cloudflare's IP ranges to reach ports 80/443.
# Cloudflare publishes them at https://www.cloudflare.com/ips/
# Ask your developer to apply this with ufw or in the nginx config —
# it is the step that makes the protection unbypassable.
```

This is worth doing, but do it **after** you have confirmed everything works,
and keep SSH (port 22) open to yourself or you will lock yourself out.
