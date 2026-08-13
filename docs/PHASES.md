# Trading Automation — trạng thái và roadmap

Cập nhật: 2026-08-13

## Trạng thái hiện tại

Hệ thống đang chạy **DEMO end-to-end** với Binance Futures Demo/Testnet làm nguồn dữ liệu và execution:

- Backend FastAPI, PostgreSQL, Redis và web dashboard đang healthy qua Docker Compose.
- Auto-trader chạy liên tục: scanner → data-quality gate → xác nhận tín hiệu → risk engine → order plan → exchange adapter.
- Entry đi kèm Stop Loss và 3 mức Take Profit; watchdog phát hiện vị thế thiếu SL, tự repair khi có thể và chuyển `SAFE_MODE` khi không thể bảo vệ.
- User stream, reconciliation, orphan-order cleanup, duplicate client-order handling và emergency controls đã có.
- Portfolio risk đã có snapshot/audit theo symbol, hướng, tổng exposure, open risk và correlation nhưng hiện vẫn ở chế độ **shadow**, chưa chặn lệnh thật.
- Smart Entry đang **shadow/read-only**, thu outcome 4/12/24 nến và không tác động Baseline hay execution.
- Web và iOS dùng chung API; workflow GitHub Actions tạo unsigned IPA đã build thành công.
- CI backend/web chạy Ruff, Pytest, lint và production build trên push/PR.

## Bằng chứng DEMO ngày 2026-08-13

- Bot: `RUNNING`, exchange: `CONNECTED`, `SAFE_MODE=false`.
- Protective SL: đạt; reconciliation dưới 120 giây; không có open-order ID trùng; toàn bộ open orders do bot sở hữu.
- Stability verdict: `COLLECTING_DATA`, score 67/100.
- Mẫu hiện tại: 15/50 realized trades, khoảng 1/7 ngày.
- PNL realized: dương; profit factor khoảng 2.15 tại thời điểm audit, nhưng **chưa đủ mẫu để kết luận chiến lược hiệu quả**.
- Portfolio audit đã phát hiện exposure hiện tại vượt một số ngưỡng shadow; đây là bằng chứng cần hiệu chỉnh sizing/limits trước khi bật enforcement.

## Milestone hiện tại — DEMO ổn định và đủ bằng chứng

Không mở LIVE cho đến khi tất cả điều kiện sau đạt:

1. Tối thiểu **50 realized trades và 7 ngày** chạy DEMO liên tục cho readiness vận hành.
2. Thu **300–500 tín hiệu có outcome** để đánh giá chất lượng chiến lược theo strategy, symbol, timeframe và regime.
3. Không có vị thế thiếu SL, duplicate order, reconciliation stale hoặc incident critical đang mở.
4. Restart/redeploy không tạo lệnh trùng và trạng thái exchange được reconcile an toàn.
5. Portfolio risk shadow được quan sát đủ lâu, giới hạn được hiệu chỉnh và có test trước khi chuyển sang enforcement.
6. Backend, web và iOS đều qua CI/build.

## Thứ tự triển khai tiếp theo

### 1. Tiếp tục soak test DEMO

- Giữ bot chạy, không reset performance baseline nếu không có lý do vận hành rõ ràng.
- Theo dõi `/api/demo/stability`, `/api/risk`, `/api/smart-entry`, logs và incidents.
- Điều tra mọi reconnect, stale reconciliation, orphan order hoặc protective-stop repair.
- Xác minh TP1 → break-even, TP2 → trailing và close lifecycle bằng dữ liệu exchange thực tế.

### 2. Hiệu chỉnh portfolio risk trước enforcement

- So sánh sizing thực tế với `max_symbol_exposure`, `max_portfolio_exposure`, directional exposure và margin limits.
- Xử lý trường hợp plan mới làm vượt limit; bổ sung test fail-closed.
- Chỉ bật enforcement sau khi shadow audit ổn định và không có false positive do dữ liệu correlation thiếu/stale.

### 3. Đánh giá chiến lược bằng dữ liệu đủ mẫu

- Báo cáo win rate, expectancy, profit factor và drawdown theo strategy/symbol/timeframe/regime.
- Giữ Smart Entry ở shadow; chỉ cân nhắc canary khi outcome đủ mẫu và tốt hơn Baseline có ý nghĩa.
- Không tối ưu trực tiếp trên cùng tập dữ liệu dùng để đánh giá.

### 4. Hoàn thiện vận hành Web/iOS

- Hiển thị rõ stability blockers, data-quality status, exchange freshness, incidents và portfolio-risk reasons.
- Kiểm tra IPA trên thiết bị thật, auth/biometric và realtime reconnect.
- Duy trì hành động nguy hiểm có xác nhận, audit log và trạng thái phản hồi rõ ràng.

### 5. Production hardening rồi mới Testnet/LIVE gate

- Authentication/phân quyền API, quản lý secret, backup/restore và monitoring/alerting.
- Kiểm thử restart, network partition, partial fill, cancel/replace và exchange reconciliation.
- LIVE vẫn khóa mặc định; chỉ dùng vốn rất nhỏ sau khi readiness tự động và checklist thủ công cùng đạt.
