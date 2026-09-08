from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def event_time(event: dict[str, Any]) -> datetime:
    value = event.get("event_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def closed_lifecycle_outcomes(
    events: list[dict[str, Any]],
    *,
    open_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Reconstruct one outcome per verified OPEN without trusting fill order labels.

    Binance marks a completely filled TP order as FILLED even when the position is
    only partially closed.  Also, locally generated close orders may have a new
    client id and therefore arrive as ENTRY_FILL.  A lifecycle is considered closed
    when a later verified OPEN for the same symbol exists, or when an authoritative
    exchange snapshot says that symbol is flat.  All fills in that symbol/time
    segment are then attributed to the verified OPEN.
    """
    ordered = sorted(events, key=event_time)
    opens_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for event in ordered:
        if (
            event.get("event_type") == "OPEN"
            and event.get("risk_verifiable") is True
            and float(event.get("entry_price") or 0) > 0
        ):
            lifecycle_id = str(event.get("lifecycle_id") or "")
            symbol = str(event.get("symbol") or "").upper()
            segment_key = symbol or (f"@{lifecycle_id}" if lifecycle_id else "")
            if segment_key:
                opens_by_symbol.setdefault(segment_key, []).append(event)

    normalized_open_symbols = (
        {symbol.upper() for symbol in open_symbols} if open_symbols is not None else None
    )
    outcomes: list[dict[str, Any]] = []
    for segment_key, opens in opens_by_symbol.items():
        symbol = segment_key if not segment_key.startswith("@") else ""
        lifecycle_ids = {str(event.get("lifecycle_id") or "") for event in opens}
        symbol_events = [
            event
            for event in ordered
            if (symbol and str(event.get("symbol") or "").upper() == symbol)
            or str(event.get("lifecycle_id") or "") in lifecycle_ids
        ]
        for index, open_event in enumerate(opens):
            started_at = event_time(open_event)
            next_open_at = event_time(opens[index + 1]) if index + 1 < len(opens) else None
            segment = [
                event
                for event in symbol_events
                if event_time(event) >= started_at
                and (next_open_at is None or event_time(event) < next_open_at)
            ]
            fills = [
                event
                for event in segment
                if event.get("event_type") in {"ENTRY_FILL", "PARTIAL_CLOSE", "CLOSE_FILL"}
            ]
            if next_open_at is not None:
                closed = True
            elif normalized_open_symbols is not None:
                closed = not symbol or symbol not in normalized_open_symbols
            else:
                closed = any(event.get("event_type") == "CLOSE_FILL" for event in segment)
            if not closed or not fills:
                continue

            realized_pnl = sum(float(event.get("realized_pnl") or 0) for event in fills)
            commission = sum(abs(float(event.get("commission") or 0)) for event in fills)
            closing_fills = [
                event
                for event in fills
                if event.get("event_type") in {"PARTIAL_CLOSE", "CLOSE_FILL"}
                or abs(float(event.get("realized_pnl") or 0)) > 0
            ]
            closed_at = max(
                (event_time(event) for event in closing_fills),
                default=max(event_time(event) for event in fills),
            )
            entry_fills = [
                event
                for event in fills
                if event.get("event_type") == "ENTRY_FILL"
                and abs(float(event.get("realized_pnl") or 0)) == 0
            ]
            entry_quantity = sum(float(event.get("last_fill_quantity") or 0) for event in entry_fills)
            entry_notional = sum(
                float(event.get("last_fill_quantity") or 0)
                * float(event.get("last_fill_price") or 0)
                for event in entry_fills
            )
            final_reason = (
                str(closing_fills[-1].get("reason") or "Đóng vị thế")
                if closing_fills
                else "Đóng vị thế"
            )
            if final_reason == "ENTRY" and closing_fills and abs(
                float(closing_fills[-1].get("realized_pnl") or 0)
            ) > 0:
                final_reason = "MARKET_CLOSE"
            outcomes.append(
                {
                    "lifecycle_id": str(open_event.get("lifecycle_id") or ""),
                    "symbol": symbol or str(open_event.get("symbol") or "-"),
                    "side": str(open_event.get("side") or "CLOSED"),
                    "entry_price": (
                        entry_notional / entry_quantity
                        if entry_quantity > 0 and entry_notional > 0
                        else float(open_event.get("entry_price") or 0)
                    ),
                    "exit_price": float(closing_fills[-1].get("last_fill_price") or 0)
                    if closing_fills
                    else 0.0,
                    "quantity": float(open_event.get("initial_quantity") or 0),
                    "gross_pnl": realized_pnl,
                    "fee": commission,
                    "net_pnl": realized_pnl - commission,
                    "reason": final_reason,
                    "closed_at": closed_at,
                }
            )
    return sorted(outcomes, key=lambda item: item["closed_at"], reverse=True)
