# Trading Automation — trạng thái và roadmap

Cập nhật: 2026-08-27

## Trạng thái hiện tại

Hệ thống đang chạy **DEMO end-to-end**, nhưng bot hiện được giữ **STOPPED** để tránh phát sinh dữ liệu/lệnh trong lúc hardening và audit. Backend, web, PostgreSQL và Redis đều healthy qua Docker Compose.

Các năng lực đã có:

- Scanner → data-quality gate → signal confirmation → risk engine → order plan → exchange adapter.
- Entry có Stop Loss và 3 mức Take Profit; watchdog repair SL khi có thể, SAFE_MODE khi không thể bảo vệ vị thế.
- User stream, reconciliation, orphan-order cleanup, duplicate client-order handling và emergency controls.
- Portfolio risk enforcement cho entry mới đã bật trong runtime DEMO; giới hạn exposure/open risk/correlation vẫn cần được quan sát và hiệu chỉnh bằng dữ liệu dài hạn.
- Smart Entry và AI evaluator chỉ shadow/read-only, không tham gia quyết định execution hay risk.
- Web dashboard có auth gate; iOS dùng Keychain; API và WebSocket production bắt buộc Bearer token.
- CI/local quality gate hiện sạch: Ruff, 195 Pytest, web lint, production build và npm audit.

## Evidence tại thời điểm audit 2026-08-26

- Runtime: `TRADING_MODE=DEMO`, `LIVE_TRADING_ENABLED=false`, `SAFE_MODE=false`, emergency stop tắt.
- API public không token trả `401`; API hợp lệ và WebSocket token-auth đã xác minh được.
- LIVE readiness: `allowed=false`; blockers là LIVE bị khóa thủ công và `demo_stable=false`.
- Khi bot dừng, exchange snapshot/reconciliation có thể hiển thị `STALE`; đây không phải trạng thái chấp nhận được để bật hoặc chạy bot. Cần reconnect/reconcile thành công trước khi start.
- Các container backend, web, PostgreSQL và Redis đều healthy sau deploy.

## Điều kiện tuyệt đối trước LIVE

Không mở LIVE cho đến khi **tất cả** điều kiện sau đạt và có xác nhận thủ công độc lập:

1. Ít nhất **50 realized trades và 7 ngày** DEMO liên tục, với exchange/reconciliation không stale.
2. 300–500 tín hiệu có outcome, được phân tích theo strategy, symbol, timeframe và regime; không tối ưu trên cùng tập đánh giá.
3. Không còn vị thế thiếu SL, duplicate order, orphan order, reconciliation stale, reconnect incident, hoặc incident critical đang mở.
4. Restart/redeploy/network-partition/partial-fill/cancel-replace đã được kiểm thử không tạo lệnh trùng và reconcile an toàn.
5. Portfolio-risk enforcement được quan sát đủ lâu; giới hạn sizing/exposure/correlation đã hiệu chỉnh, có test fail-closed và không false positive vì dữ liệu stale/thiếu.
6. Backend, web và iOS đều qua CI/build; IPA được kiểm tra trên thiết bị thật, gồm auth/Keychain/biometric và reconnect realtime.
7. Backup/restore, monitoring và alerting đã được diễn tập. API token/secret rotation và audit log vận hành được kiểm tra.

## Thứ tự công việc tiếp theo

### 1. Khôi phục DEMO soak test có kiểm soát

Chỉ start bot sau khi xác minh exchange đã reconnect/reconcile fresh và operator chủ động chấp nhận tạo DEMO activity. Theo dõi `/api/demo/stability`, `/api/risk`, `/api/smart-entry`, logs, incident và portfolio audit.

### 2. Quan sát và hiệu chỉnh risk

So sánh sizing/exposure thực tế với `max_symbol_exposure`, `max_portfolio_exposure`, directional exposure, margin và correlation limits. Điều tra mọi `WOULD_REJECT`, stale data hoặc protective-stop repair trước khi đổi cấu hình.

### 3. Đánh giá chiến lược

Báo cáo win rate, expectancy, profit factor, drawdown theo strategy/symbol/timeframe/regime. Giữ Smart Entry shadow đến khi outcome đủ mẫu và tốt hơn Baseline có ý nghĩa thống kê.

### 4. Production hardening vận hành

Duy trì token auth; lập quy trình rotation, backup/restore và alerting. Theo dõi lỗi WebSocket/reconnect, healthchecks và log exception. Bất kỳ thay đổi LIVE/risk nào đều cần review và test trước.
