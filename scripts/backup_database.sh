#!/usr/bin/env bash
# PostgreSQL backup for the Docker Compose trading stack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP="$(date -u +"%Y%m%d_%H%M%S")"
BACKUP_FILE="$BACKUP_DIR/trading_${TIMESTAMP}.dump.gz"

mkdir -p "$BACKUP_DIR"
cd "$ROOT_DIR"

docker compose exec -T postgres pg_dump -U trading -d trading --format=custom \
  | gzip -c > "$BACKUP_FILE"

gzip -t "$BACKUP_FILE"
find "$BACKUP_DIR" -type f -name 'trading_*.dump.gz' -mtime "+$RETENTION_DAYS" -delete
printf 'Backup verified: %s\n' "$BACKUP_FILE"
