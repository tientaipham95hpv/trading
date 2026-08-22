#!/usr/bin/env bash
# Restore a PostgreSQL custom-format backup into the Docker Compose trading stack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <backup-file-or-path>\n' "$0" >&2
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'trading_*.dump.gz' -printf '%f\n' 2>/dev/null | sort -r | head -10 >&2 || true
  exit 2
fi

backup="$1"
[[ -f "$backup" ]] || backup="$BACKUP_DIR/$backup"
[[ -f "$backup" ]] || { printf 'Backup not found: %s\n' "$1" >&2; exit 2; }
gzip -t "$backup"

printf 'This replaces all data in the PostgreSQL trading database. Type RESTORE to continue: '
read -r confirmation
[[ "$confirmation" == "RESTORE" ]] || { printf 'Cancelled.\n'; exit 0; }

cd "$ROOT_DIR"
gzip -cd "$backup" | docker compose exec -T postgres pg_restore -U trading -d trading --clean --if-exists --no-owner --no-privileges
printf 'Restore completed from: %s\n' "$backup"
