from collections.abc import Iterable
from datetime import datetime

from app.domain.models import (
    Candle,
    ExitAnalyticsAvailability,
    ExitAnalyticsBreakdown,
    ExitAnalyticsResponse,
    ExitAnalyticsSummary,
    ExitExcursionMetrics,
)


class ExitAnalyticsService:
    """Pure, read-only aggregation of exchange history already fetched by the caller."""

    def analyze(
        self,
        trades: Iterable[dict[str, object]],
        income: Iterable[dict[str, object]],
        *,
        source: str = "Binance trade/order/income history",
        lifecycle_events: Iterable[dict[str, object]] = (),
        lifecycle_candles: dict[str, list[Candle]] | None = None,
    ) -> ExitAnalyticsResponse:
        closed = [row for row in trades if abs(_number(row.get("realizedPnl"))) > 1e-12]
        income_rows = list(income)
        commission = -sum(
            _number(r.get("income")) for r in income_rows if r.get("incomeType") == "COMMISSION"
        )
        funding = sum(
            _number(r.get("income")) for r in income_rows if r.get("incomeType") == "FUNDING_FEE"
        )
        realized = sum(_number(row.get("realizedPnl")) for row in closed)
        events = list(lifecycle_events)
        opens = {
            str(row.get("lifecycle_id")): row
            for row in events
            if row.get("event_type") == "OPEN" and row.get("risk_verifiable") is True
        }
        closes_by_lifecycle: dict[str, float] = {}
        for row in events:
            if row.get("event_type") not in {"CLOSE_FILL", "PARTIAL_CLOSE"}:
                continue
            lifecycle_id = str(row.get("lifecycle_id") or "")
            if not lifecycle_id or row.get("realized_pnl") is None:
                continue
            closes_by_lifecycle[lifecycle_id] = closes_by_lifecycle.get(
                lifecycle_id, 0.0
            ) + _number(row.get("realized_pnl"))
        matched = [key for key in closes_by_lifecycle if key in opens]
        covered_risk = sum(_number(opens[key].get("initial_risk")) for key in matched)
        covered_pnl = sum(closes_by_lifecycle[key] for key in matched)
        realized_r = covered_pnl / covered_risk if covered_risk > 0 else None
        coverage = len(matched) / len(closes_by_lifecycle) if closes_by_lifecycle else 0.0
        excursion, excursion_coverage, excursion_reason = self._excursions(
            events, lifecycle_candles or {}, closes_by_lifecycle
        )
        excursion_available = excursion.lifecycles > 0

        return ExitAnalyticsResponse(
            source=source,
            summary=ExitAnalyticsSummary(
                close_fills=len(closed),
                realized_pnl=realized,
                commission=commission,
                funding=funding,
                net_realized_pnl=realized - commission + funding,
            ),
            by_close_reason=self._breakdown(closed, "reason"),
            by_side=self._breakdown(closed, "position_side"),
            by_symbol=self._breakdown(closed, "symbol"),
            realized_r=realized_r,
            excursion=excursion,
            realized_r_availability=ExitAnalyticsAvailability(
                available=realized_r is not None,
                coverage=coverage,
                reason=None
                if realized_r is not None
                else "Recorder chưa có lifecycle đóng khớp với initial risk đã xác minh.",
            ),
            mae_availability=ExitAnalyticsAvailability(
                available=excursion_available,
                coverage=excursion_coverage,
                reason=None if excursion_available else excursion_reason,
            ),
            mfe_availability=ExitAnalyticsAvailability(
                available=excursion_available,
                coverage=excursion_coverage,
                reason=None if excursion_available else excursion_reason,
            ),
            missed_r_availability=ExitAnalyticsAvailability(
                available=excursion_available,
                coverage=excursion_coverage,
                reason=None if excursion_available else excursion_reason,
            ),
            notes=[
                "Số lần thoát là số close fill, không phải số lifecycle giao dịch đã đóng.",
                "PnL theo reason/side/symbol lấy từ các close fill có realizedPnl khác 0.",
                "Commission và funding là tổng theo income history; không phân bổ giả định vào từng nhóm.",
            ],
        )

    def _breakdown(self, rows: list[dict[str, object]], field: str) -> list[ExitAnalyticsBreakdown]:
        totals: dict[str, tuple[int, float]] = {}
        for row in rows:
            key = str(row.get(field) or "Không xác định")
            count, pnl = totals.get(key, (0, 0.0))
            totals[key] = count + 1, pnl + _number(row.get("realizedPnl"))
        return [
            ExitAnalyticsBreakdown(key=key, closes=count, realized_pnl=pnl, net_realized_pnl=pnl)
            for key, (count, pnl) in sorted(totals.items())
        ]

    @staticmethod
    def _excursions(
        events: list[dict[str, object]],
        candles_by_lifecycle: dict[str, list[Candle]],
        realized_by_lifecycle: dict[str, float],
    ) -> tuple[ExitExcursionMetrics, float, str]:
        opens = {
            str(row.get("lifecycle_id")): row
            for row in events
            if row.get("event_type") == "OPEN"
            and row.get("risk_verifiable") is True
            and row.get("entry_timestamp_verifiable") is True
            and row.get("timeframe")
            and _event_ms(row) is not None
        }
        terminal = _terminal_closes(events)
        eligible = sorted(set(opens) & set(terminal))
        mae_values: list[float] = []
        mfe_values: list[float] = []
        missed_values: list[float] = []
        for lifecycle_id in eligible:
            row = opens[lifecycle_id]
            entry_ms = _event_ms(row)
            close_ms = _event_ms(terminal[lifecycle_id])
            candles = candles_by_lifecycle.get(lifecycle_id, [])
            interval_ms = _interval_ms(str(row.get("timeframe")))
            if entry_ms is None or close_ms is None or not interval_ms or close_ms <= entry_ms:
                continue
            expected_first = ((entry_ms + interval_ms - 1) // interval_ms) * interval_ms
            expected_last = ((close_ms + 1) // interval_ms) * interval_ms - interval_ms
            selected = [
                candle
                for candle in candles
                if candle.open_time >= expected_first and candle.close_time < close_ms
            ]
            expected_count = (
                (expected_last - expected_first) // interval_ms + 1
                if expected_last >= expected_first
                else 0
            )
            if expected_count <= 0 or len(selected) != expected_count:
                continue
            if any(
                candle.open_time != expected_first + index * interval_ms
                for index, candle in enumerate(selected)
            ):
                continue
            entry = _number(row.get("entry_price"))
            stop = _number(row.get("initial_stop_loss"))
            risk_per_unit = abs(entry - stop)
            if entry <= 0 or risk_per_unit <= 0:
                continue
            side = str(row.get("side") or "").upper()
            if side == "LONG":
                mae_r = max(0.0, (entry - min(c.low for c in selected)) / risk_per_unit)
                mfe_r = max(0.0, (max(c.high for c in selected) - entry) / risk_per_unit)
            elif side == "SHORT":
                mae_r = max(0.0, (max(c.high for c in selected) - entry) / risk_per_unit)
                mfe_r = max(0.0, (entry - min(c.low for c in selected)) / risk_per_unit)
            else:
                continue
            initial_risk = _number(row.get("initial_risk"))
            if lifecycle_id not in realized_by_lifecycle or initial_risk <= 0:
                continue
            realized_r = realized_by_lifecycle[lifecycle_id] / initial_risk
            mae_values.append(mae_r)
            mfe_values.append(mfe_r)
            missed_values.append(max(0.0, mfe_r - realized_r))
        coverage = len(mae_values) / len(eligible) if eligible else 0.0
        reason = (
            "Chưa có lifecycle hoàn tất với initial risk, timeframe, timestamp và nến đóng đầy đủ."
            if not eligible
            else "Một hoặc nhiều lifecycle thiếu chuỗi nến đóng liên tục trong toàn bộ thời gian giữ lệnh."
        )
        count = len(mae_values)
        return (
            ExitExcursionMetrics(
                lifecycles=count,
                mae_r=sum(mae_values) / count if count else None,
                mfe_r=sum(mfe_values) / count if count else None,
                missed_r=sum(missed_values) / count if count else None,
            ),
            coverage,
            reason,
        )


def excursion_requests(
    events: Iterable[dict[str, object]],
) -> dict[str, tuple[str, str, int, int, int]]:
    rows = list(events)
    opens = {
        str(row.get("lifecycle_id")): row
        for row in rows
        if row.get("event_type") == "OPEN"
        and row.get("risk_verifiable") is True
        and row.get("entry_timestamp_verifiable") is True
        and row.get("timeframe")
    }
    closes = _terminal_closes(rows)
    requests: dict[str, tuple[str, str, int, int, int]] = {}
    for lifecycle_id in set(opens) & set(closes):
        opened = opens[lifecycle_id]
        start_ms = _event_ms(opened)
        end_ms = _event_ms(closes[lifecycle_id])
        interval = str(opened.get("timeframe"))
        interval_ms = _interval_ms(interval)
        if start_ms is None or end_ms is None or not interval_ms or end_ms <= start_ms:
            continue
        first = ((start_ms + interval_ms - 1) // interval_ms) * interval_ms
        count = max(0, (end_ms - first) // interval_ms)
        if 0 < count <= 5000:
            requests[lifecycle_id] = (
                str(opened.get("symbol") or ""),
                interval,
                first,
                end_ms,
                count,
            )
    return requests


def _terminal_closes(
    events: Iterable[dict[str, object]],
) -> dict[str, dict[str, object]]:
    terminal: dict[str, dict[str, object]] = {}
    for row in events:
        if row.get("event_type") != "CLOSE_FILL" or _event_ms(row) is None:
            continue
        reason = row.get("reason")
        lifecycle_id = str(row.get("lifecycle_id") or "")
        if not lifecycle_id:
            continue
        if reason in {"STOP_LOSS", "MARKET_CLOSE"}:
            terminal[lifecycle_id] = row
            continue
        if reason == "TAKE_PROFIT" and str(row.get("lifecycle_state") or "") == "CLOSED":
            terminal[lifecycle_id] = row
    return terminal


def normalize_exchange_closes(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    normalized = []
    for row in rows:
        item = dict(row)
        client_id = str(item.get("clientOrderId") or "").lower()
        item["reason"] = (
            "Stop Loss"
            if any(tag in client_id for tag in ("-sl-", "-be-", "-lock-", "-repair-"))
            else "Take Profit"
            if "-tp-" in client_id
            else "Thủ công/thị trường"
        )
        order_side = str(item.get("side") or "").upper()
        item["position_side"] = (
            "LONG" if order_side == "SELL" else "SHORT" if order_side == "BUY" else "Không xác định"
        )
        item["symbol"] = str(item.get("symbol") or "Không xác định")
        normalized.append(item)
    return normalized


def _event_ms(row: dict[str, object]) -> int | None:
    value = row.get("event_at")
    try:
        if isinstance(value, datetime):
            return int(value.timestamp() * 1000)
        if isinstance(value, str):
            return int(datetime.fromisoformat(value).timestamp() * 1000)
    except ValueError:
        return None
    return None


def _interval_ms(interval: str) -> int | None:
    return {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}.get(
        interval
    )


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
