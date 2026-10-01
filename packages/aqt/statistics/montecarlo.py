"""Monte Carlo resampling of trade sequences."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class MonteCarloResult:
    n_simulations: int
    final_return_p5: float
    final_return_p50: float
    final_return_p95: float
    max_drawdown_p50: float
    max_drawdown_p95: float  # 95th percentile of *depth* (more negative = worse)
    prob_loss: float
    prob_drawdown_exceeds: float
    drawdown_threshold: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def monte_carlo_trades(
    trade_returns: np.ndarray,
    n_simulations: int = 5000,
    position_fraction: float = 1.0,
    drawdown_threshold: float = -0.20,
    seed: int = 7,
) -> MonteCarloResult:
    """Bootstrap trades with replacement; position_fraction scales each trade's P&L."""
    tr = np.asarray(trade_returns, dtype=float)
    if tr.size == 0:
        return MonteCarloResult(n_simulations, 0, 0, 0, 0, 0, 0.0, 0.0, drawdown_threshold)
    rng = np.random.default_rng(seed)
    samples = rng.choice(tr, size=(n_simulations, tr.size), replace=True) * position_fraction
    equity = np.cumprod(1.0 + samples, axis=1)
    equity = np.concatenate([np.ones((n_simulations, 1)), equity], axis=1)
    peaks = np.maximum.accumulate(equity, axis=1)
    mdd = (equity / peaks - 1.0).min(axis=1)
    final = equity[:, -1] - 1.0
    return MonteCarloResult(
        n_simulations=n_simulations,
        final_return_p5=float(np.percentile(final, 5)),
        final_return_p50=float(np.percentile(final, 50)),
        final_return_p95=float(np.percentile(final, 95)),
        max_drawdown_p50=float(np.percentile(mdd, 50)),
        max_drawdown_p95=float(np.percentile(mdd, 5)),
        prob_loss=float((final < 0).mean()),
        prob_drawdown_exceeds=float((mdd < drawdown_threshold).mean()),
        drawdown_threshold=drawdown_threshold,
    )
