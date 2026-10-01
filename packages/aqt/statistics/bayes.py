"""Bayesian evidence for win probability (Beta-Binomial conjugate model).

95/100 and 9 500/10 000 have the same point estimate but very different posteriors.
"""

from __future__ import annotations

from dataclasses import dataclass

from scipy import stats


@dataclass(frozen=True)
class BetaPosterior:
    alpha: float = 1.0
    beta: float = 1.0

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.beta <= 0:
            raise ValueError("alpha and beta must be > 0")

    def update(self, wins: int, losses: int) -> BetaPosterior:
        if wins < 0 or losses < 0:
            raise ValueError("counts must be non-negative")
        return BetaPosterior(self.alpha + wins, self.beta + losses)

    def update_one(self, won: bool) -> BetaPosterior:
        return self.update(int(won), int(not won))

    @property
    def n_observations(self) -> float:
        return self.alpha + self.beta - 2.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def std(self) -> float:
        return float(stats.beta.std(self.alpha, self.beta))

    def credible_interval(self, mass: float = 0.95) -> tuple[float, float]:
        lo, hi = stats.beta.interval(mass, self.alpha, self.beta)
        return float(lo), float(hi)

    def prob_greater_than(self, threshold: float) -> float:
        return float(stats.beta.sf(threshold, self.alpha, self.beta))

    def breakeven_win_rate(self, avg_win: float, avg_loss: float) -> float:
        """Win rate at which EV = 0 given payoff magnitudes."""
        total = avg_win + avg_loss
        return avg_loss / total if total > 0 else 1.0

    def prob_positive_ev(self, avg_win: float, avg_loss: float) -> float:
        return self.prob_greater_than(self.breakeven_win_rate(avg_win, avg_loss))
