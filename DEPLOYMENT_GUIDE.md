# SAHIL PAY — PRODUCTION DEPLOYMENT GUIDE (sahilpay.co.ke on Novahost)

**Goal:** `https://sahilpay.co.ke` live, searchable, and taking client sign-ups — frontend,
backend, and database all deployed and linked.
**Host:** [Novahost](https://novahost.co.ke/) (domain + VPS + email).
**Everything referenced here already exists in the repo** under `deploy/` — nginx config,
systemd services, production env templates, and a one-command redeploy script.

---

## 0. The architecture decision (read this first)

**Q: Can I host the frontend in one place and the backend in another?**
Technically yes — the frontend is a static Vite build and the backend is a plain API, so they
are fully decoupled. **But in your case the backend's public address is already fixed:** your
M-Pesa C2B webhook URLs were registered with Safaricom on **2026-07-15** against:

- `https://sahilpay.co.ke/api/webhooks/daraja/c2b/validation`
- `https://sahilpay.co.ke/api/webhooks/daraja/c2b/confirmation`

Safaricom does not let you casually re-register these. So whatever you do, **the Flask API
must answer at `sahilpay.co.ke/api/...`** — you cannot put the backend on
`api.sahilpay.co.ke` or another domain without redoing the C2B registration.

**The deployment shape (recommended and assumed by every config in `deploy/`):**

```
                    sahilpay.co.ke  (one Novahost VPS)
                ┌────────────────────────────────────────┐
   Browser ───► │ nginx :443 (SSL)                       │
                │   /        → /var/www/sahilpay/client  │  ← static React build
                │   /api/    → gunicorn 127.0.0.1:8000   │  ← Flask API
   Safaricom ─► │   /api/webhooks/daraja/*  (same proxy) │
                └───────────────┬────────────────────────┘
                                │
                 PostgreSQL ◄───┼───► Redis ◄── Celery worker + Beat
                 (localhost)         (localhost)   (background jobs)
```

The frontend and backend **are** separate deployments here — separate build steps, separate
directories, zero shared code at runtime — they just sit behind one nginx on one machine.
That is the correct way to get "separate hosting" while honouring your registered webhook
URLs. (A true two-host split is described in Appendix A, but don't start there.)

**Why a VPS and not Novahost shared/cPanel hosting:** this stack needs long-running
processes (gunicorn, Celery worker, Celery Beat), Redis, PostgreSQL, and WeasyPrint's native
libraries (Pango/HarfBuzz). Shared cPanel hosting provides none of those reliably — it's
built for PHP/WordPress and MySQL. The frontend *alone* could live on shared hosting, but the
backend cannot, and the backend must own `sahilpay.co.ke/api`. So: **one VPS.**

---

## 1. What to buy at Novahost (Day 0)

Go to <https://novahost.co.ke/> and get:

1. **Domain: `sahilpay.co.ke`** — register it (KeNIC `.co.ke` domains are cheap, ~KES
   700–1,000/yr). If you already own it, skip.
2. **A VPS**, not a shared-hosting plan. Ask Novahost support for exactly this:
   - KVM VPS with **full root SSH access**
   - **Ubuntu 24.04 LTS** (or 22.04) image
   - **Minimum 2 vCPU / 4 GB RAM / 50 GB SSD** (2 GB RAM works to start, but Postgres +
     Redis + Celery + gunicorn + WeasyPrint is comfortable at 4 GB)
   - A **public IPv4 address**
   > If Novahost has no VPS product that fits, keep the **domain + DNS + email** at Novahost
   > and buy the VPS elsewhere (Contabo/Hetzner/DigitalOcean ~$5–8/mo). Nothing else in this
   > guide changes.
3. **Email hosting for `info@sahilpay.co.ke`** — Novahost's basic email hosting on the same
   domain, so the address on your letterhead actually receives mail. (Outbound *transactional*
   mail is SendGrid — §9 — these are separate things.)

**Credentials to have ready before Day 1:** SendGrid API key, Cloudinary account,
an S3-compatible bucket (Cloudflare R2 free tier is fine), Africa's Talking SMS account,
Daraja production consumer key/secret (you have these; passkey still pending — simulation
mode covers that, §8).

---

## 2. Point DNS at the VPS (Day 0, propagates while you work)

In Novahost's DNS panel for `sahilpay.co.ke`, create:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | `<VPS public IP>` | 3600 |
| A | `www` | `<VPS public IP>` | 3600 |

(Leave the MX records as Novahost sets them for your `info@` mailbox. SendGrid CNAMEs come
in §9.) Verify propagation before §7: `dig +short sahilpay.co.ke` must return the VPS IP.

---

## 3. Bootstrap the VPS (Day 1, ~30 min)

SSH in as root (`ssh root@<VPS-IP>`) and run:

```bash
# a) system user + firewall
adduser --disabled-password --gecos "" sahilpay
usermod -aG sudo sahilpay
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable

# b) all system packages in one go
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-dev build-essential \
    postgresql postgresql-contrib redis-server nginx git curl \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev \
    fonts-dejavu-core certbot python3-certbot-nginx

# c) Node.js 20 (for building the frontend on the server)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# d) redis + postgres run on boot
systemctl enable --now redis-server postgresql
```

## 4. Database (5 min)

```bash
sudo -u postgres psql <<'SQL'
CREATE USER sahilpay WITH PASSWORD 'CHOOSE_A_STRONG_DB_PASSWORD';
CREATE DATABASE sahilpay OWNER sahilpay;
SQL
```

Postgres only listens on localhost by default — leave it that way (no firewall hole needed).

## 5. Backend (Day 1, ~20 min)

VPS directory layout (every config in `deploy/` assumes exactly this):

```
/var/www/sahilpay/app     ← the git repo (source, venv, .env)
/var/www/sahilpay/client  ← live frontend build, served by nginx (created in §6)
```

```bash
# as the sahilpay user
su - sahilpay
sudo mkdir -p /var/www/sahilpay && sudo chown sahilpay:sahilpay /var/www/sahilpay

# a) get the code (push your repo to GitHub first if you haven't; use a
#    deploy key or HTTPS token for a private repo)
git clone <YOUR_REPO_URL> /var/www/sahilpay/app
cd /var/www/sahilpay/app

# b) python env
cd server
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# c) environment — the template has every REQUIRED var annotated
cp ../deploy/server.env.production.example .env
nano .env        # fill in: secrets, DB password from §4, SendGrid, Cloudinary,
                 # S3/R2, Africa's Talking, Daraja keys. See the file's comments.
chmod 600 .env

# d) create the schema
set -a && source .env && set +a
venv/bin/flask db upgrade

# e) seed the platform admin + packages (same as local setup)
venv/bin/python seed.py
```

Smoke-test it before wiring systemd:

```bash
venv/bin/gunicorn "app:create_app()" -b 127.0.0.1:8000 &
curl -s http://127.0.0.1:8000/api/health    # → {"status": "ok", ...}
kill %1
```

Now install the services (files are in `deploy/systemd/`, already written for these paths):

```bash
sudo cp /var/www/sahilpay/app/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sahilpay sahilpay-celery sahilpay-celerybeat
systemctl status sahilpay --no-pager     # all three should be "active (running)"
```

## 6. Frontend (Day 1, ~10 min)

`client/.env.production` is already in the repo pointing at
`https://sahilpay.co.ke/api`. Just add your Cloudinary values to it, then:

```bash
cd /var/www/sahilpay/app/client
nano .env.production        # fill VITE_CLOUDINARY_* (must match server .env)
npm ci
npm run build               # outputs dist/
cp -r dist /var/www/sahilpay/client    # publish → nginx web root
```

(Every later deploy, `deploy/update.sh` refreshes `/var/www/sahilpay/client` for you.)

## 7. nginx + HTTPS (Day 1, ~10 min) — **HTTPS is mandatory: Daraja won't call plain-HTTP webhooks**

```bash
sudo cp /var/www/sahilpay/app/deploy/nginx/sahilpay.conf /etc/nginx/sites-available/sahilpay
sudo ln -s /etc/nginx/sites-available/sahilpay /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# free Let's Encrypt cert + automatic HTTP→HTTPS redirect + auto-renewal
sudo certbot --nginx -d sahilpay.co.ke -d www.sahilpay.co.ke \
     --redirect -m info@sahilpay.co.ke --agree-tos
```

**Go-live check, in order:**

```bash
curl -s https://sahilpay.co.ke/api/health          # {"status":"ok"}
```
Then in a browser: `https://sahilpay.co.ke` loads the public site → log in with your admin
account → open a report → download a PDF. If all four work, you are live.

## 8. M-Pesa production switch

Your C2B URLs are **already registered** (2026-07-15) — the moment §7 completes, Safaricom
can reach them. What remains:

1. In `/var/www/sahilpay/app/server/.env`: `DARAJA_BASE_URL=https://api.safaricom.co.ke` and the
   production consumer key/secret/shortcode (already in the template).
2. Keep `MPESA_SIMULATION_MODE=true` **until the production passkey and initiator
   credentials arrive** (per MPESA_INTEGRATION_SPEC.md that's the outstanding item). When
   they arrive: set `PLATFORM_DARAJA_PASSKEY`, flip `MPESA_SIMULATION_MODE=false`,
   `sudo systemctl restart sahilpay sahilpay-celery`.
3. Verify with a real KES 1 paybill payment; watch it land:
   `sudo journalctl -u sahilpay -f | grep -i daraja`
4. The reconciliation task (`server/tasks/mpesa_reconciliation_tasks.py`) runs via Beat —
   confirm in `sudo journalctl -u sahilpay-celerybeat -f`.

## 9. Email deliverability (info@sahilpay.co.ke)

1. **Receiving:** create the `info@sahilpay.co.ke` mailbox in Novahost's email hosting panel.
2. **Sending (SendGrid):** SendGrid → Settings → Sender Authentication → **Authenticate
   Domain** → `sahilpay.co.ke`. SendGrid gives you 3 CNAME records — add them in Novahost's
   DNS panel. Once verified, set `MAIL_DEFAULT_SENDER=info@sahilpay.co.ke` (already in the
   env template) and OTP/verification emails stop landing in spam.
3. Test: register a fresh landlord account and confirm the verification email arrives.

## 10. Being findable (SEO, so "sahilpay" searches find you)

1. The public pages already have SEO content built in (Phase-2 SEO work). Verify
   `https://sahilpay.co.ke` renders the marketing home for logged-out users.
2. [Google Search Console](https://search.google.com/search-console) → add property
   `sahilpay.co.ke` → verify via DNS TXT record (Novahost DNS panel) → **Request indexing**
   for the homepage. New `.co.ke` domains typically appear in search within a few days.
3. Optional but worth 10 minutes: create a free Google Business Profile with the
   phone number `0114 129 809` and the website link.

## 11. Backups & upkeep (do this before you have real client data)

```bash
# nightly DB dump, kept 14 days  (as the sahilpay user: crontab -e)
0 2 * * * pg_dump -U sahilpay sahilpay | gzip > /var/backups/sahilpay/db-$(date +\%F).sql.gz
5 2 * * * find /var/backups/sahilpay -name 'db-*.gz' -mtime +14 -delete
```
```bash
sudo mkdir -p /var/backups/sahilpay && sudo chown sahilpay /var/backups/sahilpay
```
- Point a free [UptimeRobot](https://uptimerobot.com) monitor at
  `https://sahilpay.co.ke/api/health` (alerts to info@sahilpay.co.ke).
- Certbot renews SSL automatically (`systemctl list-timers | grep certbot` to confirm).
- The in-app backup service (platform-features phase) covers tenant-facing exports; the
  cron dump above is your disaster-recovery layer.

## 12. Every future deployment = one command

```bash
ssh sahilpay@<VPS-IP>
cd /var/www/sahilpay/app && ./deploy/update.sh
```
(pulls latest code → installs deps → runs migrations → rebuilds frontend → restarts
services → health-checks.)

---

## Appendix A — true two-host split (not recommended now)

If you ever *must* host the frontend elsewhere (e.g. Novahost shared hosting or Cloudflare
Pages) while the API stays on the VPS:

1. Frontend static files go to host A, served at `sahilpay.co.ke`.
2. The API **still must be reachable at `sahilpay.co.ke/api`** (registered M-Pesa URLs), so
   you'd put Cloudflare (free plan) in front of the domain and add an Origin Rule/Worker
   routing `sahilpay.co.ke/api/*` to the VPS while `/*` goes to host A.
3. Costs you: an extra moving part (Cloudflare routing), CORS stays same-origin so no
   changes there.

It buys you nothing today — the VPS serves static files effortlessly — which is why the
main guide keeps both on one box.

## Appendix B — quick triage

| Symptom | Look at |
|---|---|
| 502 on /api | `sudo journalctl -u sahilpay -n 50` (gunicorn down / .env invalid — ProductionConfig refuses to boot when a REQUIRED var is missing and prints which one) |
| Blank page on / | nginx `root` path vs. where you copied `dist` (§6 note) |
| Emails not arriving | SendGrid domain auth pending (§9), or `ENFORCE_EMAIL_VERIFICATION` while sender unverified |
| M-Pesa payment invisible | `journalctl -u sahilpay -f` during a test payment; confirm HTTPS works from outside: `curl -s https://sahilpay.co.ke/api/health` from your laptop |
| Invoices not generating on the 1st | `sudo systemctl status sahilpay-celerybeat sahilpay-celery` |
