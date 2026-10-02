"""Causal news features from real headlines, identical in research and live.

For a bar ``[t, t + Δ)`` the decision is taken at its close, so only headlines published up to
``cutoff = t + Δ − NEWS_LAG_S`` count. The lag (5 minutes) leaves time for a live poller to have
received every headline the research saw; for hourly and daily bars it is negligible.

* ``news_1d`` — headlines about the symbol in the 24 h before the cutoff;
* ``news_ratio`` — ``news_1d / (daily average of the 20 days before + 1)``: news *intensity*
  relative to the symbol's normal flow. Large caps have headlines every day, so "with or without
  news" (Chan, 2003) is measured as abnormal versus normal flow, not as presence;
* ``news_earnings_1d`` — earnings headlines (``classify_headline``) in the last 24 h.

Missing coverage is never read as "no news": values are NaN before ``coverage_start`` + 21 days
and after ``covered_until`` (e.g. the live poller has been down), so no rule can fire on them.
Headlines tagging more than ``max_symbols`` tickers are market round-ups, not company news.
"""

from __future__ import annotations

import bisect
import threading
from collections.abc import Iterable

import numpy as np
import pandas as pd

from aqt.news.items import NewsItem

NEWS_LAG_S = 300.0
NEWS_COLUMNS = ("news_1d", "news_ratio", "news_earnings_1d")
DAY_S = 86_400.0
BASELINE_DAYS = 20
MAX_SYMBOLS = 5


class NewsBook:
    """Publication times per symbol over a known coverage window; thread-safe."""

    def __init__(
        self,
        coverage_start: float,
        covered_until: float | None = None,
        max_symbols: int = MAX_SYMBOLS,
    ) -> None:
        self.coverage_start = coverage_start
        self.covered_until = covered_until if covered_until is not None else coverage_start
        self.max_symbols = max_symbols
        self._ids: set[int] = set()
        self._times: dict[str, list[float]] = {}
        self._earnings: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def add(self, items: Iterable[NewsItem], covered_until: float | None = None) -> int:
        """Add headlines (duplicates ignored); ``covered_until`` = end of the fetched window."""
        added = 0
        with self._lock:
            for item in items:
                if item.id in self._ids:
                    continue
                self._ids.add(item.id)
                added += 1
                if not item.symbols or len(item.symbols) > self.max_symbols:
                    continue
                earnings = item.kind == "earnings"
                for sym in {s.upper() for s in item.symbols}:
                    bisect.insort(self._times.setdefault(sym, []), item.created_at)
                    if earnings:
                        bisect.insort(self._earnings.setdefault(sym, []), item.created_at)
            if covered_until is not None:
                self.covered_until = max(self.covered_until, covered_until)
        return added

    def times(self, symbol: str) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            sym = symbol.upper()
            return (
                np.asarray(self._times.get(sym, ()), dtype=float),
                np.asarray(self._earnings.get(sym, ()), dtype=float),
            )


def _count(times: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Headlines with ``lo < t <= hi``."""
    return (
        np.searchsorted(times, hi, side="right") - np.searchsorted(times, lo, side="right")
    ).astype(float)


def news_features(
    book: NewsBook, symbol: str, index: pd.DatetimeIndex, timeframe_s: float
) -> pd.DataFrame:
    idx = pd.DatetimeIndex(index)
    starts = idx.to_numpy(dtype="datetime64[ns]").astype(np.int64) / 1e9  # UTC epoch s
    cutoff = starts + timeframe_s - NEWS_LAG_S
    times, earnings = book.times(symbol)
    day = _count(times, cutoff - DAY_S, cutoff)
    base = _count(times, cutoff - (BASELINE_DAYS + 1) * DAY_S, cutoff - DAY_S) / BASELINE_DAYS
    out = pd.DataFrame(
        {
            "news_1d": day,
            "news_ratio": day / (base + 1.0),
            "news_earnings_1d": _count(earnings, cutoff - DAY_S, cutoff),
        },
        index=idx,
    )
    known = (cutoff - (BASELINE_DAYS + 1) * DAY_S >= book.coverage_start) & (
        cutoff <= book.covered_until
    )
    out.loc[~known] = np.nan
    return out
