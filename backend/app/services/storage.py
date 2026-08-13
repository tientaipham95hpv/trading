from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class FillRow(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PositionRow(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class TradeRow(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    pnl: Mapped[float] = mapped_column(Float, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PnlRow(Base):
    __tablename__ = "pnl"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class StabilitySnapshotRow(Base):
    __tablename__ = "stability_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score: Mapped[int] = mapped_column(Integer, index=True)
    verdict: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class PortfolioRiskAuditRow(Base):
    __tablename__ = "portfolio_risk_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    event: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class LifecycleAnalyticsEventRow(Base):
    __tablename__ = "lifecycle_analytics_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    lifecycle_id: Mapped[str] = mapped_column(String(96), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class SmartEntryEventRow(Base):
    __tablename__ = "smart_entry_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class SmartEntryOutcomeRow(Base):
    __tablename__ = "smart_entry_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    decision_event_key: Mapped[str] = mapped_column(String(160), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    horizon: Mapped[int] = mapped_column(Integer, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class SmartEntryCollectionStateRow(Base):
    __tablename__ = "smart_entry_collection_states"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_event_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class IncidentRow(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_key: Mapped[str] = mapped_column(String(96), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class LogRow(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


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
            await self._save_order_bundle_in_session(
                session, order, fills, positions, trades, performance
            )
            await session.commit()

    async def save_lifecycle_analytics_event(self, payload: dict[str, Any]) -> bool:
        """Persist an immutable lifecycle fact; duplicate stream events are ignored."""
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(LifecycleAnalyticsEventRow.id).where(
                        LifecycleAnalyticsEventRow.event_key == payload["event_key"]
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False
            event_at = payload.get("event_at")
            if isinstance(event_at, str):
                event_at = datetime.fromisoformat(event_at)
            session.add(
                LifecycleAnalyticsEventRow(
                    event_key=str(payload["event_key"]),
                    mode=str(payload["mode"]),
                    lifecycle_id=str(payload["lifecycle_id"]),
                    symbol=str(payload["symbol"]),
                    event_type=str(payload["event_type"]),
                    payload=payload,
                    event_at=event_at or datetime.now(UTC),
                )
            )
            count = (
                await session.execute(select(func.count(LifecycleAnalyticsEventRow.id)))
            ).scalar_one()
            if count >= 20_000:
                excess = count - 20_000 + 1
                oldest_ids = list(
                    (
                        await session.execute(
                            select(LifecycleAnalyticsEventRow.id)
                            .order_by(LifecycleAnalyticsEventRow.id.asc())
                            .limit(excess)
                        )
                    ).scalars()
                )
                await session.execute(
                    delete(LifecycleAnalyticsEventRow).where(
                        LifecycleAnalyticsEventRow.id.in_(oldest_ids)
                    )
                )
            await session.commit()
            return True

    async def lifecycle_analytics_events(
        self, *, mode: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            query = select(LifecycleAnalyticsEventRow)
            if mode:
                query = query.where(LifecycleAnalyticsEventRow.mode == mode)
            rows = (
                await session.execute(
                    query.order_by(LifecycleAnalyticsEventRow.event_at.desc()).limit(limit)
                )
            ).scalars()
            return [row.payload for row in rows]

    async def save_smart_entry_event(self, payload: dict[str, Any]) -> bool:
        """Persist immutable shadow evidence without feeding strategy behavior."""
        async with self.session_factory() as session:
            exists = (
                await session.execute(
                    select(SmartEntryEventRow.id).where(
                        SmartEntryEventRow.event_key == payload["event_key"]
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                return False
            decision_at = payload.get("decision_at")
            if isinstance(decision_at, str):
                decision_at = datetime.fromisoformat(decision_at)
            session.add(
                SmartEntryEventRow(
                    event_key=str(payload["event_key"]),
                    mode=str(payload["mode"]),
                    symbol=str(payload["symbol"]),
                    decision=str(payload["decision"]),
                    payload=payload,
                    decision_at=decision_at or datetime.now(UTC),
                )
            )
            await session.flush()
            excess = (
                await session.execute(select(func.count()).select_from(SmartEntryEventRow))
            ).scalar_one() - 10_000
            if excess > 0:
                oldest = (
                    select(SmartEntryEventRow.id)
                    .order_by(SmartEntryEventRow.id.asc())
                    .limit(excess)
                )
                await session.execute(
                    delete(SmartEntryEventRow).where(SmartEntryEventRow.id.in_(oldest))
                )
            await session.commit()
            return True

    async def smart_entry_events(
        self, *, mode: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            query = select(SmartEntryEventRow)
            if mode:
                query = query.where(SmartEntryEventRow.mode == mode)
            rows = (
                await session.execute(
                    query.order_by(SmartEntryEventRow.decision_at.desc()).limit(limit)
                )
            ).scalars()
            return [row.payload for row in rows]

    async def pending_smart_entry_events(
        self, *, mode: str, now: datetime, limit: int = 25
    ) -> list[dict[str, Any]]:
        """Return oldest incomplete decisions whose retry window is open."""
        async with self.session_factory() as session:
            outcome_count = (
                select(
                    SmartEntryOutcomeRow.decision_event_key,
                    func.count(SmartEntryOutcomeRow.id).label("outcome_count"),
                )
                .where(SmartEntryOutcomeRow.mode == mode)
                .group_by(SmartEntryOutcomeRow.decision_event_key)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(SmartEntryEventRow)
                    .outerjoin(
                        outcome_count,
                        outcome_count.c.decision_event_key == SmartEntryEventRow.event_key,
                    )
                    .outerjoin(
                        SmartEntryCollectionStateRow,
                        SmartEntryCollectionStateRow.decision_event_key
                        == SmartEntryEventRow.event_key,
                    )
                    .where(
                        SmartEntryEventRow.mode == mode,
                        func.coalesce(outcome_count.c.outcome_count, 0) < 3,
                        (SmartEntryCollectionStateRow.status.is_(None))
                        | (SmartEntryCollectionStateRow.status != "PERMANENT_ERROR"),
                        (SmartEntryCollectionStateRow.next_retry_at.is_(None))
                        | (SmartEntryCollectionStateRow.next_retry_at <= now),
                    )
                    .order_by(SmartEntryEventRow.decision_at.asc())
                    .limit(limit)
                )
            ).scalars()
            return [row.payload for row in rows]

    async def smart_entry_collection_state(self, decision_event_key: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(SmartEntryCollectionStateRow).where(
                        SmartEntryCollectionStateRow.decision_event_key == decision_event_key
                    )
                )
            ).scalar_one_or_none()
            return (
                None
                if row is None
                else {
                    "status": row.status,
                    "attempts": row.attempts,
                    "next_retry_at": row.next_retry_at,
                    "last_error": row.last_error,
                }
            )

    async def set_smart_entry_collection_state(
        self,
        *,
        decision_event_key: str,
        mode: str,
        status: str,
        attempts: int = 0,
        next_retry_at: datetime | None = None,
        last_error: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(SmartEntryCollectionStateRow).where(
                        SmartEntryCollectionStateRow.decision_event_key == decision_event_key
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = SmartEntryCollectionStateRow(
                    decision_event_key=decision_event_key, mode=mode, status=status
                )
                session.add(row)
            row.status = status
            row.attempts = attempts
            row.next_retry_at = next_retry_at
            row.last_error = last_error
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def smart_entry_collection_coverage(self, *, mode: str) -> dict[str, Any]:
        async with self.session_factory() as session:
            events = list(
                (
                    await session.execute(
                        select(SmartEntryEventRow.event_key, SmartEntryEventRow.decision_at).where(
                            SmartEntryEventRow.mode == mode
                        )
                    )
                ).all()
            )
            counts = dict(
                (
                    await session.execute(
                        select(
                            SmartEntryOutcomeRow.decision_event_key,
                            func.count(SmartEntryOutcomeRow.id),
                        )
                        .where(SmartEntryOutcomeRow.mode == mode)
                        .group_by(SmartEntryOutcomeRow.decision_event_key)
                    )
                ).all()
            )
            states = {
                row.decision_event_key: row
                for row in (
                    await session.execute(
                        select(SmartEntryCollectionStateRow).where(
                            SmartEntryCollectionStateRow.mode == mode
                        )
                    )
                ).scalars()
            }
            complete = sum(counts.get(key, 0) >= 3 for key, _ in events)
            permanent = sum(
                bool(states.get(key) and states[key].status == "PERMANENT_ERROR")
                for key, _ in events
            )
            retrying = sum(
                bool(states.get(key) and states[key].status == "RETRYING") for key, _ in events
            )
            pending_dates = [
                when
                for key, when in events
                if counts.get(key, 0) < 3
                and not (states.get(key) and states[key].status == "PERMANENT_ERROR")
            ]
            horizon_rows = (
                await session.execute(
                    select(SmartEntryOutcomeRow.horizon, func.count(SmartEntryOutcomeRow.id))
                    .where(SmartEntryOutcomeRow.mode == mode)
                    .group_by(SmartEntryOutcomeRow.horizon)
                )
            ).all()
            horizons = {str(horizon): count for horizon, count in horizon_rows}
            return {
                "total_decisions": len(events),
                "complete_decisions": complete,
                "pending_decisions": len(events) - complete - permanent,
                "retrying_decisions": retrying,
                "permanent_errors": permanent,
                "completion_ratio": complete / len(events) if events else 0,
                "oldest_pending_at": min(pending_dates).isoformat() if pending_dates else None,
                "outcomes_by_horizon": {str(h): horizons.get(str(h), 0) for h in (4, 12, 24)},
            }

    async def save_smart_entry_outcome(self, payload: dict[str, Any]) -> bool:
        async with self.session_factory() as session:
            exists = (
                await session.execute(
                    select(SmartEntryOutcomeRow.id).where(
                        SmartEntryOutcomeRow.event_key == payload["event_key"]
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                return False
            session.add(
                SmartEntryOutcomeRow(
                    event_key=str(payload["event_key"]),
                    decision_event_key=str(payload["decision_event_key"]),
                    mode=str(payload["mode"]),
                    symbol=str(payload["symbol"]),
                    horizon=int(payload["horizon"]),
                    payload=payload,
                )
            )
            await session.flush()
            excess = (
                await session.execute(select(func.count()).select_from(SmartEntryOutcomeRow))
            ).scalar_one() - 30_000
            if excess > 0:
                oldest = (
                    select(SmartEntryOutcomeRow.id)
                    .order_by(SmartEntryOutcomeRow.id.asc())
                    .limit(excess)
                )
                await session.execute(
                    delete(SmartEntryOutcomeRow).where(SmartEntryOutcomeRow.id.in_(oldest))
                )
            await session.commit()
            return True

    async def smart_entry_outcomes(
        self, *, mode: str, decision_keys: list[str] | None = None
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            query = select(SmartEntryOutcomeRow).where(SmartEntryOutcomeRow.mode == mode)
            if decision_keys is not None:
                if not decision_keys:
                    return []
                query = query.where(SmartEntryOutcomeRow.decision_event_key.in_(decision_keys))
            rows = (await session.execute(query.order_by(SmartEntryOutcomeRow.id.asc()))).scalars()
            return [row.payload for row in rows]

    async def log(
        self, message: str, payload: dict[str, Any] | None = None, level: str = "INFO"
    ) -> None:
        async with self.session_factory() as session:
            session.add(LogRow(level=level, message=message, payload=payload))
            await session.commit()

    async def save_stability_snapshot(self, payload: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            latest = (
                await session.execute(
                    select(StabilitySnapshotRow).order_by(StabilitySnapshotRow.id.desc()).limit(1)
                )
            ).scalar_one_or_none()
            if (
                latest
                and latest.score == int(payload["score"])
                and latest.verdict == str(payload["verdict"])
            ):
                return
            session.add(
                StabilitySnapshotRow(
                    score=int(payload["score"]), verdict=str(payload["verdict"]), payload=payload
                )
            )
            await session.commit()

    async def save_portfolio_risk_audit(self, payload: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            if payload["event"] == "SNAPSHOT":
                latest = (
                    await session.execute(
                        select(PortfolioRiskAuditRow)
                        .where(PortfolioRiskAuditRow.event == "SNAPSHOT")
                        .order_by(PortfolioRiskAuditRow.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if latest and latest.fingerprint == payload["fingerprint"]:
                    return
            session.add(
                PortfolioRiskAuditRow(
                    audit_id=str(payload["audit_id"]),
                    event=str(payload["event"]),
                    symbol=payload.get("symbol"),
                    decision=str(payload["decision"]),
                    fingerprint=str(payload["fingerprint"]),
                    payload=payload,
                )
            )
            await session.flush()
            excess = (
                await session.execute(select(func.count()).select_from(PortfolioRiskAuditRow))
            ).scalar_one() - 5000
            if excess > 0:
                oldest_ids = (
                    select(PortfolioRiskAuditRow.id)
                    .order_by(PortfolioRiskAuditRow.id.asc())
                    .limit(excess)
                )
                await session.execute(
                    delete(PortfolioRiskAuditRow).where(PortfolioRiskAuditRow.id.in_(oldest_ids))
                )
            await session.commit()

    async def portfolio_risk_audit_summary(self) -> dict[str, Any]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        PortfolioRiskAuditRow.event,
                        PortfolioRiskAuditRow.decision,
                        func.count(PortfolioRiskAuditRow.id),
                    ).group_by(PortfolioRiskAuditRow.event, PortfolioRiskAuditRow.decision)
                )
            ).all()
            return {
                "total": sum(count for _, _, count in rows),
                "by_decision": {
                    decision: count for event, decision, count in rows if event == "PRE_TRADE"
                },
                "snapshots": sum(count for event, _, count in rows if event == "SNAPSHOT"),
            }

    async def portfolio_risk_audits(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(PortfolioRiskAuditRow)
                    .order_by(PortfolioRiskAuditRow.id.desc())
                    .limit(limit)
                )
            ).scalars()
            return [row.payload for row in rows]

    async def sync_incidents(self, active: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        changed: list[dict[str, Any]] = []
        async with self.session_factory() as session:
            open_rows = list(
                (
                    await session.execute(select(IncidentRow).where(IncidentRow.status == "OPEN"))
                ).scalars()
            )
            by_key = {row.incident_key: row for row in open_rows}
            for key, data in active.items():
                row = by_key.get(key)
                if row is None:
                    row = IncidentRow(
                        incident_key=key,
                        severity=str(data["severity"]),
                        status="OPEN",
                        message=str(data["message"]),
                        payload=data.get("payload"),
                        opened_at=now,
                        last_seen_at=now,
                    )
                    session.add(row)
                    changed.append({"event": "OPENED", "key": key, **data})
                else:
                    row.last_seen_at = now
                    row.message = str(data["message"])
                    row.payload = data.get("payload")
            for row in open_rows:
                if row.incident_key not in active:
                    row.status = "RESOLVED"
                    row.resolved_at = now
                    row.last_seen_at = now
                    changed.append(
                        {
                            "event": "RESOLVED",
                            "key": row.incident_key,
                            "severity": row.severity,
                            "message": row.message,
                        }
                    )
            await session.commit()
        return changed

    async def list_incidents(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(IncidentRow).order_by(IncidentRow.id.desc()).limit(limit)
                    )
                ).scalars()
            )
            return [
                {
                    "id": row.id,
                    "key": row.incident_key,
                    "severity": row.severity,
                    "status": row.status,
                    "message": row.message,
                    "payload": row.payload,
                    "opened_at": row.opened_at.isoformat(),
                    "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                    "last_seen_at": row.last_seen_at.isoformat(),
                }
                for row in rows
            ]

    async def stability_history(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(StabilitySnapshotRow)
                        .order_by(StabilitySnapshotRow.id.desc())
                        .limit(limit)
                    )
                ).scalars()
            )
            return [row.payload for row in rows]

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
                    status=position.get("status", "OPEN"),
                    payload=position,
                    updated_at=datetime.now(UTC),
                )
            )
        for trade in trades:
            session.add(TradeRow(symbol=trade["symbol"], pnl=trade["net_pnl"], payload=trade))
        if performance:
            session.add(PnlRow(payload=performance))
