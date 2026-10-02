"""Cross-sectional (between symbols) and calendar features, identical in research and live.

Cross-sectional features rank each symbol against the rest of its universe — the raw material of
the best documented equity anomalies (cross-sectional momentum, short-term reversal, relative
strength) that a single-symbol rule cannot express:

* ``xs_rank_ret_{5,20,60}`` — percentile (0–1) of the symbol's N-bar return in the universe;
* ``xs_rel_ret_20`` — 20-bar return minus the universe median;
* ``xs_breadth`` — share of the universe trading above its own 50-bar EMA;
* ``xs_n`` — how many symbols were ranked.

They are taken from the **previous completed panel bar**: live, a symbol's bar may close a few
seconds before another's, so using bar ``t`` would make the value depend on arrival order. One bar
of lag makes research and live see exactly the same number, and keeps everything causal.

Calendar features (from the bar timestamp only): ``hour_utc``, ``day_of_week``,
``day_of_month``, ``days_to_month_end`` (calendar days left in the month, for turn-of-the-month
effects) and, for US stocks, ``minutes_to_close`` measured from the end of the bar to the 16:00
New York close. Dates are those of the bar's last instant (New York for stocks, UTC otherwise), so
a daily bar labelled 00:00 UTC belongs to its own trading day. The calendar is known in advance:
none of these looks ahead.
"""

from __future__ import annotations

from collections.abc import Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from aqt.news.book import NewsBook, news_features

NY = ZoneInfo("America/New_York")

XS_PERIODS = (5, 20, 60)
XS_COLUMNS = (
    *(f"xs_rank_ret_{n}" for n in XS_PERIODS),
    "xs_rel_ret_20",
    "xs_breadth",
    "xs_n",
)
CALENDAR_COLUMNS = (
    "hour_utc",
    "day_of_week",
    "minutes_to_close",
    "day_of_month",
    "days_to_month_end",
)
PASSTHROUGH_PREFIXES = ("xs_", "news_")


def cross_sectional_features(closes: Mapping[str, pd.Series]) -> dict[str, pd.DataFrame]:
    """Per-symbol frames of ``XS_COLUMNS`` aligned to each symbol's own index (lagged one bar)."""
    if not closes:
        return {}
    rets: dict[int, dict[str, pd.Series]] = {n: {} for n in XS_PERIODS}
    above: dict[str, pd.Series] = {}
    for sym, close in closes.items():
        c = close.astype(float)
        for n in XS_PERIODS:
            rets[n][sym] = c / c.shift(n) - 1.0  # on the symbol's own bar sequence
        ema50 = c.ewm(span=50, adjust=False, min_periods=50).mean()
        above[sym] = (c > ema50).astype(float).where(ema50.notna())
    out_cols: dict[str, pd.DataFrame] = {}
    for n in XS_PERIODS:
        panel = pd.DataFrame(rets[n]).sort_index()
        out_cols[f"xs_rank_ret_{n}"] = panel.rank(axis=1, pct=True)
        if n == 20:
            out_cols["xs_rel_ret_20"] = panel.sub(panel.median(axis=1), axis=0)
            counts = panel.notna().sum(axis=1).astype(float)
            out_cols["xs_n"] = pd.DataFrame({s: counts for s in panel.columns}, index=panel.index)
    breadth = pd.DataFrame(above).sort_index().mean(axis=1)
    index = out_cols["xs_rank_ret_5"].index
    out_cols["xs_breadth"] = pd.DataFrame({s: breadth for s in closes}, index=index)
    result: dict[str, pd.DataFrame] = {}
    for sym, close in closes.items():
        frame = pd.DataFrame(
            {col: df[sym].shift(1) for col, df in out_cols.items()}  # previous panel bar
        )
        result[sym] = frame.reindex(close.index)[list(XS_COLUMNS)]
    return result


def calendar_features(index: pd.DatetimeIndex, timeframe_s: float, session: str) -> pd.DataFrame:
    idx = pd.DatetimeIndex(index)
    out = pd.DataFrame(index=idx)
    out["hour_utc"] = idx.hour + idx.minute / 60.0
    local = idx.tz_convert(NY) if session == "us_equity" else idx
    last = local + pd.Timedelta(seconds=timeframe_s) - pd.Timedelta(microseconds=1)
    out["day_of_week"] = last.dayofweek.astype(float)
    if session == "us_equity":
        bar_end = local + pd.Timedelta(seconds=timeframe_s)
        close = local.normalize() + pd.Timedelta(hours=16)
        out["minutes_to_close"] = np.maximum((close - bar_end).total_seconds() / 60.0, 0.0)
    out["day_of_month"] = last.day.astype(float)
    out["days_to_month_end"] = (last.days_in_month - last.day).astype(float)
    return out


def augment(
    bars: Mapping[str, pd.DataFrame],
    timeframe_s: float,
    session: str = "24/7",
    news: NewsBook | None = None,
) -> dict[str, pd.DataFrame]:
    """Add cross-sectional + calendar (+ news, when a :class:`NewsBook` is given) columns to
    every symbol's bars — the one function both research and live use."""
    xs = cross_sectional_features({s: b["close"] for s, b in bars.items() if not b.empty})
    out: dict[str, pd.DataFrame] = {}
    for sym, b in bars.items():
        index = pd.DatetimeIndex(b.index)
        parts = [b, calendar_features(index, timeframe_s, session)]
        if sym in xs:
            parts.append(xs[sym])
        if news is not None:
            parts.append(news_features(news, sym, index, timeframe_s))
        out[sym] = pd.concat(parts, axis=1)
    return out
