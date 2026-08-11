from app.domain.models import StrategySignal


class AiEvaluator:
    """AI sees market/strategy context only; it has no Binance client dependency."""

    async def score(self, signal: StrategySignal) -> StrategySignal:
        return signal
