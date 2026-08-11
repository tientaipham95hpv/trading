from app.domain.models import StrategySignal, SymbolCandidate


class StrategyEngine:
    async def evaluate(self, candidate: SymbolCandidate) -> StrategySignal | None:
        # Placeholder for phase-specific strategy rules.
        return None
