"""Incremental, causal features for the streaming engine (O(1) or O(window) per bar).

Every value in a snapshot uses only bars that have already closed. ``breakout`` compares the
current close with the highest high of the *previous* ``breakout_bars`` bars.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass

from aqt.stream.bars import Bar


@dataclass(frozen=True)
class FeatureParams:
    fast_span: int = 12
    slow_span: int = 48
    vol_span: int = 60
    zscore_window: int = 60
    flow_window: int = 12
    momentum_bars: int = 12
    breakout_bars: int = 24
    volume_window: int = 720

    @property
    def warmup(self) -> int:
        return max(self.slow_span, self.vol_span, self.zscore_window, self.breakout_bars) + 1


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    ts: float  # bar end: the moment the snapshot became knowable
    close: float
    ema_fast: float
    ema_slow: float
    sigma: float  # per-bar volatility of log returns (EWMA)
    momentum: float  # close / close[t - momentum_bars] - 1
    zscore: float  # (close - rolling mean) / rolling std
    rolling_mean: float
    order_flow_imbalance: float  # signed trade volume / total volume, in [-1, 1]
    book_imbalance: float  # (bid_qty - ask_qty) / (bid_qty + ask_qty), in [-1, 1]
    prior_high: float  # highest high of the previous breakout_bars bars
    breakout: bool
    spread_pct: float
    volume_per_second: float
    bars_seen: int
    ready: bool

    def to_dict(self) -> dict[str, float | bool | str | int]:
        return asdict(self)


def _alpha(span: int) -> float:
    return 2.0 / (span + 1.0)


class IncrementalFeatures:
    def __init__(self, symbol: str, params: FeatureParams | None = None) -> None:
        self.symbol = symbol
        self.p = params or FeatureParams()
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._var: float | None = None
        self._last_close: float | None = None
        self._closes: deque[float] = deque(
            maxlen=max(self.p.zscore_window, self.p.momentum_bars + 1)
        )
        self._highs: deque[float] = deque(maxlen=self.p.breakout_bars)
        self._flow: deque[tuple[float, float]] = deque(maxlen=self.p.flow_window)
        self._vol: deque[float] = deque(maxlen=self.p.volume_window)
        self._interval = 0.0
        self.bars_seen = 0
        self.last: FeatureSnapshot | None = None

    def update(self, bar: Bar) -> FeatureSnapshot:
        p = self.p
        c = bar.close
        self._interval = bar.interval
        if self._ema_fast is None or self._ema_slow is None:
            self._ema_fast = self._ema_slow = c
        else:
            self._ema_fast += _alpha(p.fast_span) * (c - self._ema_fast)
            self._ema_slow += _alpha(p.slow_span) * (c - self._ema_slow)
        if self._last_close is not None and self._last_close > 0:
            r = math.log(c / self._last_close)
            a = _alpha(p.vol_span)
            self._var = r * r if self._var is None else (1 - a) * self._var + a * r * r
        self._last_close = c

        prior_high = max(self._highs) if self._highs else c
        breakout = len(self._highs) == self._highs.maxlen and c > prior_high
        self._highs.append(bar.high)

        self._closes.append(c)
        window = list(self._closes)[-p.zscore_window :]
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / len(window)
        std = math.sqrt(var)
        z = (c - mean) / std if std > 0 else 0.0
        past = list(self._closes)
        mom = c / past[-p.momentum_bars - 1] - 1.0 if len(past) > p.momentum_bars else 0.0

        self._flow.append((bar.signed_volume, bar.volume))
        tot = sum(v for _, v in self._flow)
        ofi = sum(s for s, _ in self._flow) / tot if tot > 0 else 0.0
        depth = bar.bid_qty + bar.ask_qty
        book = (bar.bid_qty - bar.ask_qty) / depth if depth > 0 else 0.0
        self._vol.append(bar.volume)
        vps = sum(self._vol) / (len(self._vol) * bar.interval)
        mid = (bar.bid + bar.ask) / 2.0
        spread = (bar.ask - bar.bid) / mid if mid > 0 else float("inf")

        self.bars_seen += 1
        snap = FeatureSnapshot(
            symbol=self.symbol,
            ts=bar.end,
            close=c,
            ema_fast=self._ema_fast,
            ema_slow=self._ema_slow,
            sigma=math.sqrt(self._var) if self._var is not None else 0.0,
            momentum=mom,
            zscore=z,
            rolling_mean=mean,
            order_flow_imbalance=ofi,
            book_imbalance=book,
            prior_high=prior_high,
            breakout=breakout,
            spread_pct=spread,
            volume_per_second=vps,
            bars_seen=self.bars_seen,
            ready=self.bars_seen >= p.warmup and self._var is not None and self._var > 0,
        )
        self.last = snap
        return snap
