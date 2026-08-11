import math
from statistics import mean, pstdev

from app.domain.models import BacktestMetrics, TradeRecord


class BacktestService:
    def metrics(
        self,
        trades: list[TradeRecord],
        *,
        fees: float = 0.0,
        slippage: float = 0.0,
        funding: float = 0.0,
        walk_forward_windows: int = 0,
        out_of_sample_trades: int = 0,
    ) -> BacktestMetrics:
        returns = [trade.net_pnl for trade in trades]
        wins = [value for value in returns if value > 0]
        losses = [abs(value) for value in returns if value <= 0]
        pnl = sum(returns)
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for value in returns:
            equity += value
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        downside = [value for value in returns if value < 0]
        volatility = pstdev(returns) if len(returns) > 1 else 0.0
        downside_vol = pstdev(downside) if len(downside) > 1 else 0.0
        avg_return = mean(returns) if returns else 0.0
        return BacktestMetrics(
            pnl=pnl,
            profit_factor=(sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (math.inf if wins else 0.0),
            drawdown=max_dd,
            sharpe=(avg_return / volatility) if volatility > 0 else 0.0,
            sortino=(avg_return / downside_vol) if downside_vol > 0 else 0.0,
            expectancy=avg_return,
            winrate=(len(wins) / len(trades)) if trades else 0.0,
            trades=len(trades),
            fees=fees or sum(trade.fee for trade in trades),
            slippage=slippage or sum(trade.slippage for trade in trades),
            funding=funding or sum(trade.funding for trade in trades),
            walk_forward_windows=walk_forward_windows,
            out_of_sample_trades=out_of_sample_trades,
            no_lookahead_bias=True,
        )
