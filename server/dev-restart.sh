#!/usr/bin/env bash
# Restart the local API cleanly.
#
# Written after losing time twice to the same trap: `pkill` returns non-zero
# when it matches nothing, which aborts a `&&` chain, so the "restart" never
# killed anything — the new server then failed to bind with "Address already in
# use", exited, and every subsequent request was answered by a stale process
# running code from an hour earlier. That looks exactly like a broken feature.
#
# So: kill, WAIT for the port to actually free, start, and verify.
#
#   ./dev-restart.sh          # simulation mode, verification enforced
set -u

PORT="${PORT:-5000}"
LOG="${LOG:-/tmp/sahilpay-api.log}"
cd "$(dirname "$0")"

pkill -f "flask run" >/dev/null 2>&1 || true

for _ in $(seq 1 20); do
  if ! ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then break; fi
  sleep 0.5
done

if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
  echo "port $PORT is still held — refusing to start a server that would not bind"
  ss -ltnp 2>/dev/null | grep ":$PORT"
  exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate
APP_ENV=development \
COMMS_SIMULATION_MODE=true \
ENFORCE_EMAIL_VERIFICATION=true \
FLASK_APP=app.py \
  nohup flask run --port "$PORT" > "$LOG" 2>&1 &

for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/api/health" || true)
  if [ "$code" = "200" ]; then
    echo "API up on :$PORT (log: $LOG)"
    exit 0
  fi
  sleep 0.5
done

echo "API did not come up. Last lines of $LOG:"
tail -20 "$LOG"
exit 1
