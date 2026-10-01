"""Edge Score: a single 0–100 summary of whether a statistical advantage exists.

It combines the four values every opportunity carries:
  * P(win)                — Bayesian posterior mean of the win rate;
  * Expected Value        — mean net return per trade, after costs;
  * Statistical confidence — 1 − (FDR-adjusted) p-value that EV > 0;
  * Regime compatibility  — how well the current regime matches where the edge worked.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from aqt.statistics.bayes import BetaPosterior
from aqt.statistics.confidence import mean_return_test


@dataclass(frozen=True)
class EdgeScore:
    score: float
    p_win: float
    p_win_ci: tuple[float, float]
    expected_value: float
    confidence: float
    regime_compatibility: float
    prob_positive_ev: float
    n_trades: int

    @property
    def has_edge(self) -> bool:
        return self.score > 0 and self.expected_value > 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def compute_edge_score(
    trade_returns: np.ndarray,
    p_value: float | None = None,
    regime_compatibility: float = 1.0,
    min_trades: int = 30,
    prior: BetaPosterior | None = None,
) -> EdgeScore:
    tr = np.asarray(trade_returns, dtype=float)
    n = int(tr.size)
    wins = int((tr > 0).sum())
    post = (prior or BetaPosterior()).update(wins, n - wins)
    ev = float(tr.mean()) if n else 0.0
    if p_value is None:
        p_value = mean_return_test(tr).p_value
    confidence = max(0.0, 1.0 - p_value)
    avg_win = float(tr[tr > 0].mean()) if wins else 0.0
    avg_loss = float(-tr[tr <= 0].mean()) if n - wins else 0.0
    p_pos = post.prob_positive_ev(avg_win, avg_loss) if n else 0.0

    regime_compatibility = min(max(regime_compatibility, 0.0), 1.0)
    if n == 0 or ev <= 0:
        score = 0.0
    else:
        sample_factor = min(1.0, n / min_trades)
        quality = math.tanh(ev / (avg_loss + 1e-9)) if avg_loss > 0 else 1.0
        score = 100.0 * confidence * sample_factor * regime_compatibility * quality * p_pos
    return EdgeScore(
        score=float(score),
        p_win=post.mean,
        p_win_ci=post.credible_interval(),
        expected_value=ev,
        confidence=confidence,
        regime_compatibility=regime_compatibility,
        prob_positive_ev=p_pos,
        n_trades=n,
    )
