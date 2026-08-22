from __future__ import annotations

from typing import Any

from app.domain.models import ExchangeSnapshot, TradingMode
from app.services.exchange import BinanceFuturesAdapter
from app.services.execution import ExecutionService
from app.services.storage import Storage


class ExchangeReconciliationService:
    """Small orchestration layer for exchange/local position reconciliation."""

    def __init__(self, storage: Storage, execution: ExecutionService) -> None:
        self.storage = storage
        self.execution = execution

    async def reconcile(
        self,
        *,
        adapter: BinanceFuturesAdapter,
        mode: TradingMode,
    ) -> ExchangeSnapshot:
        snapshot = await adapter.snapshot()
        exchange_symbols = {
            position.symbol for position in snapshot.positions if abs(position.quantity) > 0
        }
        pruned = self.execution.prune_positions_not_on_exchange(exchange_symbols)
        if pruned:
            await self.storage.log(
                "Đóng vị thế local không còn trên Binance (manual reconcile)",
                {"mode": mode.value, "symbols": pruned},
                level="WARNING",
            )
        return await adapter.reconcile(self._local_open_positions())

    def _local_open_positions(self) -> list[dict[str, Any]]:
        return [position.model_dump(mode="json") for position in self.execution.open_positions()]
