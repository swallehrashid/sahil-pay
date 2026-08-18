#!/usr/bin/env bash
# Everything, in one command.
#
#   ./verify-all.sh            backend suite + every browser check
#   ./verify-all.sh --scale    ...and the 1,000-unit audit + scale E2E
#
# The rate limiter is reset between browser suites on purpose. /api/auth/login
# allows "5 per minute; 30 per hour" per IP, which is right in production and
# which a run that signs in as eight accounts will exhaust — after which every
# later check fails for a reason unrelated to the code under test. Resetting is
# honest; weakening the limit, or teaching the checks to ignore 429s, is not.
set -uo pipefail

cd "$(dirname "$0")"
ROOT="$PWD"
FAILED=()

step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
record() { [ "$1" -eq 0 ] || FAILED+=("$2"); }

# ---------------------------------------------------------------------------
step "Backend suite"
cd "$ROOT/server"
# shellcheck disable=SC1091
source venv/bin/activate
APP_ENV=testing python -m pytest tests/ -q --ignore=tests/render_email_previews.py 2>&1 | tail -3
record "${PIPESTATUS[0]}" "backend tests"

# ---------------------------------------------------------------------------
step "Frontend build + lint"
cd "$ROOT/client"
npx vite build >/dev/null 2>&1
record $? "vite build"
npx eslint src --max-warnings 9999 >/dev/null 2>&1
record $? "eslint"

# ---------------------------------------------------------------------------
step "Local stack"
cd "$ROOT/server"
./dev-restart.sh || { echo "API would not start"; exit 1; }
cd "$ROOT/client"
if ! curl -sf -o /dev/null http://localhost:5173/; then
  nohup npm run dev >/tmp/sahilpay-vite.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf -o /dev/null http://localhost:5173/ && break
    sleep 1
  done
fi

# ---------------------------------------------------------------------------
for suite in verify-fixes _check-payouts _check-report-perms \
             _check-bulk-import _check-batch-penalties _check-invoice-queue \
             _check-tenant-and-new-ui; do
  step "Browser: $suite"
  "$ROOT/server/dev-reset-ratelimit.sh" >/dev/null 2>&1
  node "scripts/$suite.mjs" 2>&1 | tail -3
  record "${PIPESTATUS[0]}" "$suite"
done

# ---------------------------------------------------------------------------
if [ "${1:-}" = "--scale" ]; then
  SCALE_DB="postgresql://sahilpay:0712430742Ss@localhost:5432/sahilpay_scale"

  step "Scale: report accuracy audit"
  cd "$ROOT/server"
  APP_ENV=development DATABASE_URL="$SCALE_DB" COMMS_SIMULATION_MODE=true \
    python scale_audit.py 2>&1 | tail -4
  record "${PIPESTATUS[0]}" "scale audit"

  step "Scale: end-to-end through the UI"
  pkill -f "flask run" >/dev/null 2>&1 || true
  sleep 2
  APP_ENV=development DATABASE_URL="$SCALE_DB" COMMS_SIMULATION_MODE=true \
    ENFORCE_EMAIL_VERIFICATION=true FLASK_APP=app.py \
    nohup flask run --port 5000 >/tmp/sahilpay-scale-api.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf -o /dev/null http://localhost:5000/api/health && break
    sleep 1
  done
  "$ROOT/server/dev-reset-ratelimit.sh" >/dev/null 2>&1
  cd "$ROOT/client"
  node scripts/e2e-scale.mjs 2>&1 | tail -3
  record "${PIPESTATUS[0]}" "scale e2e"

  # Leave the stack on the ordinary dev database.
  "$ROOT/server/dev-restart.sh" >/dev/null 2>&1
fi

# ---------------------------------------------------------------------------
printf '\n%s\n' "============================================================"
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "Everything passed."
  exit 0
fi
echo "Failed: ${FAILED[*]}"
exit 1
