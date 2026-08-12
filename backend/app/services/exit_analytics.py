from collections.abc import Iterable

from app.domain.models import (
    ExitAnalyticsAvailability,
    ExitAnalyticsBreakdown,
    ExitAnalyticsResponse,
    ExitAnalyticsSummary,
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
            closes_by_lifecycle[lifecycle_id] = closes_by_lifecycle.get(
                lifecycle_id, 0.0
            ) + _number(row.get("realized_pnl"))
        matched = [key for key in closes_by_lifecycle if key in opens]
        covered_risk = sum(_number(opens[key].get("initial_risk")) for key in matched)
        covered_pnl = sum(closes_by_lifecycle[key] for key in matched)
        realized_r = covered_pnl / covered_risk if covered_risk > 0 else None
        coverage = len(matched) / len(closes_by_lifecycle) if closes_by_lifecycle else 0.0

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
            realized_r_availability=ExitAnalyticsAvailability(
                available=realized_r is not None,
                coverage=coverage,
                reason=None
                if realized_r is not None
                else "Recorder chưa có lifecycle đóng khớp với initial risk đã xác minh.",
            ),
            mae_availability=self._excursion_unavailable(),
            mfe_availability=self._excursion_unavailable(),
            missed_r_availability=self._excursion_unavailable(),
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
    def _excursion_unavailable() -> ExitAnalyticsAvailability:
        return ExitAnalyticsAvailability(
            available=False,
            coverage=0,
            reason="Chưa có lifecycle entry/exit và chuỗi nến timestamp đáng tin cậy để tính.",
        )


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


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
