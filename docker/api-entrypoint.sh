#!/bin/sh
# Apply database migrations before starting the API (idempotent).
set -e
cd /srv/apps/api
alembic upgrade head
exec "$@"
