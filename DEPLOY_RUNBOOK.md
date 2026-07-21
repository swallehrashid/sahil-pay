# SahilPay — Go-Live Runbook (HostPinnacle VPS, Ubuntu 24.04)

> Follow top to bottom. Commands are run **on the VPS over SSH** unless marked
> **[registrar]** (your domain DNS panel) or **[laptop]**. Target: `https://sahilpay.co.ke`
> live and taking sign-ups. The repo is already prepped — all config lives in `deploy/`.
>
> **Layout on the VPS:** repo at `/var/www/sahilpay/app`, live frontend at
> `/var/www/sahilpay/client`, backend at `/var/www/sahilpay/app/server`.

---

## What I already did in the repo (so you don't have to)

- ✅ `wsgi.py` added; gunicorn target `app:create_app()` verified booting in production mode.
- ✅ Production config no longer requires Cloudinary/AWS — file uploads fall back to local disk (`server/uploads/`).
- ✅ Email sender = `noreply@sahilpay.co.ke`; contact address users see = `hello@sahilpay.co.ke`. **Real SendGrid send tested and delivered.**
- ✅ `deploy/` has correct systemd units (gunicorn + celery worker + celery beat), nginx config, `update.sh`, and `server.env.production.example`.
- ✅ Migrations verified to apply cleanly on a fresh Postgres DB. All 103 tests pass.

**You still need to `git commit` + `git push` these changes** before cloning on the VPS (see step 0).

---

## 0. [laptop] Commit & push the deploy-ready code

```bash
cd ~/projects/sahil-pay
git add -A
git commit -m "Production deploy prep: wsgi, email addresses, storage fallback, Client Support rename"
git push origin backend-set-up
```

Have ready: a **GitHub Personal Access Token** (for cloning the private repo), your
**production secrets** (M-Pesa, FluxSMS keys), and the **fresh SendGrid production key**.

---

## 1. [registrar] DNS — point the domain at the VPS

In your domain DNS panel for `sahilpay.co.ke` (you said DNS is already pointed —
just confirm these two A records exist and match your VPS IP):

| Type | Host | Value | TTL |
|------|------|-------|-----|
| A | `@` | `<YOUR_VPS_IP>` | 300 |
| A | `www` | `<YOUR_VPS_IP>` | 300 |

Check from your laptop: `dig +short sahilpay.co.ke` should return the VPS IP.
**Wait until it does before step 8 (SSL).**

---

## 2. Server base setup (SSH in as root)

```bash
apt update && apt upgrade -y

# Create a non-root deploy user that owns the app
adduser --disabled-password --gecos "" sahilpay
usermod -aG sudo sahilpay
# add your laptop SSH key so you can log in as sahilpay
mkdir -p /home/sahilpay/.ssh && cp ~/.ssh/authorized_keys /home/sahilpay/.ssh/ 2>/dev/null || true
chown -R sahilpay:sahilpay /home/sahilpay/.ssh && chmod 700 /home/sahilpay/.ssh

# Firewall
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw --force enable
```

---

## 3. Install packages

```bash
apt install -y nginx postgresql postgresql-contrib redis-server \
  python3-venv python3-pip python3-dev build-essential git \
  certbot python3-certbot-nginx libpq-dev

# WeasyPrint system libraries (PDF generation) — required
apt install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
  libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info fonts-dejavu

# Node 20 (to build the React frontend on the server)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt install -y nodejs

# Confirm services are up
systemctl enable --now redis-server postgresql
redis-cli ping     # -> PONG
```

---

## 4. PostgreSQL database

```bash
sudo -u postgres psql -c "CREATE USER sahilpay WITH PASSWORD 'CHOOSE_A_STRONG_DB_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE sahilpay OWNER sahilpay;"
```

Keep that DB password — it goes in `.env` next.

---

## 5. Clone the repo & set up the backend (as the sahilpay user)

```bash
su - sahilpay
sudo mkdir -p /var/www/sahilpay && sudo chown -R sahilpay:sahilpay /var/www/sahilpay

git clone https://<GITHUB_PAT>@github.com/swallehrashid/sahil-pay.git /var/www/sahilpay/app
cd /var/www/sahilpay/app && git checkout backend-set-up

# Python venv + dependencies
cd server
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt gunicorn
```

### Create the production `.env`

```bash
cp /var/www/sahilpay/app/deploy/server.env.production.example \
   /var/www/sahilpay/app/server/.env
nano /var/www/sahilpay/app/server/.env
```

Fill in every value. **Minimum to boot:** `SECRET_KEY`, `JWT_SECRET_KEY`
(generate each with `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`),
`DATABASE_URL` (with the step-4 password), `REDIS_URL`, `SENDGRID_API_KEY`
(your fresh production key), `PLATFORM_DARAJA_CONSUMER_KEY`. Set
**`COMMS_SIMULATION_MODE=false`** so real OTPs/emails send. Leave the M-Pesa
block `MPESA_SIMULATION_MODE=true` until you have the Daraja production passkey.

