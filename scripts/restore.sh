#!/usr/bin/env sh
# Restores a dump made by backup.sh, replacing what is in the database.
#   ./scripts/restore.sh backups/mystock_20261019_020000.dump
set -eu
[ $# -eq 1 ] || { echo "usage: $0 <dump file>" >&2; exit 2; }
cd "$(dirname "$0")/.."
[ -f .env ] && . ./.env
user="${POSTGRES_USER:-mystock}"; db="${POSTGRES_DB:-mystock}"
docker compose stop backend   # nothing may write while the tables are replaced
docker compose exec -T postgres pg_restore -U "$user" -d "$db" --clean --if-exists --no-owner < "$1"
docker compose start backend
echo "restored $1"
