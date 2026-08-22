from app.domain.models import ExchangeBalance, ExchangePosition, ExchangeSnapshot, TradingMode
from app.services.reconciliation import ExchangeReconciliationService


class FakeStorage:
    def __init__(self) -> None:
        self.logs: list[tuple[str, dict, str]] = []

    async def log(self, message: str, payload=None, level: str = "INFO") -> None:
        self.logs.append((message, payload or {}, level))


class FakeExecution:
    def __init__(self) -> None:
        self.pruned_symbols: list[str] = []

    def prune_positions_not_on_exchange(self, symbols: set[str]) -> list[str]:
        self.pruned_symbols = sorted(symbols)
        return ["ETHUSDT"] if "BTCUSDT" in symbols else []

    def open_positions(self) -> list[object]:
        return [FakeLocalPosition("BTCUSDT")]


class FakeLocalPosition:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def model_dump(self, *, mode: str) -> dict[str, str]:
        return {"symbol": self.symbol, "status": "OPEN", "mode": mode}


class FakeAdapter:
    def __init__(self) -> None:
        self.reconciled_with: list[dict[str, str]] = []

    async def snapshot(self) -> ExchangeSnapshot:
        return ExchangeSnapshot(
            mode=TradingMode.DEMO,
            balance=ExchangeBalance(balance=1000),
            positions=[
                ExchangePosition(
                    symbol="BTCUSDT",
                    side="LONG",
                    quantity=0.1,
                    entry_price=100,
                )
            ],
        )

    async def reconcile(self, local_positions: list[dict[str, str]]) -> ExchangeSnapshot:
        self.reconciled_with = local_positions
        return await self.snapshot()


async def test_reconciliation_prunes_and_delegates_local_positions() -> None:
    storage = FakeStorage()
    execution = FakeExecution()
    adapter = FakeAdapter()
    service = ExchangeReconciliationService(storage, execution)  # type: ignore[arg-type]

    snapshot = await service.reconcile(adapter=adapter, mode=TradingMode.DEMO)  # type: ignore[arg-type]

    assert snapshot.positions[0].symbol == "BTCUSDT"
    assert execution.pruned_symbols == ["BTCUSDT"]
    assert adapter.reconciled_with == [{"symbol": "BTCUSDT", "status": "OPEN", "mode": "json"}]
    assert storage.logs[0][0] == "Đóng vị thế local không còn trên Binance (manual reconcile)"
    assert storage.logs[0][2] == "WARNING"
