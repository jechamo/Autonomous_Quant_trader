"""US equities for the streaming engine: trading session, order-flow estimate, 1-minute history.

* :class:`UsEquitySession` — regular session 09:30–16:00 America/New_York, Monday–Friday
  (plus optional holidays). Intraday only: the engine stops opening positions shortly before the
  close and flattens before the bell, so nothing is ever held overnight.
* :func:`bvc_taker_buy` — stock data does not say which trades were aggressive buys. Bulk Volume
  Classification (Easley, López de Prado & O'Hara) estimates the buying fraction of a bar as
  Φ(return / σ). It is computed the same way in research and live, so rules see the same
  ``flow_imbalance`` features in both.
* :func:`load_yahoo_1m` — free 1-minute bars (last ~7 days) from Yahoo's chart API, cached per
  day; :func:`bar_events` turns bars into quotes/trades for simulations and golden checks.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from scipy.stats import norm

from aqt.stream.binance import system_ssl_context
from aqt.stream.events import Event, Quote, TradeTick
from aqt.stream.session import NY, AlwaysOpen, UsEquitySession

DEFAULT_STOCKS = "SPY,QQQ,AAPL,NVDA,TSLA,MSFT,AMZN,META,AMD,GOOGL"
_COLUMNS = ["open", "high", "low", "close", "volume", "taker_buy_volume"]


def bvc_taker_buy(bars: pd.DataFrame, window: int = 50) -> pd.Series:
    """Estimated aggressive-buy volume per bar: volume × Φ(Δp / σ) (causal)."""
    ret = bars["close"].pct_change()
    sigma = ret.rolling(window, min_periods=10).std()
    z = (ret / sigma.replace(0.0, np.nan)).clip(-10, 10)
    frac = pd.Series(norm.cdf(z.fillna(0.0)), index=bars.index)
    return bars["volume"] * frac


def with_bvc(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    out["taker_buy_volume"] = bvc_taker_buy(out)
    return out


def parse_yahoo_chart(payload: dict[str, object]) -> pd.DataFrame:
    """Yahoo ``/v8/finance/chart`` JSON → OHLCV (UTC index), regular-session bars only."""
    result = payload["chart"]["result"][0]  # type: ignore[index]
    ts = result.get("timestamp") or []
    q = result["indicators"]["quote"][0]
    df = pd.DataFrame(
        {k: q.get(k) for k in ("open", "high", "low", "close", "volume")},
        index=pd.to_datetime(ts, unit="s", utc=True),
        dtype=float,
    )
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df["volume"] = df["volume"].fillna(0.0)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_yahoo_1m(
    symbol: str,
    start_ms: int,
    end_ms: int,
    cache_dir: str | Path = "data/stream/yahoo1m",
    timeout: float = 20.0,
) -> pd.DataFrame:  # pragma: no cover - network
    """1-minute regular-session bars with BVC flow. Yahoo keeps ~7 days of 1-minute history."""
    cache = Path(cache_dir) / symbol.upper()
    cache.mkdir(parents=True, exist_ok=True)
    frames = [pd.read_parquet(p) for p in sorted(cache.glob("*.parquet"))]
    have = pd.concat(frames) if frames else pd.DataFrame(columns=_COLUMNS[:5])
    now = time.time()
    lo = max(start_ms / 1000, now - 7 * 86_400 + 60)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if lo < end_ms / 1000:
        with httpx.Client(verify=system_ssl_context(), timeout=timeout, headers=headers) as c:
            r = c.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"interval": "1m", "period1": int(lo), "period2": int(end_ms / 1000),
                        "includePrePost": "false"},
            )  # fmt: skip
            r.raise_for_status()
        fresh = parse_yahoo_chart(r.json())
        have = pd.concat([have, fresh]) if len(have) else fresh
        have = have[~have.index.duplicated(keep="last")].sort_index()
        # Cache complete New York days only (today's bars may still change).
        today = str(datetime.fromtimestamp(now, NY).date())
        days = pd.DatetimeIndex(have.index).tz_convert(NY).strftime("%Y-%m-%d")
        for d in sorted(set(days)):
            if d < today:
                have[days == d].to_parquet(cache / f"{d}.parquet")
    lo_ts = pd.Timestamp(start_ms, unit="ms", tz="UTC")
    hi_ts = pd.Timestamp(end_ms, unit="ms", tz="UTC")
    bars = have[(have.index >= lo_ts) & (have.index < hi_ts)].astype(float)
    return with_bvc(bars[["open", "high", "low", "close", "volume"]])


def bar_events(
    bars: pd.DataFrame,
    symbol: str,
    spread_pct: float = 0.0002,
    seconds: float = 60.0,
    session: UsEquitySession | None = None,
) -> Iterator[Event]:
    """Bars of any length → conservative quote path (open, extremes, close) + signed trades.

    With a ``session`` the path is squeezed into the part of the bar when the market is open
    (an hourly bar starting at 09:00 New York trades from 09:30), so simulated orders can fill.
    """
    half = spread_pct / 2
    tb_col = "taker_buy_volume" if "taker_buy_volume" in bars else None
    for ts, row in zip(bars.index, bars.itertuples(index=False), strict=True):
        t = pd.Timestamp(ts).timestamp()
        end = t + seconds
        if session is not None:
            day_open, day_close = session.bounds(t)
            t, end = max(t, day_open), min(end, day_close)
            if end - t < 1.0:
                continue
        step = (end - t) / 5
        o, h, lo, c, v = (
            float(getattr(row, k)) for k in ("open", "high", "low", "close", "volume")
        )
        tb = float(getattr(row, tb_col)) if tb_col else v / 2
        size = max(v, 1e-9)
        path = (o, lo, h, c) if c >= o else (o, h, lo, c)
        for k, mid in enumerate(path):
            yield Quote(symbol, t + step * k, mid * (1 - half), size, mid * (1 + half), size)
        if tb > 0:
            yield TradeTick(symbol, t + step * 4, c, tb, False)
        if v - tb > 1e-12:
            yield TradeTick(symbol, t + step * 4.5, c, v - tb, True)


def merge_bar_events(streams: Iterable[Iterable[Event]]) -> Iterator[Event]:
    import heapq

    return heapq.merge(*streams, key=lambda e: e.ts)


def next_session_open(ts: float, session: UsEquitySession | None = None) -> float:
    """Epoch seconds of the next regular-session open at or after ``ts``."""
    session = session or UsEquitySession()
    day = datetime.fromtimestamp(ts, NY)
    for i in range(10):
        d = (day + timedelta(days=i)).replace(
            hour=session.open_time[0], minute=session.open_time[1], second=0, microsecond=0
        )
        if d.timestamp() >= ts and session.is_trading_day(d.timestamp()):
            return d.timestamp()
    return ts


__all__ = ["AlwaysOpen", "UsEquitySession", "bar_events", "bvc_taker_buy", "load_yahoo_1m"]
