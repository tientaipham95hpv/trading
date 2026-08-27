#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SERVICES=(backend web)

echo "==> Rebuilding: ${SERVICES[*]}"
docker compose build "${SERVICES[@]}"

echo "==> Recreating: ${SERVICES[*]}"
docker compose up -d "${SERVICES[@]}"

echo "==> Waiting for health checks"
for service in "${SERVICES[@]}"; do
  container="$(docker compose ps -q "$service")"
  if [[ -z "$container" ]]; then
    echo "No container found for $service" >&2
    exit 1
  fi
  for attempt in {1..30}; do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null || true)"
    running="$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)"
    if [[ "$status" == "healthy" ]]; then
      echo "$service: healthy"
      break
    fi
    if [[ "$status" == "unhealthy" || "$running" != "true" ]]; then
      echo "$service: ${status:-no health status}, running=${running:-unknown}" >&2
      docker compose logs --tail=80 "$service" >&2
      exit 1
    fi
    if [[ "$attempt" == 30 ]]; then
      echo "$service: healthcheck timeout (status: ${status:-unknown})" >&2
      docker compose ps >&2
      exit 1
    fi
    sleep 2
  done
done

curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18000/health >/dev/null
unauthorized_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 http://127.0.0.1:18000/api/status)"
if [[ "$unauthorized_status" != "401" ]]; then
  echo "Auth smoke test failed: /api/status returned $unauthorized_status without a token" >&2
  exit 1
fi
echo "Deploy complete."
