#!/usr/bin/env bash
# Clear the LOCAL login rate limiter.
#
# /api/auth/login is capped at "5 per minute; 30 per hour" per IP. Both numbers
# are right for production — a human needs two or three attempts, and the hourly
# cap is what stops a slow drip staying under the per-minute one.
#
# They are also, correctly, indifferent to the fact that a verification run
# signs in as eight different accounts. Once the hourly budget is gone, waiting
# inside the run cannot recover it, and every subsequent check fails for a
# reason that has nothing to do with the code under test.
#
# So: reset it deliberately between full verification passes, rather than
# weakening the limit or teaching the scripts to ignore 429s.
#
#   ./dev-reset-ratelimit.sh
#
# NEVER run this against a production Redis. It refuses unless REDIS_URL is
# local.
set -euo pipefail

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

case "$REDIS_URL" in
  *localhost*|*127.0.0.1*) ;;
  *)
    echo "REDIS_URL does not look local ($REDIS_URL) — refusing."
    exit 1
    ;;
esac

before=$(redis-cli --scan --pattern "LIMIT*" 2>/dev/null | wc -l)
redis-cli --scan --pattern "LIMIT*" 2>/dev/null | while read -r key; do
  [ -n "$key" ] && redis-cli DEL "$key" >/dev/null
done
echo "cleared $before rate-limit key(s) — login budget reset"
