#!/usr/bin/env sh
# Dumps the database to backups/mystock_<time>.dump (custom format) and keeps the newest 14.
#   ./scripts/backup.sh            # run from the repository root, while the stack is up
# Restore with scripts/restore.sh. Run it from cron daily (see README).
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] && . ./.env
mkdir -p backups
file="backups/mystock_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-mystock}" -d "${POSTGRES_DB:-mystock}" -Fc > "$file"
# An empty file means pg_dump failed; do not keep it as if it were a backup.
[ -s "$file" ] || { rm -f "$file"; echo "backup failed" >&2; exit 1; }
ls -1t backups/mystock_*.dump | tail -n +15 | xargs -r rm -f
echo "$file"
