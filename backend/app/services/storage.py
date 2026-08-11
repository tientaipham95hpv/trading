from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class FillRow(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PositionRow(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class TradeRow(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    pnl: Mapped[float] = mapped_column(Float, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PnlRow(Base):
    __tablename__ = "pnl"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class LogRow(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Storage:
    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def save_signal(self, payload: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            session.add(SignalRow(symbol=payload["symbol"], payload=payload))
            await session.commit()

    async def save_order_bundle(
        self,
        *,
        order: dict[str, Any],
        fills: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        performance: dict[str, Any] | None = None,
    ) -> None:
        async with self.session_factory() as session:
            await self._save_order_bundle_in_session(session, order, fills, positions, trades, performance)
            await session.commit()

    async def log(self, message: str, payload: dict[str, Any] | None = None, level: str = "INFO") -> None:
        async with self.session_factory() as session:
            session.add(LogRow(level=level, message=message, payload=payload))
            await session.commit()

    async def list_payloads(self, table: str, limit: int = 100) -> list[dict[str, Any]]:
        model = {
            "signals": SignalRow,
            "orders": OrderRow,
            "fills": FillRow,
            "positions": PositionRow,
            "trades": TradeRow,
            "pnl": PnlRow,
            "logs": LogRow,
        }[table]
        async with self.session_factory() as session:
            rows = (
                await session.execute(select(model).order_by(model.id.desc()).limit(limit))
            ).scalars()
            items: list[dict[str, Any]] = []
            for row in rows:
                if isinstance(row, LogRow):
                    items.append(
                        {
                            "level": row.level,
                            "message": row.message,
                            "payload": row.payload,
                            "created_at": row.created_at.isoformat(),
                        }
                    )
                else:
                    items.append(row.payload)
            return items

    async def _save_order_bundle_in_session(
        self,
        session: AsyncSession,
        order: dict[str, Any],
        fills: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        performance: dict[str, Any] | None,
    ) -> None:
        session.add(
            OrderRow(
                client_order_id=order["client_order_id"],
                symbol=order["symbol"],
                payload=order,
            )
        )
        for fill in fills:
            session.add(FillRow(symbol=fill["symbol"], payload=fill))
        for position in positions:
            session.add(
                PositionRow(
                    symbol=position["symbol"],
                    status=position["status"],
                    payload=position,
                    updated_at=datetime.now(UTC),
                )
            )
        for trade in trades:
            session.add(TradeRow(symbol=trade["symbol"], pnl=trade["net_pnl"], payload=trade))
        if performance:
            session.add(PnlRow(payload=performance))
