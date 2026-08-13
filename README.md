# Nền Tảng Trading Tự Động

Hệ thống điều khiển giao dịch futures tự động cho Binance USD-M Futures.

Phase hiện tại: chỉ là nền móng dự án. Giao dịch LIVE mặc định đang tắt.

## Công nghệ

- Backend: Python 3.12, FastAPI
- Dữ liệu: PostgreSQL, Redis
- Web: Next.js, TypeScript
- iOS: SwiftUI
- Hạ tầng: Docker Compose

## Mặc định an toàn

- Chế độ giao dịch mặc định là `DEMO`
- Chế độ LIVE mặc định bị tắt
- Ký quỹ mặc định là isolated
- Đòn bẩy tối đa mặc định `5x`
- Rủi ro mỗi lệnh mặc định `0.5%`
- Mức lỗ tối đa mỗi ngày mặc định `4%`
- Số vị thế mở tối đa mặc định `4`
- Mọi kế hoạch lệnh đều bắt buộc có stop loss
- Chặn martingale
- Dừng khẩn cấp sẽ chặn thực thi lệnh
- Binance API key chỉ nằm ở biến môi trường backend

## Chạy

```bash
cp .env.example .env
docker compose up --build
```

Docker Compose dùng port riêng để không đụng service production trên VPS:

- Web: `http://localhost:13000`
- Backend: `http://localhost:18000`
- PostgreSQL: `localhost:15432`
- Redis: `localhost:16379`

Kiểm tra backend:

```bash
curl http://localhost:18000/health
```

Web:

```bash
cd web
npm install
npm run dev
```

Production systemd trên VPS đang dùng:

- Web: `127.0.0.1:3000`
- Backend: `127.0.0.1:8000`
- Domain: `https://trading.cineviet.live`

Test backend local:

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Chế độ

Các chế độ được phép là `DEMO` và `LIVE`.

LIVE yêu cầu đồng thời:

- `TRADING_MODE=LIVE`
- `LIVE_TRADING_ENABLED=true`

Không bật hai giá trị này nếu chưa được duyệt rõ ràng.

## Phase 1 API

- `GET /api/status`
- `GET /api/markets`
- `GET /api/scanner?limit=30&timeframes=1m,5m,15m,1h,4h`
- `GET /api/signals`
- `POST /api/positions/mark/{symbol}?price=...`
- `GET /api/positions`
- `GET /api/trades`
- `GET /api/performance`
- `GET /api/risk`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/bot/start`
- `POST /api/bot/pause`
- `POST /api/bot/stop`

WebSocket:

- `/api/ws/market`
- `/api/ws/scanner`
- `/api/ws/positions`
- `/api/ws/performance`
- `/api/ws/system`
