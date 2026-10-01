"""Yahoo Finance daily data via yfinance (unofficial API: wrapped behind MarketDataAdapter)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import ClassVar

import numpy as np
import pandas as pd

from aqt.common.types import OHLCV_COLUMNS, validate_ohlcv
from aqt.data.adapters import MarketDataAdapter

FetchFn = Callable[[str, str | None, str | None, str], pd.DataFrame]


class DataUnavailableError(RuntimeError):
    pass


def _yfinance_fetch(symbol: str, start: str | None, end: str | None, interval: str) -> pd.DataFrame:
    import yfinance as yf  # imported lazily: optional at runtime, heavy at import

    return yf.Ticker(symbol).history(
        start=start, end=end, interval=interval, auto_adjust=True, actions=False, raise_errors=True
    )


def normalize_yahoo_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Yahoo frame -> validated OHLCV with a UTC daily index.

    Adjustment rounding can leave high/low marginally inside open/close; they are widened so
    the bar stays consistent. Rows with missing or non-positive prices are dropped.
    """
    if raw is None or raw.empty:
        raise DataUnavailableError("empty response")
    df = raw.rename(columns=str.lower)[list(OHLCV_COLUMNS)].astype(float)
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize(None) if idx.tz is not None else idx
    df.index = pd.DatetimeIndex(idx.normalize(), name="timestamp").tz_localize("UTC")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    prices = df[["open", "high", "low", "close"]]
    df = df[(prices > 0).all(axis=1) & prices.notna().all(axis=1)].copy()
    df["volume"] = df["volume"].fillna(0.0).clip(lower=0.0)
    p = df[["open", "high", "low", "close"]].to_numpy()
    df["high"] = np.max(p, axis=1)
    df["low"] = np.min(p, axis=1)
    return validate_ohlcv(df)


class YahooAdapter(MarketDataAdapter):
    name = "yahoo"
    _INTERVALS: ClassVar[dict[str, str]] = {"1d": "1d", "1wk": "1wk", "1h": "1h"}

    def __init__(
        self, fetch: FetchFn | None = None, retries: int = 3, backoff_seconds: float = 2.0
    ) -> None:
        self._fetch = fetch or _yfinance_fetch
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        interval = self._INTERVALS.get(timeframe)
        if interval is None:
            raise ValueError(f"unsupported timeframe {timeframe!r} for Yahoo")
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                return normalize_yahoo_frame(self._fetch(symbol, start, end, interval))
            except DataUnavailableError as exc:
                last_error = exc
                break  # empty is not transient
            except Exception as exc:  # network / rate limit
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(self.backoff_seconds * 2**attempt)
        raise DataUnavailableError(
            f"Yahoo data unavailable for {symbol}: {last_error}. "
            "If this environment blocks the network, allow query1/query2.finance.yahoo.com "
            "and fc.yahoo.com."
        )
