# Redeploy Runbook — Co-Pilot Landlord Inbox

Server: Novahost VPS, app at `/var/www/sahilpay/app`, services `sahilpay`,
`sahilpay-celery`, `sahilpay-celerybeat`.

This change is **Python + React + one migration**. No new system packages, no nginx
change, no M-Pesa URL re-registration (those stay registered — do not touch them).

---

## Phase 0 — the zero-deploy fix (do this FIRST, tonight)

The 5,000 test payment can be fixed with **no code at all**. Do this before deploying
anything, so you know the parser works independently of the new UI.

1. Admin portal → Co-Pilot → Templates.
2. Open the template you created for `SAHILPAY`.
3. Change **Sender ID** from `SAHILPAY` to `MPESA`. Leave the template text alone.
4. Save.
5. Admin → Co-Pilot → Messages → find the unparsed 5,000 message → **Retry**.

Expected: status flips to `parsed`, fields populate
(`amount 5000.00`, `account f2`, `ref UG9MLAK3ML`). If a tenant holds account `f2`
and auto-allocate is on, a Payment appears and the unit ledger moves.

If this works, §1 of the spec is confirmed and the deploy below is purely additive.

---

## Phase 1 — before you deploy

On your machine, with Sonnet's work merged to `backend-set-up`:

```bash
cd /home/swalleh/projects/sahil-pay
cd server && python -m pytest tests/ -q
```

All green, including `test_copilot_service.py` and the new
`test_copilot_landlord_inbox.py`. Then push:

```bash
git push origin backend-set-up
```

---

## Phase 2 — back up the database

Never migrate without this. On the VPS:

```bash
sudo -u postgres pg_dump sahilpay > ~/sahilpay-backup-$(date +%F-%H%M).sql
ls -lh ~/sahilpay-backup-*.sql
```

Confirm the file is non-trivial in size before continuing.

---

## Phase 3 — pull and build

```bash
cd /var/www/sahilpay/app
git fetch origin
git checkout backend-set-up
git pull origin backend-set-up
```

Python deps (no new ones expected, but cheap to confirm):

```bash
source /var/www/sahilpay/venv/bin/activate
pip install -r server/requirements.txt
```

Frontend — the new tab is React, so a rebuild is **mandatory** or landlords keep
seeing the old bundle:

```bash
cd /var/www/sahilpay/app/client
npm ci
npm run build
```

If `npm run build` OOMs on a small VPS:
```bash
NODE_OPTIONS=--max-old-space-size=2048 npm run build
```

---

## Phase 4 — migration

```bash
cd /var/www/sahilpay/app/server
source /var/www/sahilpay/venv/bin/activate
flask db upgrade
```

Expect the single `copilot_retain_unmatched` migration. Verify:

```bash
sudo -u postgres psql sahilpay -c "\d landlord_settings" | grep copilot
```

`copilot_retain_unmatched` should be present, `not null`, default `false`.

---

## Phase 5 — restart

```bash
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
sudo systemctl status sahilpay --no-pager
```

Green `active (running)`. If `failed`:

```bash
sudo journalctl -u sahilpay -n 50 --no-pager
```

---

## Phase 6 — verify live

```bash
curl -s localhost:8000/api/health
```

Then in a browser, hard-refresh (Ctrl+Shift+R — the old JS bundle is cached):

1. Landlord portal → **Payments → Co-Pilot tab** exists.
2. The 5,000 message from Phase 0 is listed with amount, account `f2`, reference.
3. Click **View** — raw SMS and all parsed fields render.
4. If it was auto-allocated, the unit ledger reflects it.
5. Buy airtime on the co-pilot phone → row appears as `Not recognised`, body redacted.

---

## Rollback

```bash
cd /var/www/sahilpay/app
git checkout cf6a530          # last known-good deployment commit
cd client && npm ci && npm run build
cd ../server && source /var/www/sahilpay/venv/bin/activate && flask db downgrade -1
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat
```

If the DB is wrong, restore the Phase 2 dump.

---

## Separate issue — email/SMS still dead

This is **not** fixed by the above and needs its own pass. Your systemd change
(dropping `EnvironmentFile=`, relying on `load_dotenv()`) only works if the unit's
`WorkingDirectory` is the directory containing `.env`. Check first:

```bash
systemctl show sahilpay -p WorkingDirectory
ls -la /var/www/sahilpay/app/server/.env
```

If `WorkingDirectory` is not `/var/www/sahilpay/app/server`, `load_dotenv()` is
reading nothing and **every** key is silently absent — which matches your symptom of
both email and SMS failing together.

Then confirm what the app actually loaded, rather than what the file says:

```bash
cd /var/www/sahilpay/app/server
source /var/www/sahilpay/venv/bin/activate
python -c "
from dotenv import load_dotenv; import os
load_dotenv()
for k in ('COMMS_SIMULATION_MODE','SENDGRID_API_KEY','FLUXSMS_API_KEY','FLUXSMS_SENDER_ID'):
    v = os.getenv(k)
    print(k, '=', (v[:6]+'...') if v and len(v) > 8 else v)
"
```

Any `None` there is your culprit. Note `COMMS_SIMULATION_MODE` must be `false` for
real sends — if it reads `None`, check how `config.py` defaults it, because a missing
value may be falling back to simulation. Report what this prints and we can fix it
directly; guessing further without it would waste your time.
