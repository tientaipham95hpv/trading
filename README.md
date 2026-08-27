# Nền tảng Trading tự động

Hệ thống điều khiển giao dịch Binance USD-M Futures. Trạng thái hiện tại là **DEMO end-to-end**; LIVE bị khóa cho đến khi toàn bộ readiness gate đạt yêu cầu và được duyệt thủ công.

## Thành phần

- Backend: Python 3.12, FastAPI
- Dữ liệu: PostgreSQL 16, Redis 7
- Web: Next.js 16, TypeScript
- iOS: SwiftUI
- Hạ tầng: Docker Compose, Nginx reverse proxy

## Baseline an toàn hiện hành

Cấu hình production ngày 2026-08-26:

- `TRADING_MODE=DEMO`, `LIVE_TRADING_ENABLED=false`
- Isolated margin; tối đa `10x`
- Rủi ro mục tiêu mỗi lệnh `0.25%`, trần `0.35%`
- Daily loss limit `4%`; tối đa `1` vị thế mở
- Portfolio risk đang `ENFORCED` cho entry mới
- Mọi order plan bắt buộc có Stop Loss; không martingale
- SAFE_MODE/emergency stop chặn entry khi trạng thái không chắc chắn
- AI evaluator tắt; Smart Entry chỉ shadow/read-only
- API và WebSocket bắt buộc Bearer token trong production
- Secret chỉ nằm trong `.env` backend, không commit và không đưa vào frontend bundle

## Authentication

Production bắt buộc có `API_AUTH_TOKEN`. Tạo token bằng:

```bash
openssl rand -hex 32
```

Web hiển thị màn hình đăng nhập và chỉ giữ token trong `sessionStorage` của tab. iOS lưu cùng token trong Keychain. HTTP dùng header:

```text
Authorization: Bearer <token>
```

WebSocket trình duyệt truyền token qua tham số kết nối; iOS dùng Authorization header. `/health` vẫn mở để healthcheck, toàn bộ `/api/*` được bảo vệ.

## Chạy và deploy

```bash
cp .env.example .env
# điền API_AUTH_TOKEN và DEMO credentials
./scripts/quick_start.sh
```

Sau khi sửa backend/web:

```bash
./scripts/check.sh
./scripts/deploy.sh
```

`deploy.sh` chỉ rebuild/recreate backend và web, chờ healthcheck; PostgreSQL và Redis không bị recreate.

Các cổng loopback:

- Web: `127.0.0.1:13000`
- Backend: `127.0.0.1:18000`
- PostgreSQL: `127.0.0.1:15432`
- Redis: `127.0.0.1:16379`
- Domain: `https://trading.cineviet.live`

Kiểm tra:

```bash
./scripts/health_check.sh
curl http://127.0.0.1:18000/health
curl -H "Authorization: Bearer $API_AUTH_TOKEN" http://127.0.0.1:18000/api/status
```

## Quality gates

```bash
cd backend
. .venv/bin/activate
ruff check .
pytest

cd ../web
npm run lint
npm run build
npm audit --audit-level=high
```

Baseline audit 2026-08-27: Ruff sạch, 195 backend tests pass, web lint không warning, production build pass, npm audit không có lỗ hổng.

## Chức năng chính

- Scanner đa khung thời gian, signal/data-quality gate
- Risk engine, portfolio exposure/correlation enforcement
- Order lifecycle với SL, nhiều TP, break-even/trailing
- User stream, reconciliation, duplicate/orphan handling
- SAFE_MODE, emergency stop và LIVE readiness gates
- Dashboard realtime: market, scanner, positions, orders, trades, analytics, risk, journal, settings
- Smart Entry và AI analytics shadow/read-only

Các endpoint được liệt kê tự động tại `/docs` khi có token. Roadmap và tiêu chí LIVE nằm trong `docs/PHASES.md`; hướng dẫn vận hành ở `docs/DEPLOYMENT_GUIDE.md`.
