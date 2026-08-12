import hashlib
import json
import math
from datetime import UTC, datetime
from itertools import pairwise
from uuid import uuid4

from app.domain.models import (
    Candle,
    CorrelationCluster,
    CorrelationEvidence,
    CorrelationPair,
    ExchangePosition,
    ExchangeSnapshot,
    OrderPlan,
    PortfolioRiskAudit,
    PortfolioRiskPosition,
    PortfolioRiskSnapshot,
)


class PortfolioRiskEngine:
    """Deterministic Phase 7 accounting. It observes only; it never enforces."""

    def snapshot(
        self,
        exchange: ExchangeSnapshot,
        *,
        max_open_risk_fraction: float,
        max_exposure_fraction: float,
        max_symbol_exposure_fraction: float = 0.20,
        max_directional_exposure_fraction: float = 0.30,
        max_symbol_open_risk_fraction: float = 0.015,
        correlation_candles: dict[str, list[Candle]] | None = None,
        correlation_interval: str = "15m",
        correlation_lookback: int = 60,
        correlation_threshold: float = 0.80,
        correlation_closed_at: int | None = None,
    ) -> PortfolioRiskSnapshot:
        equity = max(exchange.balance.margin_balance or exchange.balance.balance, 0.0)
        lifecycles = {item.symbol: item for item in exchange.lifecycles}
        items: list[PortfolioRiskPosition] = []
        reasons: list[str] = []
        long_notional = short_notional = open_risk = 0.0
        for position in sorted(exchange.positions, key=lambda item: (item.symbol, item.side)):
            price = position.mark_price or position.entry_price
            quantity = abs(position.quantity)
            notional = quantity * price
            side = position.side.upper()
            long_notional += notional if side == "LONG" else 0.0
            short_notional += notional if side == "SHORT" else 0.0
            lifecycle = lifecycles.get(position.symbol)
            stop = lifecycle.active_stop if lifecycle else None
            matching = [
                order.stop_price
                for order in exchange.orders
                if order.symbol == position.symbol
                and order.status == "NEW"
                and "STOP" in order.order_type
                and "TAKE_PROFIT" not in order.order_type
                and order.stop_price
            ]
            if len(matching) != 1:
                stop = None
                if len(matching) > 1:
                    reasons.append(
                        f"{position.symbol} có nhiều Stop Loss đang mở, không thể xác minh"
                    )
            elif stop is None or abs(stop - matching[0]) > 1e-9:
                stop = matching[0]
            protected = stop is not None and (
                (side == "LONG" and stop < position.entry_price)
                or (side == "SHORT" and stop > position.entry_price)
            )
            risk_amount = (
                abs(position.entry_price - stop) * quantity if protected and stop else None
            )
            if risk_amount is None:
                reasons.append(f"{position.symbol} chưa có Stop Loss hợp lệ để tính open risk")
            else:
                open_risk += risk_amount
            notional_fraction = notional / equity if equity else 0.0
            risk_fraction = risk_amount / equity if equity and risk_amount is not None else None
            if notional_fraction > max_symbol_exposure_fraction:
                reasons.append(f"{position.symbol} vượt giới hạn tập trung theo symbol")
            if risk_fraction is not None and risk_fraction > max_symbol_open_risk_fraction:
                reasons.append(f"{position.symbol} vượt giới hạn open risk theo symbol")
            items.append(
                PortfolioRiskPosition(
                    symbol=position.symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=position.entry_price,
                    mark_price=price,
                    stop_loss=stop,
                    notional=notional,
                    open_risk=risk_amount,
                    protected=protected,
                    notional_fraction=notional_fraction,
                    risk_fraction=risk_fraction,
                )
            )
        gross = long_notional + short_notional
        limit = equity * max_open_risk_fraction
        exposure_limit = equity * max_exposure_fraction
        if equity <= 0:
            reasons.append("Không có equity hợp lệ để tính ngân sách danh mục")
        if open_risk > limit:
            reasons.append("Tổng open risk vượt ngân sách")
        if gross > exposure_limit:
            reasons.append("Gross exposure vượt giới hạn")
        if equity and long_notional / equity > max_directional_exposure_fraction:
            reasons.append("Tổng tập trung phía LONG vượt giới hạn")
        if equity and short_notional / equity > max_directional_exposure_fraction:
            reasons.append("Tổng tập trung phía SHORT vượt giới hạn")
        correlation = self._correlation_evidence(
            items,
            equity,
            correlation_candles,
            interval=correlation_interval,
            lookback=correlation_lookback,
            threshold=correlation_threshold,
            closed_at=correlation_closed_at,
        )
        reasons.extend(correlation.reasons)
        reasons = list(dict.fromkeys(reasons))
        return PortfolioRiskSnapshot(
            generated_at=datetime.now(UTC),
            equity=equity,
            long_notional=long_notional,
            short_notional=short_notional,
            gross_exposure=gross,
            net_exposure=long_notional - short_notional,
            gross_exposure_fraction=gross / equity if equity else 0.0,
            net_exposure_fraction=(long_notional - short_notional) / equity if equity else 0.0,
            open_risk=open_risk,
            open_risk_fraction=open_risk / equity if equity else 0.0,
            open_risk_limit=limit,
            open_risk_remaining=max(0.0, limit - open_risk),
            exposure_limit=exposure_limit,
            max_symbol_exposure_fraction=max_symbol_exposure_fraction,
            max_directional_exposure_fraction=max_directional_exposure_fraction,
            max_symbol_open_risk_fraction=max_symbol_open_risk_fraction,
            positions=items,
            correlation=correlation,
            reasons=reasons,
            would_reject_new_entries=bool(reasons),
        )

    @staticmethod
    def _correlation_evidence(
        positions: list[PortfolioRiskPosition],
        equity: float,
        candles: dict[str, list[Candle]] | None,
        *,
        interval: str,
        lookback: int,
        threshold: float,
        closed_at: int | None,
    ) -> CorrelationEvidence:
        symbols = sorted({item.symbol for item in positions})
        lookback = min(240, max(30, lookback))
        threshold = min(1.0, max(0.0, threshold))
        if candles is None:
            return CorrelationEvidence(interval=interval, lookback=lookback, threshold=threshold)
        if not symbols:
            return CorrelationEvidence(
                status="COMPLETE",
                interval=interval,
                lookback=lookback,
                threshold=threshold,
                closed_at=closed_at,
            )
        covered, missing, returns = [], [], {}
        reference_times: tuple[int, ...] | None = None
        for symbol in symbols:
            rows = sorted(candles.get(symbol, []), key=lambda row: row.open_time)
            valid = (
                len(rows) == lookback + 1
                and all(row.close > 0 for row in rows)
                and all(a.close_time < b.open_time for a, b in pairwise(rows))
                and (closed_at is None or all(row.close_time < closed_at for row in rows))
            )
            times = tuple(row.open_time for row in rows)
            if valid and reference_times is None:
                reference_times = times
            if not valid or times != reference_times:
                missing.append(symbol)
                continue
            covered.append(symbol)
            returns[symbol] = [math.log(b.close / a.close) for a, b in pairwise(rows)]
        evidence = CorrelationEvidence(
            status="COMPLETE" if not missing else "INCOMPLETE",
            interval=interval,
            lookback=lookback,
            threshold=threshold,
            closed_at=closed_at,
            covered_symbols=covered,
            missing_symbols=missing,
        )
        if missing:
            evidence.reasons.append(
                "Không đủ dữ liệu nến đã đóng để đánh giá tương quan: " + ", ".join(missing)
            )
            return evidence
        sides = {item.symbol: item.side for item in positions}
        notionals = {item.symbol: item.notional for item in positions}
        edges: dict[str, set[str]] = {symbol: set() for symbol in symbols}
        adjustment = 0.0
        for index, left in enumerate(symbols):
            for right in symbols[index + 1 :]:
                xs, ys = returns[left], returns[right]
                mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
                numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
                dx = sum((x - mx) ** 2 for x in xs)
                dy = sum((y - my) ** 2 for y in ys)
                corr = numerator / math.sqrt(dx * dy) if dx > 0 and dy > 0 else 0.0
                corr = max(-1.0, min(1.0, corr))
                same = sides[left] == sides[right]
                evidence.pairs.append(
                    CorrelationPair(
                        symbol_a=left,
                        symbol_b=right,
                        correlation=round(corr, 8),
                        observations=lookback,
                        same_direction=same,
                    )
                )
                effective = corr if same else -corr
                if effective >= threshold:
                    edges[left].add(right)
                    edges[right].add(left)
                    adjustment += effective * min(notionals[left], notionals[right])
        remaining = set(symbols)
        while remaining:
            seed = min(remaining)
            stack = [seed]
            component = set()
            while stack:
                node = stack.pop()
                if node in component:
                    continue
                component.add(node)
                stack.extend(sorted(edges[node] - component, reverse=True))
            remaining -= component
            if len(component) > 1:
                amount = sum(notionals[item] for item in component)
                evidence.clusters.append(
                    CorrelationCluster(
                        symbols=sorted(component),
                        notional=amount,
                        notional_fraction=amount / equity if equity else 0.0,
                    )
                )
        gross = sum(notionals.values())
        evidence.adjusted_exposure = gross + adjustment
        evidence.adjusted_exposure_fraction = evidence.adjusted_exposure / equity if equity else 0.0
        return evidence

    @staticmethod
    def _decision_state(snapshot: PortfolioRiskSnapshot) -> dict[str, object]:
        """Stable audit identity: ignore mark/equity noise, retain safety-relevant state."""
        return {
            "mode": snapshot.mode,
            "enforcement_enabled": snapshot.enforcement_enabled,
            "would_reject_new_entries": snapshot.would_reject_new_entries,
            "reasons": snapshot.reasons,
            "positions": [
                {
                    "symbol": item.symbol,
                    "side": item.side,
                    "quantity": item.quantity,
                    "entry_price": item.entry_price,
                    "stop_loss": item.stop_loss,
                    "protected": item.protected,
                }
                for item in snapshot.positions
            ],
            "correlation": {
                "status": snapshot.correlation.status,
                "interval": snapshot.correlation.interval,
                "lookback": snapshot.correlation.lookback,
                "threshold": snapshot.correlation.threshold,
                "covered_symbols": snapshot.correlation.covered_symbols,
                "missing_symbols": snapshot.correlation.missing_symbols,
                "pairs": [
                    {
                        "symbol_a": pair.symbol_a,
                        "symbol_b": pair.symbol_b,
                        "correlation": pair.correlation,
                        "same_direction": pair.same_direction,
                    }
                    for pair in snapshot.correlation.pairs
                ],
                "clusters": [cluster.symbols for cluster in snapshot.correlation.clusters],
            },
            "limits": {
                "open_risk_fraction": snapshot.open_risk_limit / snapshot.equity
                if snapshot.equity
                else 0.0,
                "exposure_fraction": snapshot.exposure_limit / snapshot.equity
                if snapshot.equity
                else 0.0,
                "symbol_exposure_fraction": snapshot.max_symbol_exposure_fraction,
                "directional_exposure_fraction": snapshot.max_directional_exposure_fraction,
                "symbol_open_risk_fraction": snapshot.max_symbol_open_risk_fraction,
            },
        }

    def audit_snapshot(self, exchange: ExchangeSnapshot, **limits: float) -> PortfolioRiskAudit:
        before = self.snapshot(exchange, **limits)
        canonical = {
            "event": "SNAPSHOT",
            "decision": "OBSERVED",
            "state": self._decision_state(before),
        }
        fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        return PortfolioRiskAudit(
            audit_id=f"pra-{uuid4().hex}",
            event="SNAPSHOT",
            decision="OBSERVED",
            reasons=before.reasons,
            before=before,
            fingerprint=fingerprint,
        )

    def evaluate_plan(
        self, exchange: ExchangeSnapshot, plan: OrderPlan, **limits: float
    ) -> PortfolioRiskAudit:
        before = self.snapshot(exchange, **limits)
        candidate = ExchangePosition(
            symbol=plan.symbol,
            side=plan.side.value,
            quantity=plan.quantity,
            entry_price=plan.entry_price,
            mark_price=plan.entry_price,
        )
        projected = exchange.model_copy(deep=True)
        projected.positions.append(candidate)
        # A candidate plan has a deterministic SL, represented as a lifecycle-equivalent order.
        from app.domain.models import ExchangeOrder

        projected.orders.append(
            ExchangeOrder(
                symbol=plan.symbol,
                order_id=f"shadow-{uuid4().hex}",
                client_order_id=f"shadow-{plan.client_order_id}",
                side="SELL" if plan.side.value == "LONG" else "BUY",
                order_type="STOP_MARKET",
                status="NEW",
                quantity=plan.quantity,
                reduce_only=True,
                stop_price=plan.stop_loss,
            )
        )
        after = self.snapshot(projected, **limits)
        reasons = [reason for reason in after.reasons if reason not in before.reasons]
        decision = "WOULD_REJECT" if reasons or before.would_reject_new_entries else "WOULD_ALLOW"
        if before.would_reject_new_entries:
            reasons = list(dict.fromkeys(before.reasons + reasons))
        candidate_payload = {
            "symbol": plan.symbol,
            "side": plan.side.value,
            "quantity": plan.quantity,
            "entry_price": plan.entry_price,
            "stop_loss": plan.stop_loss,
            "notional": plan.quantity * plan.entry_price,
            "open_risk": plan.quantity * abs(plan.entry_price - plan.stop_loss),
        }
        canonical = {
            "event": "PRE_TRADE",
            "symbol": plan.symbol,
            "side": plan.side.value,
            "decision": decision,
            "reasons": reasons,
            "before": self._decision_state(before),
            "after": self._decision_state(after),
            "candidate": candidate_payload,
        }
        fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        return PortfolioRiskAudit(
            audit_id=f"pra-{uuid4().hex}",
            event="PRE_TRADE",
            symbol=plan.symbol,
            side=plan.side.value,
            decision=decision,
            reasons=reasons,
            before=before,
            after=after,
            candidate=candidate_payload,
            fingerprint=fingerprint,
        )
