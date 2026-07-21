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

echo "==> Publishing frontend build"
rm -rf "${WEB_ROOT}.bak"
[ -d "$WEB_ROOT" ] && mv "$WEB_ROOT" "${WEB_ROOT}.bak"
cp -r client/dist "$WEB_ROOT"

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
