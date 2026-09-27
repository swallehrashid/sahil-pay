# Sahil Pay — Redeploy: September 2026 (nine-item release)

Leases in the tenant portal, installment billing with an account lock, receipts
that download, confirmation-only payments, M-Pesa hardening, grouped navigation,
the Co-pilot download page, landlord-branded emails and ruled tables.

**Do §1 and §2 before running `update.sh`.** §3 (nginx) is manual — `update.sh`
does not install the nginx config, which is why the Co-pilot upload kept failing.

---

## 0. What is in this release

| # | Change | VPS action? |
|---|---|---|
| 1 | Receipts, statements, reports as ruled tables (PDF and on screen) | No |
| 2 | Billing: pay any amount; running balance; lock after 5 days' grace; admin exemption | Migration (automatic) + **review balances, §5** |
| 3 | Billing receipt downloads (streamed from the API) and is fully Sahil-branded | No |
| 4 | A payment is only "paid" once M-Pesa confirms it — simulation included | No |
| 5 | Grouped landlord/team navigation, "+ New", phone bottom bar, grouped Settings | No |
| 6 | M-Pesa hardening (real caller IP, Safaricom IP list, STK status cross-check) | **Env, §1** |
| 7 | Co-pilot download page at `/copilot`, APK shipped with the site | **nginx, §3** |
| 8 | Emails from a landlord's account carry their logo, colours, letterhead, contacts | No |
| 9 | Leases: tenant Leases page, sign in portal or on paper, review, both download | No |

New migration (runs in `update.sh`):

```
10aaeeb9b8d4 -> ah1b2c3d4e5f   brand contacts, subscription balance ledger, lease documents and scans
```

New Python packages (installed by `update.sh` from `requirements.txt`): `pypdf`, `nh3`.

---

## 1. Environment — `server/.env` on the VPS

Add or confirm:

```
TRUST_PROXY=true
TRUSTED_PROXY_HOPS=2          # Cloudflare + nginx
DARAJA_ALLOWED_IPS=           # empty = Safaricom's published callback IPs only
SUBSCRIPTION_GRACE_DAYS=5
```

Going live with M-Pesa in this deploy? Also set, after §4 of
[MPESA_GO_LIVE.md](MPESA_GO_LIVE.md):

```
MPESA_SIMULATION_MODE=false
DARAJA_BASE_URL=https://api.safaricom.co.ke
```

## 2. Back up the database

```bash
pg_dump "$DATABASE_URL" -Fc -f ~/sahilpay-before-nine-items-$(date +%F).dump
```

## 3. nginx (manual — `update.sh` does not do this)

```bash
sudo cp /var/www/sahilpay/app/deploy/nginx/sahilpay.conf /etc/nginx/sites-available/sahilpay.conf
sudo nginx -t && sudo systemctl reload nginx
```

What changed:

- `location /downloads/` serves the bundled Co-pilot APK as
  `application/vnd.android.package-archive` with its length (the page's progress bar needs it).
- `proxy_request_buffering on` for `/api/`. With it **off**, a 20 MB APK upload from a slow
  connection streamed into a gunicorn worker for minutes and was killed at 120 s — the
  "Co-pilot release upload doesn't work" bug. Verified by probing production: a 22 MB body
  was cut off at ~62 s.

## 4. Deploy

```bash
cd /var/www/sahilpay/app && ./deploy/update.sh
sudo systemctl restart sahilpay-celerybeat   # picks up the new daily billing job
```

## 5. Check subscription balances (important)

`amount_due` is now a **running balance**. The migration:

- sets trial accounts to 0;
- resets to 0 any account whose "amount due" was just next month's price on a date not yet reached;
- leaves every other balance as it was, and **locks nobody** — the grace clock for an existing
  balance starts the first night after deploy, so the earliest anyone can lock is 5 days later.

Before those 5 days are up, open **Admin → Landlords → Billing** for each paying client and
confirm the balance is right. Where a client owes but you have agreed to wait, set
**Keep open until** with a reason.

## 6. Verify (10 minutes)

1. `https://sahilpay.co.ke/copilot` — press Download on an Android phone; progress shows; file installs.
2. `https://sahilpay.co.ke/api/copilot/app/download` — redirects to the APK.
3. Landlord → Leases → **Send a lease** to a test tenant. Tenant signs in on a phone: dashboard shows
   "You have a lease to sign", **Leases** tab has a badge. Sign on paper (upload two photos). Landlord →
   Needs review → Approve. Both download the final copy.
4. Settings → Billing → a confirmed payment → **Download** receipt opens a PDF.
5. `cd server && venv/bin/python scripts/mpesa_preflight.py` → `READY`.

## 7. Rollback

```bash
cd /var/www/sahilpay/app && git checkout <previous-tag> && ./deploy/update.sh
cd server && venv/bin/flask db downgrade 10aaeeb9b8d4
```

The downgrade drops the new columns; restore the §2 dump if lease scans or claimed payments
recorded after deploy must be kept.
