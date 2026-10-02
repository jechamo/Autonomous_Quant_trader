"""Pure, causal indicator functions on pandas Series/DataFrames."""

from __future__ import annotations

import numpy as np
import pandas as pd


def returns(close: pd.Series, periods: int = 1) -> pd.Series:
    return close.pct_change(periods, fill_method=None)


def log_returns(close: pd.Series, periods: int = 1) -> pd.Series:
    ratio = (close / close.shift(periods)).to_numpy(dtype=float)
    return pd.Series(np.log(ratio), index=close.index, name=close.name)


def rolling_volatility(close: pd.Series, window: int = 20) -> pd.Series:
    return log_returns(close).rolling(window, min_periods=window).std()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def distance_to(series: pd.Series, reference: pd.Series) -> pd.Series:
    """Relative distance ``series / reference - 1``."""
    return series / reference - 1.0


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1, skipna=True)


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range with Wilder smoothing."""
    return true_range(df).ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI in [0, 100]."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # No losses in window -> RSI 100; no movement at all -> 50.
    out = out.where(avg_loss != 0.0, np.where(avg_gain > 0.0, 100.0, 50.0))
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger_position(close: pd.Series, window: int = 20, k: float = 2.0) -> pd.Series:
    """Location of close within the Bollinger band: 0 = lower band, 1 = upper band."""
    mid = sma(close, window)
    sd = close.rolling(window, min_periods=window).std()
    upper, lower = mid + k * sd, mid - k * sd
    width = (upper - lower).replace(0.0, np.nan)
    return (close - lower) / width


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """Volume relative to the average of the *previous* ``window`` bars."""
    return volume / volume.shift(1).rolling(window, min_periods=window).mean()


def vwap_deviation(df: pd.DataFrame, window: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (typical * df["volume"]).rolling(window, min_periods=window).sum()
    vol = df["volume"].rolling(window, min_periods=window).sum()
    vwap = pv / vol.replace(0.0, np.nan)
    return df["close"] / vwap - 1.0


def gap(df: pd.DataFrame) -> pd.Series:
    return df["open"] / df["close"].shift(1) - 1.0


def streaks(close: pd.Series) -> pd.DataFrame:
    """Consecutive closes below (``down_streak``) / above (``up_streak``) the previous close,
    counted up to and including t. A flat close resets both; the first bar is undefined."""
    diff = close.diff()
    out = {}
    for name, moved in (("down_streak", diff < 0), ("up_streak", diff > 0)):
        run = moved.astype(int)
        out[name] = run.groupby((run == 0).cumsum()).cumsum().astype(float)
    return pd.DataFrame(out, index=close.index).where(diff.notna())


def rolling_drawdown(close: pd.Series, window: int = 252) -> pd.Series:
    peak = close.rolling(window, min_periods=1).max()
    return close / peak - 1.0


def trend_strength(close: pd.Series, window: int = 50) -> pd.Series:
    """Slope of log-price regression over ``window`` bars, scaled by residual std (t-stat-like)."""
    y = np.log(close.to_numpy(dtype=float))
    n = len(y)
    out = np.full(n, np.nan)
    if n < window:
        return pd.Series(out, index=close.index)
    x = np.arange(window, dtype=float)
    x_c = x - x.mean()
    sxx = float((x_c**2).sum())
    windows = np.lib.stride_tricks.sliding_window_view(y, window)
    y_c = windows - windows.mean(axis=1, keepdims=True)
    slope = (y_c * x_c).sum(axis=1) / sxx
    resid = y_c - slope[:, None] * x_c
    se = np.sqrt((resid**2).sum(axis=1) / max(window - 2, 1) / sxx)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, slope / se, 0.0)
    out[window - 1 :] = t
    return pd.Series(out, index=close.index)


def candle_geometry(df: pd.DataFrame) -> pd.DataFrame:
    """Mathematical description of each candle, independent of traditional pattern names."""
    o, h, low, c = df["open"], df["high"], df["low"], df["close"]
    rng = (h - low).replace(0.0, np.nan)
    body = (c - o).abs()
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    lower = pd.concat([o, c], axis=1).min(axis=1) - low
    return pd.DataFrame(
        {
            "body_size": body / o,
            "body_direction": np.sign(c - o),
            "upper_shadow": upper / rng,
            "lower_shadow": lower / rng,
            "body_range_ratio": body / rng,
            "close_position": (c - low) / rng,
            "range_pct": (h - low) / o,
        },
        index=df.index,
    )
