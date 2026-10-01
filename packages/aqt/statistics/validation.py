"""Out-of-sample, walk-forward, purged CV and parameter-stability analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from aqt.backtest import CostModel, Trade, run_backtest
from aqt.statistics.confidence import mean_return_test
from aqt.strategies.dsl import StrategySpec


def split_in_out_of_sample(
    df: pd.DataFrame, oos_fraction: float = 0.3
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split; the OOS block is always the most recent data."""
    if not 0 < oos_fraction < 1:
        raise ValueError("oos_fraction must be in (0, 1)")
    cut = int(len(df) * (1 - oos_fraction))
    return df.iloc[:cut], df.iloc[cut:]


def purged_kfold_splits(
    n: int, n_splits: int = 5, embargo: int = 0
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Contiguous K-fold for time series with an embargo removed on both sides of each test fold.

    Prevents leakage from overlapping labels (trades that span fold boundaries).
    """
    if n_splits < 2 or n < n_splits:
        raise ValueError("need n >= n_splits >= 2")
    bounds = np.linspace(0, n, n_splits + 1, dtype=int)
    all_idx = np.arange(n)
    splits = []
    for k in range(n_splits):
        lo, hi = bounds[k], bounds[k + 1]
        test = all_idx[lo:hi]
        keep = (all_idx < lo - embargo) | (all_idx >= hi + embargo)
        splits.append((all_idx[keep], test))
    return splits


def _selection_score(trade_returns: np.ndarray, min_trades: int) -> float:
    if trade_returns.size < min_trades:
        return -np.inf
    return mean_return_test(trade_returns).t_stat


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    selected: str
    is_ev: float
    oos_ev: float
    oos_trades: int


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    oos_trades: list[Trade] = field(default_factory=list)

    @property
    def oos_returns(self) -> np.ndarray:
        return np.array([t.net_return for t in self.oos_trades], dtype=float)

    @property
    def efficiency(self) -> float:
        """Mean OOS EV / mean IS EV of the selected variants (1.0 = no decay)."""
        is_ev = np.mean([w.is_ev for w in self.windows]) if self.windows else 0.0
        oos_ev = np.mean([w.oos_ev for w in self.windows]) if self.windows else 0.0
        return float(oos_ev / is_ev) if is_ev > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [w.__dict__ for w in self.windows],
            "oos_trades": len(self.oos_trades),
            "oos_ev": float(self.oos_returns.mean()) if self.oos_trades else 0.0,
            "efficiency": self.efficiency,
        }


def walk_forward(
    features: pd.DataFrame,
    variants: Sequence[StrategySpec],
    n_windows: int = 5,
    anchored: bool = True,
    costs: CostModel | None = None,
    min_trades: int = 5,
) -> WalkForwardResult:
    """Re-select the best variant on each training window, then trade it on the next block."""
    if not variants:
        raise ValueError("need at least one variant")
    bounds = np.linspace(0, len(features), n_windows + 2, dtype=int)
    windows: list[WalkForwardWindow] = []
    oos_trades: list[Trade] = []
    for k in range(1, n_windows + 1):
        train_lo = 0 if anchored else bounds[k - 1]
        train = features.iloc[train_lo : bounds[k]]
        test = features.iloc[bounds[k] : bounds[k + 1]]
        if len(train) < 2 or len(test) < 2:
            continue
        best, best_score, best_ev = variants[0], -np.inf, 0.0
        for v in variants:
            tr = run_backtest(train, v, costs).trade_returns
            score = _selection_score(tr, min_trades)
            if score > best_score:
                best, best_score, best_ev = v, score, float(tr.mean()) if tr.size else 0.0
        res = run_backtest(test, best, costs)
        oos_trades.extend(res.trades)
        windows.append(
            WalkForwardWindow(
                train_start=str(train.index[0]),
                train_end=str(train.index[-1]),
                test_start=str(test.index[0]),
                test_end=str(test.index[-1]),
                selected=best.name,
                is_ev=best_ev,
                oos_ev=float(res.trade_returns.mean()) if res.trades else 0.0,
                oos_trades=len(res.trades),
            )
        )
    return WalkForwardResult(windows=windows, oos_trades=oos_trades)


def parameter_stability(evs: Sequence[float]) -> dict[str, float]:
    """How robust is the edge across the parameter grid?

    A real edge should be positive for most neighbours, not only for one lucky combination.
    """
    arr = np.asarray([e for e in evs if np.isfinite(e)], dtype=float)
    if arr.size == 0:
        return {
            "n_variants": 0,
            "fraction_positive": 0.0,
            "median_ev": 0.0,
            "best_ev": 0.0,
            "dispersion": 0.0,
            "stability_score": 0.0,
        }
    median, best = float(np.median(arr)), float(arr.max())
    dispersion = float(arr.std() / (abs(arr.mean()) + 1e-12))
    frac_pos = float((arr > 0).mean())
    # 1.0 when all variants are positive and the best is not an outlier vs the median.
    outlier_penalty = median / best if best > 0 and median > 0 else 0.0
    return {
        "n_variants": int(arr.size),
        "fraction_positive": frac_pos,
        "median_ev": median,
        "best_ev": best,
        "dispersion": dispersion,
        "stability_score": float(frac_pos * outlier_penalty),
    }
