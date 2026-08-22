# Deployment guide

## Safety baseline

- The committed default is `TRADING_MODE=DEMO`; `LIVE_TRADING_ENABLED=false`.
- Keep `PORTFOLIO_RISK_ENFORCEMENT_ENABLED=false` while validating shadow-calibration results. Enabling it rejects new entries that would violate portfolio-risk limits.
- Do not set LIVE mode until the live preflight gates documented in `docs/PHASES.md` are all satisfied and independently reviewed.

## Start and inspect

```bash
cd /var/www/trading
cp .env.example .env  # first deployment only; add DEMO credentials as needed
./scripts/quick_start.sh
./scripts/health_check.sh
```

The local backend health endpoint is `http://127.0.0.1:18000/health`. The web dashboard is served on `http://127.0.0.1:13000`.

## PostgreSQL backups

The stack stores data in Docker Compose PostgreSQL, not a SQLite file. Create a verified compressed custom-format dump:

```bash
./scripts/backup_database.sh
```

Backups are written to `backups/trading_*.dump.gz` and are retained for seven days by default (`RETENTION_DAYS` can override this). Schedule this script only after reviewing the host scheduler configuration; it is intentionally not modified by repository scripts.

Restore is destructive and requires explicit confirmation:

```bash
./scripts/restore_database.sh trading_YYYYMMDD_HHMMSS.dump.gz
```

## Operational checks

- `docker compose ps` — container state
- `docker compose logs --tail=200 backend` — backend logs
- `./scripts/health_check.sh` — read-only health and recent error summary
- `./scripts/check.sh` — backend tests plus web lint/build

## Configuration notes

Keep `.env` out of version control. Use `.env.example` only for non-secret defaults. Telegram alerts and AI evaluation are opt-in; the AI evaluator remains shadow-only and is never part of the execution or risk decision path.
