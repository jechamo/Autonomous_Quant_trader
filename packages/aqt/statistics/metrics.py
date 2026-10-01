"""Performance metrics. Win rate alone is never the objective: EV after costs is."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TradeMetrics:
    n_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float  # positive magnitude
    expected_value: float  # mean net return per trade
    profit_factor: float
    total_return: float
    max_drawdown: float  # negative fraction
    sharpe: float
    sortino: float
    exposure: float

    def to_dict(self) -> dict[str, float]:
        return {
            k: (None if isinstance(v, float) and not math.isfinite(v) else v)  # type: ignore[misc]
            for k, v in asdict(self).items()
        }


def max_drawdown(equity: pd.Series | np.ndarray) -> float:
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1.0).min())


def _annualised_ratio(r: np.ndarray, downside: bool, periods_per_year: int) -> float:
    if r.size < 2:
        return 0.0
    mean = r.mean()
    if downside:
        d = np.minimum(r, 0.0)
        sd = math.sqrt((d**2).mean())
    else:
        sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(mean / sd * math.sqrt(periods_per_year))


def compute_metrics(
    trade_returns: np.ndarray,
    bar_returns: pd.Series | np.ndarray | None = None,
    exposure: pd.Series | np.ndarray | None = None,
    periods_per_year: int = 252,
) -> TradeMetrics:
    tr = np.asarray(trade_returns, dtype=float)
    n = int(tr.size)
    wins, losses = tr[tr > 0], tr[tr <= 0]
    win_rate = float(wins.size / n) if n else 0.0
    avg_win = float(wins.mean()) if wins.size else 0.0
    avg_loss = float(-losses.mean()) if losses.size else 0.0
    gross_loss = float(-losses.sum())
    pf = float(wins.sum() / gross_loss) if gross_loss > 0 else (math.inf if wins.size else 0.0)

    if bar_returns is not None:
        br = np.asarray(bar_returns, dtype=float)
        equity = np.cumprod(1.0 + br)
        total = float(equity[-1] - 1.0) if equity.size else 0.0
        mdd = max_drawdown(np.concatenate([[1.0], equity]))
        sharpe = _annualised_ratio(br, False, periods_per_year)
        sortino = _annualised_ratio(br, True, periods_per_year)
    else:
        equity = np.cumprod(1.0 + tr)
        total = float(equity[-1] - 1.0) if n else 0.0
        mdd = max_drawdown(np.concatenate([[1.0], equity]))
        sharpe = sortino = 0.0

    expo = float(np.asarray(exposure, dtype=float).mean()) if exposure is not None else 0.0
    return TradeMetrics(
        n_trades=n,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expected_value=float(tr.mean()) if n else 0.0,
        profit_factor=pf,
        total_return=total,
        max_drawdown=mdd,
        sharpe=sharpe,
        sortino=sortino,
        exposure=expo,
    )
