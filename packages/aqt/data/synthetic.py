"""Deterministic synthetic OHLCV generator for offline research and tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

_FREQ = {"1d": "B", "1h": "h", "15m": "15min", "5m": "5min"}


def generate_ohlcv(
    n: int = 2000,
    *,
    seed: int = 42,
    start: str = "2015-01-01",
    timeframe: str = "1d",
    start_price: float = 100.0,
    annual_drift: float = 0.07,
    annual_vol: float = 0.18,
    regime_switch_prob: float = 0.01,
) -> pd.DataFrame:
    """Regime-switching geometric Brownian motion with consistent OHLC bars.

    Two regimes (calm / turbulent) alternate with a small switch probability so that
    volatility-clustering and regime-dependent behaviour exist in the data.
    """
    if n < 2:
        raise ValueError("n must be >= 2")
    rng = np.random.default_rng(seed)
    periods_per_year = 252 if timeframe == "1d" else 252 * 7
    mu = annual_drift / periods_per_year
    base_sigma = annual_vol / np.sqrt(periods_per_year)

    regime = np.zeros(n, dtype=int)
    for i in range(1, n):
        regime[i] = 1 - regime[i - 1] if rng.random() < regime_switch_prob else regime[i - 1]
    sigma = np.where(regime == 1, base_sigma * 2.0, base_sigma * 0.8)
    drift = np.where(regime == 1, -mu, mu * 1.5)

    log_ret = drift - 0.5 * sigma**2 + sigma * rng.standard_normal(n)
    close = start_price * np.exp(np.cumsum(log_ret))
    prev_close = np.concatenate([[start_price], close[:-1]])
    gap = sigma * 0.3 * rng.standard_normal(n)
    open_ = prev_close * np.exp(gap)
    wick_hi = np.abs(rng.standard_normal(n)) * sigma * 0.5
    wick_lo = np.abs(rng.standard_normal(n)) * sigma * 0.5
    high = np.maximum(open_, close) * np.exp(wick_hi)
    low = np.minimum(open_, close) * np.exp(-wick_lo)
    volume = rng.lognormal(mean=13.0, sigma=0.4, size=n) * (1.0 + regime * 0.8)

    freq = _FREQ.get(timeframe, "B")
    index = pd.date_range(start=start, periods=n, freq=freq, tz="UTC", name="timestamp")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
