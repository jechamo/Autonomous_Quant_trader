"""Frequentist confidence measures."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (0.0, 1.0)
    if not 0 <= successes <= n:
        raise ValueError("successes must be in [0, n]")
    z = float(stats.norm.ppf(0.5 + confidence / 2.0))
    p = successes / n
    denom = 1.0 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class MeanTest:
    mean: float
    ci_low: float
    ci_high: float
    t_stat: float
    p_value: float  # one-sided H1: mean > 0


def mean_return_test(returns: np.ndarray, confidence: float = 0.95) -> MeanTest:
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 2:
        m = float(r.mean()) if n else 0.0
        return MeanTest(m, -math.inf, math.inf, 0.0, 1.0)
    mean = float(r.mean())
    se = float(r.std(ddof=1) / math.sqrt(n))
    if se == 0:
        p = 0.0 if mean > 0 else 1.0
        return MeanTest(mean, mean, mean, math.inf if mean > 0 else 0.0, p)
    t = mean / se
    tcrit = float(stats.t.ppf(0.5 + confidence / 2.0, df=n - 1))
    p = float(stats.t.sf(t, df=n - 1))
    return MeanTest(mean, mean - tcrit * se, mean + tcrit * se, float(t), p)