### Run database migrations

```bash
cd /var/www/sahilpay/app/server
set -a && source .env && set +a
venv/bin/flask db upgrade      # creates all 58 tables on the fresh DB
```

Optional — seed an initial admin/demo data: `venv/bin/python seed.py`
(skip if you want a completely empty production DB; you can create the admin manually).

---

## 6. Build the frontend

```bash
cd /var/www/sahilpay/app/client
# .env.production already points VITE_API_BASE_URL at https://sahilpay.co.ke/api
npm ci
npm run build
cp -r dist /var/www/sahilpay/client
```

---

## 7. Install the services & nginx (as root — `exit` back to root, or use sudo)

```bash
# systemd units (gunicorn API + celery worker + celery beat scheduler)
sudo cp /var/www/sahilpay/app/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sahilpay sahilpay-celery sahilpay-celerybeat
sudo systemctl status sahilpay --no-pager     # should be active (running)

# nginx site
sudo cp /var/www/sahilpay/app/deploy/nginx/sahilpay.conf /etc/nginx/sites-available/sahilpay
sudo ln -sf /etc/nginx/sites-available/sahilpay /etc/nginx/sites-enabled/sahilpay
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Quick local check (before SSL): `curl -s http://127.0.0.1:8000/api/health` → `{"status":"ok"...}`.

---

## 8. SSL (only after `dig +short sahilpay.co.ke` returns the VPS IP)

```bash
sudo certbot --nginx -d sahilpay.co.ke -d www.sahilpay.co.ke
```

Choose "redirect HTTP→HTTPS" when asked. Certbot rewrites the nginx file and sets
up auto-renewal. **HTTPS is mandatory** — Safaricom won't call HTTP callbacks.

---

## 9. Launch verification

1. `https://sahilpay.co.ke` loads the app with a green padlock.
2. `curl -s https://sahilpay.co.ke/api/health` → `{"status":"ok","env":"production"}`.
3. Register a landlord → the **verification email arrives from `noreply@sahilpay.co.ke`**.
4. Log in to each portal (Landlord, Team Member, Tenant via OTP, Admin).
5. Logs are clean: `sudo journalctl -u sahilpay -f` (no 500s), `sudo journalctl -u sahilpay-celery -f` (worker connected to Redis).
6. Generate one PDF (a tenant statement/receipt) to confirm WeasyPrint works.
7. `sudo reboot`, then confirm all three services come back: `systemctl status sahilpay sahilpay-celery sahilpay-celerybeat`.

---

## 10. M-Pesa go-live (when you have the Daraja production passkey)

In `.env`: set `MPESA_SIMULATION_MODE=false` and fill `PLATFORM_DARAJA_PASSKEY`,
`PLATFORM_DARAJA_SHORTCODE`, `PLATFORM_DARAJA_CONSUMER_SECRET`, and the B2C
credentials. Then `sudo systemctl restart sahilpay sahilpay-celery`. The C2B
callback URLs are **already registered** with Safaricom against
`https://sahilpay.co.ke/api/...` — do not re-register. Test with a small real
payment and watch `journalctl -u sahilpay -f` for the callback hit.

---

## 11. Post-launch (within 24h — not blocking go-live)

- **Backups.** The VPS is a single point of failure. Nightly cron:
  ```bash
  # DB
  0 2 * * * pg_dump -U sahilpay sahilpay | gzip > /var/backups/sahilpay-$(date +\%F).sql.gz
  # Uploaded files (local-disk storage — documents, receipts)
  0 3 * * * tar czf /var/backups/uploads-$(date +\%F).tar.gz -C /var/www/sahilpay/app/server uploads
  ```
  Copy these off the server (rsync/rclone to object storage or another host).
- **Fail2ban** for SSH: `apt install -y fail2ban`.
- **🔑 Rotate the SendGrid API key.** The key you pasted in chat should be replaced:
  create a fresh one in SendGrid, put it in the VPS `.env`, restart `sahilpay`, then
  delete the old key in SendGrid.
- Consider Sentry (free tier) for error tracking.

---

## Redeploying later (after any code change)

```bash
# on the VPS, as sahilpay
cd /var/www/sahilpay/app && ./deploy/update.sh
```
It pulls, installs deps, runs migrations, rebuilds the frontend, restarts all
services, and health-checks. (Needs `sudo` rights for the restart — already set in step 2.)

---

## If something breaks

| Symptom | Check |
|---|---|
| API 502 in browser | `sudo journalctl -u sahilpay -n 50` — usually a missing `.env` var (it names which one) |
| App won't boot | It logs the exact missing REQUIRED env var. Fill it, `sudo systemctl restart sahilpay` |
| Emails not arriving | `COMMS_SIMULATION_MODE` must be `false`; check `journalctl -u sahilpay-celery` |
| Scheduled invoices not running | `systemctl status sahilpay-celerybeat` — exactly one beat instance must be active |
| Callback from Safaricom fails | Must be HTTPS (step 8 done) and path under `/api/webhooks/daraja/` |
