# Sahil Pay

Smart rent collection for Kenyan landlords and property managers.
Flask + PostgreSQL API, React (Vite) frontend, M-Pesa Daraja, FluxSMS, Resend.

```
client/     React frontend (Vite)
server/     Flask API, Celery workers, migrations
deploy/     nginx config, systemd units, update.sh
docs/       All documentation — see below
```

## Documentation

**Every `.md` file in this repository lives in [`docs/`](docs/)**, except this
one. Add new documentation there, not at the root.

Start here:

| I want to… | Read |
|---|---|
| **Deploy the current release** | [docs/REDEPLOY.md](docs/REDEPLOY.md) |
| Set up a server from scratch | [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) |
| Understand transactional email | [docs/EMAIL_RESEND_SETUP.md](docs/EMAIL_RESEND_SETUP.md) |
| Get a logo/signature onto receipts | [docs/BRAND_ASSETS_REQUIREMENTS.md](docs/BRAND_ASSETS_REQUIREMENTS.md) |
| Understand search, totals and SMS margins | [docs/SCALE_AND_SEARCH_NOTES.md](docs/SCALE_AND_SEARCH_NOTES.md) |

[docs/INDEX.md](docs/INDEX.md) lists everything.

## Running locally

```bash
# API on :5000
cd server && ./dev-restart.sh

# Frontend on :5173
cd client && npm install && npm run dev
```

Seeded logins are in `seed data credentials`.

## Tests

```bash
cd server && source venv/bin/activate && python -m pytest tests/ -q

cd client
node scripts/stage1_walkthrough.mjs   # branding, receipts, colours
node scripts/stage2_walkthrough.mjs   # search, totals, dropdowns
node scripts/dropdown_audit.mjs       # every dropdown in every portal
```
