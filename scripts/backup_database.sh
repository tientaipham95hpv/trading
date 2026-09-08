#!/usr/bin/env bash
# PostgreSQL backup for the Docker Compose trading stack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP="$(date -u +"%Y%m%d_%H%M%S")"
BACKUP_FILE="$BACKUP_DIR/trading_${TIMESTAMP}.dump.gz"
TEMP_FILE="$BACKUP_FILE.tmp"
LOCK_FILE="$ROOT_DIR/.database-maintenance.lock"

mkdir -p "$BACKUP_DIR"
cd "$ROOT_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  printf 'Backup skipped: another database backup or restore is running.\n' >&2
  exit 75
fi
trap 'rm -f "$TEMP_FILE"' EXIT

docker compose exec -T postgres pg_dump -U trading -d trading --format=custom \
  | gzip -c > "$TEMP_FILE"

gzip -t "$TEMP_FILE"
set +o pipefail
gzip -cd "$TEMP_FILE" | docker compose exec -T postgres pg_restore --list >/dev/null
restore_list_status=${PIPESTATUS[1]}
set -o pipefail
if [[ "$restore_list_status" -ne 0 ]]; then
  printf 'Backup verification failed: pg_restore could not read the archive.\n' >&2
  exit 1
fi
mv "$TEMP_FILE" "$BACKUP_FILE"
trap - EXIT
find "$BACKUP_DIR" -type f -name 'trading_*.dump.gz' -mtime "+$RETENTION_DAYS" -delete
printf 'Backup verified: %s\n' "$BACKUP_FILE"
