#!/bin/sh
# Apply database migrations (idempotent), then start the API on $PORT (default 8000).
set -e
cd /srv/apps/api
alembic upgrade head
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
