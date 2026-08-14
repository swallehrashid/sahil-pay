# Sahil Pay — Redeployment Guide, August 2026

> **Read this once end to end before you touch anything.** It is written so
> that a second person (or another AI) can follow it with no other context.
>
> **Your situation:** last deployment was 2026-07-16. Since then the repo has
> gained **19 database migrations**, three new required environment variables,
> a new nginx config, a new scheduled job, and two new Python packages. You have
> also **changed your development machine to Ubuntu**, and you have **new
> Cloudinary credentials** that were never on the server.
>
> **Estimated time:** 25–40 minutes for the redeploy itself, plus ~20 minutes
> for Cloudflare (which can be done separately, before or after).

---

## Table of contents

1. [Vocabulary — the four places things live](#1-vocabulary)
2. [What changed since your last deploy](#2-what-changed)
3. [Your `.env` files — local and server](#3-env-files)
4. [The encryption key — what it is and how to make one](#4-encryption-key)
5. [Cloudflare — the complete walkthrough](#5-cloudflare)
6. [The Co-pilot Android app — do you need to rebuild?](#6-copilot)
7. [Ubuntu — what changing your OS does and doesn't affect](#7-ubuntu)
8. [The redeployment itself, step by step](#8-redeploy)
9. [Post-deploy checklist — prove it worked](#9-verify)
10. [If something goes wrong](#10-rollback)
11. [Appendix A — every migration being applied](#appendix-a)
12. [Appendix B — full production `.env` template](#appendix-b)

---

<a name="1-vocabulary"></a>
## 1. Vocabulary — the four places things live

You will be switching between these constantly. Getting them straight now
prevents most mistakes.

| Name | What it is | How you reach it |
|---|---|---|
| **Your laptop** | Ubuntu machine with the code and the local `.env` | you are on it |
| **GitHub** | Where the code is pushed to and pulled from | browser / `git` |
| **The VPS** | The HostPinnacle Ubuntu server that runs the live site | `ssh sahilpay@YOUR_SERVER_IP` |
| **The registrar** | Where you bought `sahilpay.co.ke` and where its **nameservers** are set | browser |

On the VPS, the layout is:

```
/var/www/sahilpay/app          ← the git repo (source code)
/var/www/sahilpay/app/server   ← the Flask backend, its venv, and its .env
/var/www/sahilpay/app/server/uploads  ← uploaded files (lease scans, APK, screenshots)
/var/www/sahilpay/client       ← the built React frontend that nginx serves
```

Three systemd services run the backend:

```
sahilpay             the web API (gunicorn)
sahilpay-celery      the background worker (invoices, reminders, penalties)
sahilpay-celerybeat  the scheduler that tells the worker when to run things
```

---

<a name="2-what-changed"></a>
## 2. What changed since your last deploy

Your last deployment commit was **`cf6a530`, 2026-07-16**. Everything below has
landed since.

### 2.1 New features (user-visible)

| Feature | What it means operationally |
|---|---|
| eTIMS / KRA compliance | Off by default per account **and** per property. Nothing happens until a landlord opts in. |
| Payment allocation engine | Suspense/review queue, pay-codes, commission rules, payout runs. |
| Help Content CMS | You author articles in the admin portal; landlords/tenants/team read them. |
| Admin 2FA (TOTP) | **Mandatory for admins.** See §2.4 — this one can lock you out. |
| Tenant bulk import | Spreadsheet → validated preview → commit. |
| Receipt layout designer | Per-landlord paper size and sections. |
| Tenant score | Nightly job, plus refresh on payment. |
| Late-payment penalties | Per property, **automation off by default**. |
| Automatic payment receipts | Per-channel, **off by default**. |
| Lease agreements | Template → tenant signs in portal → you approve → both download. Or upload a signed scan. |
| Team-member tutorials | Filtered to the modules each member holds. |
| SMS one-pool reselling | Every sender ID draws your pool at the landlord's agreed rate. |
| Cloudinary image storage | Images only; everything else stays on the VPS. |

### 2.2 Nineteen database migrations

They apply automatically with one command (§8). Full list in [Appendix A](#appendix-a).
The chain has a **single head: `u1a1b2c3d4e5`**.

### 2.3 New environment variables

| Variable | Required? | Consequence if missing |
|---|---|---|
| `FIELD_ENCRYPTION_KEY` | **YES, in production** | **The app refuses to start.** |
| `TRUST_PROXY` | Strongly recommended | Every request looks like it came from `127.0.0.1`, so the rate limiter throttles all your users as one. |
| `RATELIMIT_STORAGE_URI` | Recommended | Rate limits reset on every restart. |
| `CLOUDINARY_*` | Optional | Images stay on the VPS. Everything still works. |

### 2.4 🔴 Admin 2FA will lock you out until you enrol

The moment this deploys, **every `/api/admin/*` route refuses your admin account
until you enrol a second factor.** This is intended, not a bug.

What happens: you sign in normally, and the app sends you straight to an
enrolment screen. You scan a QR code with Google Authenticator (or Authy, or
your password manager), type the 6-digit code back, and save the backup codes it
shows you. Then the admin portal opens.

**Have your phone with an authenticator app installed before you deploy.**

### 2.5 Two new Python packages

`pyotp` (TOTP) and `cryptography` (encrypts the 2FA secret at rest). Both are
pinned in `requirements.txt` and install automatically.

### 2.6 A new scheduled job

`apply-due-penalties`, daily at 02:30. It only acts on properties where an owner
has explicitly switched penalties on, so it does nothing until you use the
feature. **You must restart `sahilpay-celerybeat`** for the schedule to be
picked up (§8 does this).

### 2.7 A new nginx config — this one is not optional

The repo's `deploy/nginx/sahilpay.conf` was written *after* your last deploy, so
your live nginx does not have it. It adds:

- **`/uploads/` location** — without it, downloading the Co-pilot APK, a signed
  lease or a tutorial screenshot returns the React app's `index.html` instead of
  the file. This is why your APK link "didn't work".
- **`client_max_body_size 100m`** — was 20 MB, which rejected every real APK.
- **Security headers** — HSTS, CSP, `frame-ancestors 'none'`, `server_tokens off`.

---

<a name="3-env-files"></a>
## 3. Your `.env` files — local and server

**They are two different files and they must NOT be copied over one another.**

The local one points at your laptop's database, runs in simulation mode, and
uses throwaway secrets. Copying it to the server would point production at a
database that does not exist and silently stop all real SMS and M-Pesa traffic.

### 3.1 On your laptop — `server/.env`

Add these three lines. Nothing else changes.

```bash
# Generate your own — see §4
FIELD_ENCRYPTION_KEY=paste-the-key-you-generate

# So pytest can find its own database (already added if you followed along)
TEST_DATABASE_URL=postgresql://sahilpay:YOURPASSWORD@localhost:5432/sahilpay_test
```

Your Cloudinary credentials are **already there and working** — I tested a real
upload against your account and deleted the test asset afterwards.

> **Note:** the test suite deliberately ignores your Cloudinary credentials, so
> running tests can never spend your free-tier credits or leave stray files in
> your account.

### 3.2 On the VPS — `/var/www/sahilpay/app/server/.env`

**Do not copy your local file up.** Instead, SSH in and *add* the new keys to
the file that is already there:

```bash
ssh sahilpay@YOUR_SERVER_IP
cd /var/www/sahilpay/app/server
cp .env .env.backup-$(date +%F)      # always take a backup first
nano .env
```

Add at the bottom:

```bash
# --- Added August 2026 -------------------------------------------------
FIELD_ENCRYPTION_KEY=paste-the-SAME-key-or-a-different-one-see-below
TRUST_PROXY=true
RATELIMIT_STORAGE_URI=redis://localhost:6379/1

# Images only. Same credentials as your laptop is fine.
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-key
CLOUDINARY_API_SECRET=your-secret
```

Save with `Ctrl+O`, `Enter`, then exit with `Ctrl+X`.

### 3.3 Should local and production share the same encryption key?

**No — use two different keys.** They encrypt different databases. If your
laptop is ever stolen or your local key leaks, production is unaffected.

The only rule: **once a key is in use on a machine, it can never change** (§4).

---

<a name="4-encryption-key"></a>
## 4. The encryption key — what it is and how to make one

### What it does

`FIELD_ENCRYPTION_KEY` encrypts your admins' two-factor secrets **at rest**.
Without it, someone who obtained a copy of your database would also obtain
working second factors for every admin — which would make 2FA decorative.

It is a **Fernet key**: 32 random bytes, base64-encoded. It is not a password
and you never type it anywhere except the `.env` file.

### Where to get one

**Do not invent one by hand.** A key that isn't valid base64 of the right length
will simply fail. Generate it:

```bash
cd /var/www/sahilpay/app/server
venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

It prints one line, something like:

```
g-9FhreU3ZHyuo6t3fks7z0VRKdfbqlZGwCPQK9QBa4=
```

Paste that after `FIELD_ENCRYPTION_KEY=` in the `.env`. The trailing `=` is part
of the key — keep it.

> **I have already generated one you may use for production:**
>
> ```
> FIELD_ENCRYPTION_KEY=g-9FhreU3ZHyuo6t3fks7z0VRKdfbqlZGwCPQK9QBa4=
> ```
>
> It is fine to use it, but generating your own with the command above is
> better practice, because that one has appeared in a chat transcript.

### 🔴 The one rule that matters

**Never change this key once admins have enrolled in 2FA.** Their stored
secrets were encrypted with it; a new key cannot decrypt them, and **every
enrolled admin is locked out permanently** — they would each have to be reset in
the database by hand.

Write it down somewhere offline. Put it in a password manager. Treat it exactly
like the key to a safe, because that is what it is.

---

<a name="5-cloudflare"></a>
## 5. Cloudflare — the complete walkthrough

### 5.1 First, what Cloudflare actually is, in one paragraph

Right now, when someone types `sahilpay.co.ke`, their computer asks the internet
"where is that?" and your registrar answers "at this VPS IP address" — so the
visitor connects **straight to your server**.

Cloudflare puts itself in the middle. Visitors connect to **Cloudflare**, and
Cloudflare connects to your server. That gives you a free CDN (your pages load
faster and your server does less work), free DDoS protection, and it **hides
your server's real IP address** so nobody can attack it directly.

### 5.2 Answering your specific questions

> **Do I do this at HostPinnacle, or on the VPS, or somewhere else?**

**Almost entirely in a browser, at two websites.** You will:

1. Create a free Cloudflare account and add your domain (at `cloudflare.com`).
2. Change your **nameservers** at your registrar — wherever you bought
   `sahilpay.co.ke`. If you bought the domain from HostPinnacle, that is where.

> **Do I have to run commands on my VPS?**

**No.** Not a single one. Cloudflare sits entirely in front of your server. The
one server-side thing that matters — reading the visitor's real IP through
Cloudflare — is handled by `TRUST_PROXY=true`, which you are adding to `.env`
anyway in §3.2.

> **Is it like when I pointed my DNS at the SahilPay server?**

Not quite, and this is the key difference:

- **Last time** you edited an **A record** — "the name `sahilpay.co.ke` points
  to IP `1.2.3.4`". You kept using your registrar's DNS.
- **This time** you change the **nameservers** — "the *entire question* of what
  `sahilpay.co.ke` means is now answered by Cloudflare, not by you". After that,
  you manage all your DNS records inside Cloudflare's dashboard rather than at
  the registrar.

### 5.3 Step by step

#### Step 1 — Create the account (3 minutes)

1. Go to **https://dash.cloudflare.com/sign-up**
2. Sign up with your email, confirm the address.
3. On the dashboard, click **Add a site**.
4. Type `sahilpay.co.ke` (no `https://`, no `www`). Click **Continue**.
5. Choose the **Free** plan. Click **Continue**.

Cloudflare now scans your existing DNS and shows you what it found. This takes
about a minute.

#### Step 2 — Check the imported records (5 minutes) 🔴 **Do not skip**

You should see at least:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| A | `sahilpay.co.ke` | your VPS IP | Proxied (orange cloud) |
| A or CNAME | `www` | your VPS IP or `sahilpay.co.ke` | Proxied (orange cloud) |

**If the A record is missing, add it manually** — click *Add record*, type `A`,
name `@`, content your VPS IP, and leave the proxy toggle **on** (orange).

**If you have email on this domain**, make sure the `MX` records came across.
Their proxy status must be **DNS only** (grey cloud) — proxying mail records
breaks email delivery.

Click **Continue**.

#### Step 3 — Set SSL mode BEFORE switching nameservers (2 minutes) 🔴 **Critical**

In the left sidebar: **SSL/TLS → Overview**. Set the mode to **Full (strict)**.

**Why this order matters:** the default is *Flexible*, which means Cloudflare
talks to your server over plain HTTP even though the visitor sees HTTPS. With
your app forcing HTTPS, that produces an infinite redirect loop and the site
becomes unreachable. You already have a valid Let's Encrypt certificate, so
*Full (strict)* is correct and safe.

#### Step 4 — Copy your two nameservers (1 minute)

Cloudflare shows two, looking like:

```
adam.ns.cloudflare.com
lucy.ns.cloudflare.com
```

They are randomly assigned — **yours will have different names**. Copy both
exactly.

#### Step 5 — Change the nameservers at your registrar (5 minutes)

Log in wherever you bought the domain (HostPinnacle, if that is where).

Find the domain management area. Look for a section called **Nameservers**,
**DNS Management**, or **Custom DNS**. It usually shows your registrar's own
nameservers, something like `ns1.hostpinnacle.co.ke`.

**Replace both** with the two Cloudflare gave you. Save.

> If you cannot find the setting, open a support ticket and say exactly:
> *"Please change the nameservers for sahilpay.co.ke to adam.ns.cloudflare.com
> and lucy.ns.cloudflare.com"* — substituting your own two.

#### Step 6 — Wait (5 minutes to 24 hours, usually under an hour)

Back on Cloudflare, click **Check nameservers now**. When it is done, the site
status changes to **Active** and you get an email.

**Your site keeps working the whole time.** Visitors resolve through either the
old or the new path; both reach your server.

#### Step 7 — 🔴 Protect the M-Pesa webhook — **do this the moment the site is Active**

**This is the single most important step in this whole document.**

Safaricom's servers post payment confirmations to your API. They are **not
browsers**. If Cloudflare decides to show them a security challenge — a CAPTCHA,
a "checking your browser" page — they cannot solve it, **payment confirmations
stop arriving, and tenants' payments stop being recorded.**

Create a rule that excludes them:

1. Left sidebar → **Security → WAF → Custom rules** → **Create rule**.
2. **Rule name:** `Never challenge payment webhooks`
3. Set the expression. Click **Edit expression** and paste:

   ```
   (starts_with(http.request.uri.path, "/api/webhooks/")) or (starts_with(http.request.uri.path, "/api/copilot/"))
   ```

4. **Action:** `Skip` → tick **All remaining custom rules**, and under
   *Additional options* also tick **Bot Fight Mode** and **Security Level**.
5. **Deploy**.

The `/api/copilot/` path is included for the same reason: your Android
forwarder app is not a browser either.

#### Step 8 — Turn on the useful protections (5 minutes)

| Where | Setting | Value |
|---|---|---|
| SSL/TLS → Edge Certificates | Always Use HTTPS | **On** |
| SSL/TLS → Edge Certificates | Automatic HTTPS Rewrites | **On** |
| SSL/TLS → Edge Certificates | Minimum TLS Version | **TLS 1.2** |
| Speed → Optimization | Brotli | **On** |
| Caching → Configuration | Caching Level | Standard |
| Security → Settings | Security Level | Medium |

**Do NOT turn on:** *Rocket Loader* or *Auto Minify for JavaScript*. Both rewrite
your JavaScript and can break a React single-page app in ways that are very hard
to diagnose.

#### Step 9 — Verify (2 minutes)

```bash
# Should show Cloudflare IPs, not your VPS IP
dig sahilpay.co.ke +short

# Should include a "cf-ray" header — proof it came through Cloudflare
curl -sI https://sahilpay.co.ke | grep -i "cf-ray\|server"

# The API must still work
curl -s https://sahilpay.co.ke/api/health
```

Then, in a browser: log in, load a report, and record a test payment.

### 5.4 Certbot renewal after Cloudflare

Your existing Let's Encrypt certificate keeps renewing normally, because renewal
uses the HTTP challenge on port 80 and Cloudflare passes that through. Confirm
once:

```bash
sudo certbot renew --dry-run
```

If it ever fails after the switch, the fix is to temporarily grey-cloud (unproxy)
the A record in Cloudflare, renew, then re-proxy.

---

<a name="6-copilot"></a>
## 6. The Co-pilot Android app — do you need to rebuild?

### Short answer: **No, you do not need to rebuild it.**

### Why I can say that

The Android app lives in a **separate repository** — the `copilot/` folder in
this repo is empty. So I cannot inspect the app's own code. What I *can* check,
and did, is **the API contract between the app and your server**, because a
rebuild is only genuinely required if that contract changed.

I compared every device-facing endpoint against the state of the code when you
built the app. These are the endpoints the app calls:

| Endpoint | What the app uses it for | Changed? |
|---|---|---|
| `POST /api/copilot/pair` | First-time pairing with an agent code | **No** |
| `POST /api/copilot/heartbeat` | Daily check-in, version report | **No** |
| `POST /api/copilot/ingest` | Forwarding an M-Pesa SMS | **No** |
| `GET /api/copilot/app/latest` | Self-update version check | **No** |
| `GET /api/copilot/app/download` | Fetching the APK | Improved, see below |

**Not one of the pairing, heartbeat or ingest endpoints changed.** Your installed
apps will keep working after this deploy without being touched.

### The one change, and why it is not breaking

`/api/copilot/app/download` used to **redirect** to the stored file. It now
**serves** the file directly, with the correct Android MIME type and a proper
filename. Any HTTP client that follows redirects — which the app already had to
do — works with both. This change makes the link *more* reliable, not less.

### Server-side Co-pilot health: verified

I ran the full Co-pilot test suite against the current code: **76 tests, all
passing**, covering SMS parsing, bank presets, pairing, the landlord inbox,
auto-allocation, and the Daraja webhooks.

I also confirmed the new **one-pool SMS billing** does not affect Co-pilot
ingestion: an incoming payment SMS is parsed and allocated exactly as before.

### When you *would* want to rebuild in Codemagic

Only for these reasons:

1. **You want to ship app changes** — new features or fixes in the app itself.
2. **You want to test the release pipeline** now that the upload actually works
   (it was broken by the 20 MB cap and the missing `/uploads/` nginx block —
   both fixed here).

If you do rebuild, remember the two rules:

- **Increment `versionCode` by 1** in every build. The app compares this integer
  to decide whether an update exists. Same number = no update offered.
- **Sign with the same keystore** as the installed version. Android refuses to
  install over an app signed with a different key, and your users would have to
  uninstall and reinstall — losing their pairing.

### Uploading a release (now that it works)

1. Admin portal → **Co-pilot → Releases**.
2. **APK file** — your built `.apk`, now accepted up to **100 MB**.
3. **Version name** — the human label, e.g. `1.4.0`. Display only.
4. **Version code** — an integer that **must increase every release**
   (`1`, `2`, `3`…). This is what triggers the update prompt.
5. **Min supported code** — leave blank normally. Setting it *forces* (rather
   than offers) an update for anyone below that number.
6. Tick **Mark as latest**, then upload.

The public link is always `https://sahilpay.co.ke/api/copilot/app/download`.
Send that one link to clients forever; it always resolves to the newest release.

---

<a name="7-ubuntu"></a>
## 7. Ubuntu — what changing your OS does and doesn't affect

You moved your **development machine** to Ubuntu. Your **VPS was already
Ubuntu**. This is good news: your laptop and your server now behave the same
way, which removes a whole class of "works on my machine" problems.

### What this changes: nothing about the deployment

Every command in this document is the same as it was. The deployment target has
not changed at all.

### What it changes for you locally

| Area | Note |
|---|---|
| Line endings | Both are Unix now. No more CRLF issues in shell scripts. |
| File paths | Both use `/`. Paths in config files behave identically. |
| Postgres | Same version family as the server — same SQL behaviour. |
| WeasyPrint (PDFs) | Needs system libraries. If PDF generation fails locally, see below. |
| File permissions | Ubuntu enforces them. If a script "won't run", it needs `chmod +x`. |

If PDF generation misbehaves on your new laptop:

```bash
sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
                    libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev
```

### One thing to check on the new laptop

Your SSH key changed with the machine. Confirm you can still reach the server
**before** you start the deploy:

```bash
ssh sahilpay@YOUR_SERVER_IP "echo connected"
```

If that fails, add your new laptop's public key (`~/.ssh/id_ed25519.pub`) to
`~/.ssh/authorized_keys` on the server — you may need to use your provider's
web console to get in the first time.

---

<a name="8-redeploy"></a>
## 8. The redeployment itself, step by step

### Step 0 — Before you begin, have these ready

- [ ] Your phone, with **Google Authenticator** (or Authy) installed
- [ ] Your `FIELD_ENCRYPTION_KEY` (§4)
- [ ] Your Cloudinary credentials
- [ ] SSH access to the VPS confirmed working
- [ ] 30 uninterrupted minutes

### Step 1 — [laptop] Final checks and commit

```bash
cd ~/Projects/sahil-pay

# Everything must pass. Expect: 485 passed
cd server && set -a && . ./.env && set +a && APP_ENV=testing venv/bin/python -m pytest tests/ -q
cd ..

# The frontend must build cleanly
cd client && npm run build && cd ..
```

Then commit and push:

```bash
git add -A
git commit -m "eTIMS/KRA, allocation engine, penalties, leases, SMS reselling, Cloudinary"
git push origin backend-set-up
```

### Step 2 — [laptop/GitHub] Merge to `main`

Production deploys from `main`.

```bash
git checkout main
git pull origin main
git merge backend-set-up
git push origin main
git checkout backend-set-up      # go back to your working branch
```

*(Or open a pull request on GitHub and merge it there — same result.)*

### Step 3 — [VPS] Back up the database 🔴 **Do not skip**

Nineteen migrations are about to run. If anything goes wrong, this file is how
you get back.

```bash
ssh sahilpay@YOUR_SERVER_IP

pg_dump -U sahilpay sahilpay > ~/sahilpay-backup-$(date +%F-%H%M).sql
ls -lh ~/sahilpay-backup-*.sql        # confirm it is not empty
```

### Step 4 — [VPS] Update the `.env`

Follow **§3.2**. Add `FIELD_ENCRYPTION_KEY`, `TRUST_PROXY`,
`RATELIMIT_STORAGE_URI` and the three `CLOUDINARY_*` values.

> The app will refuse to start without `FIELD_ENCRYPTION_KEY`, and it tells you
> exactly which variable is missing. That is a feature — it fails loudly at boot
> rather than quietly at the first 2FA enrolment.

### Step 5 — [VPS] Install the new nginx config

```bash
cd /var/www/sahilpay/app
git pull origin main                    # get the new config file first

sudo cp deploy/nginx/sahilpay.conf /etc/nginx/sites-available/sahilpay
```

🔴 **Now re-add your TLS lines.** `certbot` previously edited the live file to
add the certificate paths and the HTTP→HTTPS redirect, and you have just
overwritten that. The simplest fix is to let certbot redo it:

```bash
sudo certbot --nginx -d sahilpay.co.ke -d www.sahilpay.co.ke
sudo nginx -t                            # MUST say "syntax is ok"
sudo systemctl reload nginx
```

If `nginx -t` reports an error, **do not reload** — fix it first, or restore
your previous config from `/etc/nginx/sites-available/sahilpay.bak` if you made
one.

### Step 6 — [VPS] Run the deployment

```bash
cd /var/www/sahilpay/app
./deploy/update.sh
```

This script pulls the code, installs Python dependencies, **runs all 19
migrations**, builds the frontend, attempts the SEO prerender, creates the
uploads directory, restarts all three services, and health-checks the API.

> **On the prerender step:** it drives a headless Chromium, which may not be
> installed on your server. If it prints `SKIPPED`, **that is fine** — the site
> is fully functional; only search-engine and WhatsApp link previews are less
> rich. To enable it later:
> ```bash
> cd /var/www/sahilpay/app/client && npx playwright install --with-deps chromium
> ```

### Step 7 — [VPS] Confirm the services are healthy

```bash
sudo systemctl status sahilpay sahilpay-celery sahilpay-celerybeat --no-pager
```

All three must say **active (running)**. If the API service failed, its log
names the exact problem:

```bash
sudo journalctl -u sahilpay -n 50 --no-pager
```

### Step 8 — [VPS] Confirm the scheduler picked up the new job

```bash
sudo systemctl restart sahilpay-celerybeat
sudo journalctl -u sahilpay-celerybeat -n 30 --no-pager | grep -i penal
```

You should see `apply-due-penalties` in the schedule.

### Step 9 — [browser] Enrol your admin in 2FA 🔴 **Do this immediately**

1. Go to `https://sahilpay.co.ke/login`
2. Sign in with your admin account.
3. You will land on **"One more step before you continue"**.
4. Press **Get started**, scan the QR with your authenticator app.
5. Type the 6-digit code, press **Turn on two-factor**.
6. **Download the backup codes and store them offline.** Each works once. They
   are how you get in if you lose your phone.

Until this is done, the admin portal will not open. That is by design.

### Step 10 — [browser] Set your real SMS wholesale cost

Admin → **SMS → Pricing**. Set **platform cost per SMS** to what FluxSMS
actually charges you (**0.40**, not the 0.65 placeholder). Every margin figure
in your reports depends on this number being right.

### Step 11 — [optional] Backfill tenant scores

Only if you want scores populated immediately rather than after tonight's job:

```bash
cd /var/www/sahilpay/app/server
set -a && source .env && set +a
venv/bin/python -c "
from tasks.payment_tasks import refresh_all_tenant_scores
refresh_all_tenant_scores.delay()
print('queued')
"
```

---

<a name="9-verify"></a>
## 9. Post-deploy checklist — prove it worked

Work through these in a browser. Tick each one.

### The basics
- [ ] `https://sahilpay.co.ke` loads and shows the marketing page
- [ ] `https://sahilpay.co.ke/api/health` returns OK
- [ ] Log in as a landlord — the dashboard loads with real numbers
- [ ] Open a report — the PDF downloads and is not blank

### The new features
- [ ] **Admin 2FA** — you enrolled, and the admin portal opens
- [ ] **Penalties** — Settings → Penalties shows the property picker
- [ ] **Leases** — the Leases page loads; you can prepare one for a tenant
- [ ] **Guides** — the sidebar has *Guides*, and articles open
- [ ] **Review queue** and **Payout runs** load
- [ ] **eTIMS** links are *absent* (correct — nobody has opted in yet)

### The things that were broken
- [ ] **APK upload** — Admin → Co-pilot → Releases; upload a real APK (>20 MB)
- [ ] **APK download** — open `https://sahilpay.co.ke/api/copilot/app/download`
      in a browser. It must download a **file**, not show a web page.
- [ ] **Images** — upload a logo in Settings → General. It should save, and the
      URL should begin `https://res.cloudinary.com/`

### Money
- [ ] Record a payment manually — the tenant balance moves correctly
- [ ] Tick **Send receipt** — it arrives on the chosen channels
- [ ] Admin → SMS → the per-landlord table lists **every** landlord with balances

### On a phone
- [ ] Open the site on your actual phone. **No page should scroll sideways.**
      (I verified 130 pages at 360px and 768px, but check yours.)

---

<a name="10-rollback"></a>
## 10. If something goes wrong

### The API will not start

```bash
sudo journalctl -u sahilpay -n 80 --no-pager
```

The most likely cause is a missing environment variable — the app names it
explicitly at boot. Add it to `.env` and `sudo systemctl restart sahilpay`.

### A migration failed halfway

```bash
cd /var/www/sahilpay/app/server
set -a && source .env && set +a
venv/bin/flask db current        # where are you?
venv/bin/flask db heads          # where should you be? (u1a1b2c3d4e5)
venv/bin/flask db upgrade        # safe to re-run; it resumes
```

If it still fails, restore the backup from Step 3:

```bash
psql -U sahilpay -d sahilpay < ~/sahilpay-backup-YYYY-MM-DD-HHMM.sql
```

### The frontend looks broken or stale

The previous build is kept:

```bash
sudo rm -rf /var/www/sahilpay/client
sudo mv /var/www/sahilpay/client.bak /var/www/sahilpay/client
sudo systemctl reload nginx
```

Also do a hard refresh (`Ctrl+Shift+R`) — and if you have Cloudflare on,
**Caching → Purge Everything**.

### Full rollback to the previous release

```bash
cd /var/www/sahilpay/app
git log --oneline -5             # find the previous commit
git checkout <previous-commit-hash>
./deploy/update.sh
```

> ⚠️ **Migrations do not roll back automatically.** If you must go back after
> migrations have run, restore the database backup as well. This is why Step 3
> exists.

### Payments stopped arriving after Cloudflare

You skipped §5.7. Create the WAF skip rule for `/api/webhooks/` and
`/api/copilot/` immediately, then ask Safaricom to re-send the missed
confirmations.

---

<a name="appendix-a"></a>
## Appendix A — every migration being applied

Nineteen, in dependency order. They run automatically; this list is for your
records and for diagnosing a failure.

| # | Revision | What it adds |
|---|---|---|
| 1 | `70d7e5498282` | M-Pesa production integration |
| 2 | `a4b5c6d7e8f9` | FluxSMS provider rename |
| 3 | `b3c4d5e6f7a8` | Co-pilot: retain unmatched messages |
| 4 | `c1a2b3d4e5f6` | Co-pilot: bank parser presets |
| 5 | `c2b3d4e5f6a7` | Per-landlord SMS credit ledger |
| 6 | `fd0e10981cd2` | Notifications: tenant recipients |
| 7 | `5435e6002fe8` | SMS credit ranges (word→credit tiers) |
| 8 | `d7e8f9a0b1c2` | Utility reading subcategory |
| 9 | `p1a1b2c3d4e5` | Team role presets + owner payouts |
| 10 | `p2b1c2d3e4f5` | Per-property commission + gross basis |
| 11 | `p4c1d2e3f4a5` | Tenant payment score |
| 12 | `p6d1e2f3a4b5` | Fixed monthly price + welcome message |
| 13 | `p5e1f2a3b4c5` | Link multi-unit tenants to one person |
| 14 | `p8f1a2b3c4d5` | Two-factor auth + receipt layout |
| 15 | `q1a1b2c3d4e5` | eTIMS/KRA compliance + Help CMS |
| 16 | `r1a1b2c3d4e5` | Payment allocation engine |
| 17 | `s1a1b2c3d4e5` | Penalty policies, tiers, charge ledger |
| 18 | `t1a1b2c3d4e5` | Auto-receipt channels |
| 19 | `u1a1b2c3d4e5` | Lease agreements |

**Single head: `u1a1b2c3d4e5`.** After deploying, `flask db current` must show
exactly that.

Migration 17 back-fills any `rent_payment_penalty` you had configured into the
new penalty policies, **switched off** — enabling automatic fines is a decision
with financial consequences for tenants, and a migration does not make it on
your behalf.

---

<a name="appendix-b"></a>
## Appendix B — full production `.env` template

The authoritative copy is `deploy/server.env.production.example` in the repo.
Everything marked **REQUIRED** must have a value or the app will not start.

```bash
APP_ENV=production                                  # REQUIRED

SECRET_KEY=                                         # REQUIRED, long random
JWT_SECRET_KEY=                                     # REQUIRED, long random
FIELD_ENCRYPTION_KEY=                               # REQUIRED — see §4

DATABASE_URL=postgresql://sahilpay:PASS@localhost:5432/sahilpay   # REQUIRED
REDIS_URL=redis://localhost:6379/0                  # REQUIRED
RATELIMIT_STORAGE_URI=redis://localhost:6379/1

FRONTEND_URL=https://sahilpay.co.ke
CORS_ORIGINS=https://sahilpay.co.ke,https://www.sahilpay.co.ke
TRUST_PROXY=true                                    # behind nginx + Cloudflare

SENDGRID_API_KEY=                                   # REQUIRED for email
MAIL_DEFAULT_SENDER=noreply@sahilpay.co.ke
MAIL_DEFAULT_SENDER_NAME=Sahil Pay
ENFORCE_EMAIL_VERIFICATION=true

COMMS_SIMULATION_MODE=false                         # false = really send SMS
FLUXSMS_BASE_URL=https://api.fluxsms.co.ke
FLUXSMS_API_KEY=
FLUXSMS_SENDER_ID=SAHILPAY

DARAJA_BASE_URL=https://api.safaricom.co.ke
# Keep true until the Daraja production passkey + initiator credentials are
# in hand — true lets the app boot without PLATFORM_DARAJA_PASSKEY.
MPESA_SIMULATION_MODE=true
PLATFORM_DARAJA_CONSUMER_KEY=
PLATFORM_DARAJA_CONSUMER_SECRET=
PLATFORM_DARAJA_SHORTCODE=
PLATFORM_DARAJA_PASSKEY=
PLATFORM_DARAJA_STK_CALLBACK_URL=https://sahilpay.co.ke/api/webhooks/daraja/billing-callback
PLATFORM_DARAJA_INITIATOR_NAME=
PLATFORM_DARAJA_SECURITY_CREDENTIAL=

# Images only — everything else stays on this server
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
```

To generate the three secrets:

```bash
cd /var/www/sahilpay/app/server
venv/bin/python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
venv/bin/python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(48))"
venv/bin/python -c "from cryptography.fernet import Fernet; print('FIELD_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

> ⚠️ Changing `SECRET_KEY` or `JWT_SECRET_KEY` logs **everyone** out immediately
> (all tokens become invalid). Changing `FIELD_ENCRYPTION_KEY` **permanently
> locks out every 2FA-enrolled admin**. Set them once and keep them.

---

## Quick reference — the whole deploy in ten lines

For when you have done this once and just need the commands:

```bash
# laptop
cd ~/Projects/sahil-pay && git add -A && git commit -m "release" && git push origin backend-set-up
git checkout main && git merge backend-set-up && git push origin main && git checkout backend-set-up

# VPS
ssh sahilpay@YOUR_SERVER_IP
pg_dump -U sahilpay sahilpay > ~/sahilpay-backup-$(date +%F-%H%M).sql
nano /var/www/sahilpay/app/server/.env          # add FIELD_ENCRYPTION_KEY etc.
cd /var/www/sahilpay/app && git pull origin main
sudo cp deploy/nginx/sahilpay.conf /etc/nginx/sites-available/sahilpay
sudo certbot --nginx -d sahilpay.co.ke -d www.sahilpay.co.ke && sudo nginx -t && sudo systemctl reload nginx
./deploy/update.sh
sudo systemctl status sahilpay sahilpay-celery sahilpay-celerybeat --no-pager
# then: log in, enrol 2FA, set the SMS platform cost to 0.40
```
