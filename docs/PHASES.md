# Kiểm Soát Phase

Hệ thống chỉ được tiến sang phase tiếp theo khi có yêu cầu rõ ràng.

## Phase 0: Nền móng

- Cấu trúc monorepo
- Docker Compose cho backend, web, PostgreSQL, Redis
- Mặc định an toàn ở backend
- Ranh giới scanner chỉ đọc
- Hàng rào kiểm soát rủi ro
- Khung thực thi chỉ PAPER
- Skeleton quản trị cho web/iOS

## Phase 1: Backend Core + Scanner + Paper Trading

- FastAPI backend core
- PostgreSQL + Redis + Docker Compose
- Binance public REST market data
- Active USD-M Perpetual discovery
- Lọc volume, spread, listing age, whitelist, blacklist
- Timeframe: `1m`, `5m`, `15m`, `1h`, `4h`
- Indicator: EMA20/50/200, RSI, MACD, ATR, Bollinger, VWAP, ADX, volume
- Market regime: `TRENDING_UP`, `TRENDING_DOWN`, `RANGING`, `HIGH_VOL`, `LOW_VOL`, `PANIC`
- Scanner chấm `LONG_SCORE` và `SHORT_SCORE` 0-100; không đủ điểm là `NO_TRADE`
- Strategy ban đầu: Trend Pullback, Breakout
- Risk engine: 0.5%/trade, max 1%, max daily loss 4%, max 4 positions, max leverage simulation 5x, RR tối thiểu 1.8, bắt buộc SL
- Paper trading: LONG/SHORT, Market/Limit model, SL, TP1/TP2/TP3, partial TP, break-even, trailing stop, fee, slippage, funding
- Lưu signals, orders, fills, positions, trades, PNL, logs
- REST API: status, markets, scanner, signals, positions, trades, performance, risk, settings, bot start/pause/stop
- WebSocket: market, scanner, positions, performance, system
- Tests: indicator, scanner, risk, position sizing, LONG/SHORT, SL/TP, PNL, fee/slippage

## Đang khoá cho tới khi được yêu cầu

- Thực thi lệnh Binance thật
- Cài đặt bộ đánh giá AI
- Chế độ LIVE
- Triển khai production cho logic trading thật
- Binance private API
- Demo mode
- Web UI Phase 1
- iOS Phase 1
