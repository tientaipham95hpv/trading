#!/usr/bin/env bash
# Start the Docker Compose stack without changing host schedulers or trading mode.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  printf 'Missing .env. Copy .env.example and configure DEMO credentials before starting.\n' >&2
  exit 2
fi

docker compose up -d
for _ in {1..30}; do
  if curl --silent --fail --max-time 3 http://127.0.0.1:18000/health >/dev/null; then
    curl --silent http://127.0.0.1:18000/health
    exit 0
  fi
  sleep 1
done

printf 'Backend did not become healthy within 30 seconds.\n' >&2
exit 1
