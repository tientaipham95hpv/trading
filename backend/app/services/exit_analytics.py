from collections.abc import Iterable
from datetime import datetime

from app.domain.models import (
    Candle,
    ExitAnalyticsAvailability,
    ExitAnalyticsBreakdown,
    ExitAnalyticsResponse,
    ExitAnalyticsSummary,
    ExitExcursionMetrics,
    LifecycleAnalyticsSummary,
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
        lifecycle_rows = _verified_completed_lifecycles(events)
        closes_by_lifecycle = {
            lifecycle_id: sum(_number(row.get("realized_pnl")) for row in rows)
            for lifecycle_id, rows in _deduplicated_close_fills(events).items()
            if any(row.get("realized_pnl") is not None for row in rows)
        }
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
            lifecycle_summary=self._lifecycle_summary(events, lifecycle_rows),
            lifecycle_by_reason=self._lifecycle_breakdown(lifecycle_rows, "reason"),
            lifecycle_by_side=self._lifecycle_breakdown(lifecycle_rows, "side"),
            lifecycle_by_symbol=self._lifecycle_breakdown(lifecycle_rows, "symbol"),
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
                "Commission và funding là tổng theo income history; funding không được phân bổ giả định vào lifecycle.",
                "Lifecycle metrics chỉ dùng terminal close khớp OPEN; execution updates trùng trade được dedupe.",
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
    def _lifecycle_summary(
        events: list[dict[str, object]], rows: list[dict[str, object]]
    ) -> LifecycleAnalyticsSummary:
        lifecycle_ids = {str(row.get("lifecycle_id")) for row in events if row.get("lifecycle_id")}
        opened = {str(row.get("lifecycle_id")) for row in events if row.get("event_type") == "OPEN"}
        terminal = set(_terminal_closes(events))
        pnl = [_number(row.get("net_pnl")) for row in rows]
        wins = [value for value in pnl if value > 1e-12]
        losses = [value for value in pnl if value < -1e-12]
        equity = peak = drawdown = 0.0
        streak = max_streak = 0
        for value in pnl:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
            streak = streak + 1 if value < -1e-12 else 0
            max_streak = max(max_streak, streak)
        gross_loss = abs(sum(losses))
        return LifecycleAnalyticsSummary(
            lifecycle_ids=len(lifecycle_ids),
            opened_lifecycles=len(opened),
            terminal_lifecycles=len(terminal),
            verified_lifecycles=len(rows),
            coverage=len(rows) / len(terminal) if terminal else 0.0,
            wins=len(wins),
            losses=len(losses),
            breakeven=len(rows) - len(wins) - len(losses),
            winrate=len(wins) / len(rows) if rows else 0.0,
            realized_pnl=sum(_number(row.get("realized_pnl")) for row in rows),
            commission=sum(_number(row.get("commission")) for row in rows),
            net_pnl=sum(pnl),
            profit_factor=(sum(wins) / gross_loss if gross_loss else None),
            expectancy=(sum(pnl) / len(rows) if rows else None),
            max_drawdown=(drawdown if rows else None),
            max_loss_streak=(max_streak if rows else None),
        )

    @staticmethod
    def _lifecycle_breakdown(
        rows: list[dict[str, object]], field: str
    ) -> list[ExitAnalyticsBreakdown]:
        grouped: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get(field) or "Không xác định"), []).append(row)
        return [
            ExitAnalyticsBreakdown(
                key=key,
                closes=len(items),
                realized_pnl=sum(_number(row.get("realized_pnl")) for row in items),
                commission=sum(_number(row.get("commission")) for row in items),
                net_realized_pnl=sum(_number(row.get("net_pnl")) for row in items),
            )
            for key, items in sorted(grouped.items())
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


def _deduplicated_close_fills(
    events: Iterable[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    fills: dict[str, dict[tuple[str, str], dict[str, object]]] = {}
    for row in events:
        lifecycle_id = str(row.get("lifecycle_id") or "")
        if not lifecycle_id or row.get("event_type") not in {"PARTIAL_CLOSE", "CLOSE_FILL"}:
            continue
        order_id = str(row.get("order_id") or row.get("client_order_id") or "")
        trade_id = str(row.get("trade_id") or "")
        identity = (
            (order_id, trade_id)
            if trade_id
            else (
                order_id,
                str(
                    (
                        _event_ms(row),
                        row.get("last_fill_quantity"),
                        row.get("last_fill_price"),
                        row.get("realized_pnl"),
                    )
                ),
            )
        )
        previous = fills.setdefault(lifecycle_id, {}).get(identity)
        if previous is None or row.get("event_type") == "CLOSE_FILL":
            fills[lifecycle_id][identity] = row
    return {lifecycle_id: list(items.values()) for lifecycle_id, items in fills.items()}


def _verified_completed_lifecycles(
    events: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    rows = list(events)
    opens = {
        str(row.get("lifecycle_id")): row
        for row in rows
        if row.get("event_type") == "OPEN" and row.get("lifecycle_id")
    }
    terminal = _terminal_closes(rows)
    fills = _deduplicated_close_fills(rows)
    completed: list[dict[str, object]] = []
    for lifecycle_id, terminal_row in terminal.items():
        opened = opens.get(lifecycle_id)
        lifecycle_fills = fills.get(lifecycle_id, [])
        if not opened or not lifecycle_fills:
            continue
        realized = sum(_number(row.get("realized_pnl")) for row in lifecycle_fills)
        commission = sum(abs(_number(row.get("commission"))) for row in lifecycle_fills)
        side = str(opened.get("side") or "").upper()
        if side not in {"LONG", "SHORT"}:
            order_side = str(terminal_row.get("side") or "").upper()
            side = "LONG" if order_side == "SELL" else "SHORT" if order_side == "BUY" else ""
        completed.append(
            {
                "lifecycle_id": lifecycle_id,
                "event_at": terminal_row.get("event_at"),
                "symbol": opened.get("symbol") or terminal_row.get("symbol"),
                "side": side or "Không xác định",
                "reason": terminal_row.get("reason") or "UNKNOWN",
                "realized_pnl": realized,
                "commission": commission,
                "net_pnl": realized - commission,
            }
        )
    completed.sort(key=lambda row: _event_ms(row) or 0)
    return completed


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
