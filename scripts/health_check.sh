#!/usr/bin/env bash
# Read-only health check for the Docker Compose trading stack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${API_BASE:-http://127.0.0.1:18000}"
cd "$ROOT_DIR"

printf 'Trading stack\n=============\n'
docker compose ps
printf '\nBackend health: '
health="$(curl --fail --silent --show-error --max-time 5 "$API_BASE/health")"
printf '%s\n' "$health"

printf '\nRecent backend errors (up to 10):\n'
docker compose logs --tail=200 backend 2>&1 | grep -Ei 'error|critical|traceback' | tail -10 || printf 'None found.\n'

printf '\nBackups:\n'
if compgen -G "$ROOT_DIR/backups/trading_*.dump.gz" >/dev/null; then
  ls -lht "$ROOT_DIR"/backups/trading_*.dump.gz | head -5
else
  printf 'No PostgreSQL backups found in %s/backups.\n' "$ROOT_DIR"
fi
