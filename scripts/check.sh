#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../backend"
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi
ruff check .
python3 -m pytest

cd ../web
npm run lint
npm run build
npm audit --audit-level=high
