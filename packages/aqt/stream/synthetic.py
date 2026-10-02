"""Deterministic synthetic tick streams (quotes + trades) for tests and offline demos."""

from __future__ import annotations

import math

import numpy as np

from aqt.stream.events import Event, Quote, TradeTick


def synthetic_ticks(
    symbol: str = "BTCEUR",
    seconds: float = 3600.0,
    start_ts: float = 1_700_000_000.0,
    price: float = 50_000.0,
    vol_per_sqrt_s: float = 0.0002,
    drift_per_s: float = 0.0,
    quote_every_s: float = 0.5,
    trade_prob: float = 0.6,
    spread_pct: float = 0.0001,
    seed: int = 7,
) -> list[Event]:
    """A random-walk mid with a fixed relative spread and order flow correlated with returns."""
    rng = np.random.default_rng(seed)
    n = int(seconds / quote_every_s)
    shocks = rng.standard_normal(n) * vol_per_sqrt_s * math.sqrt(quote_every_s)
    drift = drift_per_s * quote_every_s
    events: list[Event] = []
    mid = price
    for i in range(n):
        ts = start_ts + i * quote_every_s
        ret = drift + float(shocks[i])
        mid *= math.exp(ret)
        half = mid * spread_pct / 2
        bq, aq = float(rng.uniform(0.1, 2.0)), float(rng.uniform(0.1, 2.0))
        events.append(Quote(symbol, ts, mid - half, bq, mid + half, aq))
        if rng.random() < trade_prob:
            buy = rng.random() < (0.5 + 0.4 * math.tanh(ret / (vol_per_sqrt_s + 1e-12)))
            qty = float(rng.exponential(0.05))
            px = mid + half if buy else mid - half
            events.append(TradeTick(symbol, ts + quote_every_s / 2, px, qty, not buy))
    return events
