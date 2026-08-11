import asyncio
from collections.abc import Awaitable, Callable

from app.domain.models import AiDecision, Side, SignalAction, StrategySignal


class AiEvaluator:
    """AI sees market/strategy context only; it has no Binance client dependency."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        timeout_seconds: float = 3.0,
        provider: Callable[[StrategySignal], Awaitable[AiDecision]] | None = None,
    ) -> None:
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.provider = provider

    async def decide(self, signal: StrategySignal) -> AiDecision:
        if not self.enabled or self.provider is None:
            return self._deterministic(signal)
        try:
            decision = await asyncio.wait_for(self.provider(signal), timeout=self.timeout_seconds)
        except TimeoutError:
            return AiDecision(
                action=SignalAction.NO_TRADE,
                confidence=0.0,
                strategy=signal.strategy,
                reasons=["AI timeout, fallback NO_TRADE"],
                risk_flags=["AI_TIMEOUT"],
            )
        return self._sanitize(decision, signal)

    async def score(self, signal: StrategySignal) -> StrategySignal:
        decision = await self.decide(signal)
        if decision.action == SignalAction.NO_TRADE:
            return signal.model_copy(update={"confidence": 0.0, "metadata": {**signal.metadata, "ai_action": "NO_TRADE"}})
        side = Side.LONG if decision.action == SignalAction.LONG else Side.SHORT
        return signal.model_copy(
            update={
                "side": side,
                "confidence": min(signal.confidence, decision.confidence),
                "strategy": decision.strategy,
                "metadata": {
                    **signal.metadata,
                    "ai_action": decision.action.value,
                    "ai_reasons": " | ".join(decision.reasons[:4]),
                    "ai_risk_flags": ",".join(decision.risk_flags),
                },
            }
        )

    def _deterministic(self, signal: StrategySignal) -> AiDecision:
        action = SignalAction.LONG if signal.side == Side.LONG else SignalAction.SHORT
        flags: list[str] = []
        if signal.confidence < 0.55:
            action = SignalAction.NO_TRADE
            flags.append("LOW_CONFIDENCE")
        return AiDecision(
            action=action,
            confidence=signal.confidence,
            strategy=signal.strategy,
            reasons=["Deterministic fallback, không có quyền gửi order hoặc đổi risk"],
            risk_flags=flags,
        )

    @staticmethod
    def _sanitize(decision: AiDecision, signal: StrategySignal) -> AiDecision:
        if decision.action not in {SignalAction.LONG, SignalAction.SHORT, SignalAction.NO_TRADE}:
            return AiDecision(
                action=SignalAction.NO_TRADE,
                confidence=0.0,
                strategy=signal.strategy,
                reasons=["AI response ngoài schema cho phép"],
                risk_flags=["INVALID_AI_ACTION"],
            )
        return decision
