#!/usr/bin/env bash
# =============================================================================
# Sahil Pay — redeploy script. Run on the VPS as the sahilpay user after the
# first-time setup in DEPLOYMENT_GUIDE.md:
#   cd /var/www/sahilpay/app && ./deploy/update.sh
#
# Layout on the VPS:
#   /var/www/sahilpay/app     — this git repo (source)
#   /var/www/sahilpay/client  — live frontend build served by nginx
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root: /var/www/sahilpay/app
WEB_ROOT=/var/www/sahilpay/client

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Backend: dependencies + migrations"
server/venv/bin/pip install -r server/requirements.txt --quiet
(cd server && set -a && source .env && set +a && venv/bin/flask db upgrade)

echo "==> Frontend: build"
(cd client && npm ci --silent && npm run build)

# Prerender the public pages so crawlers and WhatsApp/Facebook link previews
# see real text instead of an empty <div>. It drives a headless Chromium, which
# is a big optional dependency — so a missing browser must NOT abort a
# deployment. The app is fully functional without it; only SEO is reduced.
#   One-time, to enable it:  cd client && npx playwright install --with-deps chromium
echo "==> Frontend: SEO prerender (optional)"
if (cd client && npm run prerender); then
  echo "    prerendered ✔"
else
  echo "    SKIPPED — headless Chromium unavailable. The site works; public"
  echo "    pages just render client-side. Install with:"
  echo "      cd /var/www/sahilpay/app/client && npx playwright install --with-deps chromium"
fi

echo "==> Publishing frontend build"
rm -rf "${WEB_ROOT}.bak"
[ -d "$WEB_ROOT" ] && mv "$WEB_ROOT" "${WEB_ROOT}.bak"
cp -r client/dist "$WEB_ROOT"

echo "==> Ensuring the upload directory exists"
# Tutorial screenshots, signed lease scans and the Co-pilot APK live here, and
# nginx serves it directly at /uploads/. A missing directory makes every upload
# fail at write time rather than at validation.
mkdir -p server/uploads

echo "==> Restarting services"
sudo systemctl restart sahilpay sahilpay-celery sahilpay-celerybeat

echo "==> Health check"
sleep 2
if curl -sf https://sahilpay.co.ke/api/health >/dev/null; then
  echo "API healthy ✔ — deploy complete"
else
  echo "WARNING: health check failed — check: sudo journalctl -u sahilpay -n 50"
  exit 1
fi
