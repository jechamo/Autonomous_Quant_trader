"""Feature Engine: composes indicators into a single causal feature matrix."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from aqt.common.types import validate_ohlcv
from aqt.indicators import (
    atr,
    bollinger_position,
    candle_geometry,
    distance_to,
    ema,
    gap,
    macd,
    returns,
    rolling_drawdown,
    rolling_volatility,
    rsi,
    sma,
    trend_strength,
    volume_ratio,
    vwap_deviation,
)
from aqt.regime import RegimeClassifier


def candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Boolean classic patterns, derived from candle geometry (kept for interpretability)."""
    o, h, low, c = df["open"], df["high"], df["low"], df["close"]
    po, pc = o.shift(1), c.shift(1)
    body = (c - o).abs()
    rng = (h - low).replace(0.0, np.nan)
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    lower = pd.concat([o, c], axis=1).min(axis=1) - low

    bullish_engulfing = (pc < po) & (c > o) & (o <= pc) & (c >= po)
    bearish_engulfing = (pc > po) & (c < o) & (o >= pc) & (c <= po)
    hammer = (
        (lower >= 2 * body) & (upper <= 0.3 * body.where(body > 0, rng * 0.1)) & (body / rng > 0.05)
    )
    shooting_star = (
        (upper >= 2 * body) & (lower <= 0.3 * body.where(body > 0, rng * 0.1)) & (body / rng > 0.05)
    )
    doji = body / rng < 0.1
    return pd.DataFrame(
        {
            "pat_bullish_engulfing": bullish_engulfing.fillna(False).astype(float),
            "pat_bearish_engulfing": bearish_engulfing.fillna(False).astype(float),
            "pat_hammer": hammer.fillna(False).astype(float),
            "pat_shooting_star": shooting_star.fillna(False).astype(float),
            "pat_doji": doji.fillna(False).astype(float),
        },
        index=df.index,
    )


@dataclass
class FeatureEngine:
    return_periods: Sequence[int] = (1, 3, 5, 10, 20)
    ma_windows: Sequence[int] = (20, 50, 200)
    vol_window: int = 20
    atr_window: int = 14
    rsi_window: int = 14
    flow_windows: Sequence[int] = (5, 15)
    regime: RegimeClassifier = field(default_factory=RegimeClassifier)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        validate_ohlcv(df)
        close = df["close"]
        feats: dict[str, pd.Series] = {}

        for p in self.return_periods:
            feats[f"ret_{p}"] = returns(close, p)
        feats["volatility"] = rolling_volatility(close, self.vol_window)
        feats["atr"] = atr(df, self.atr_window)
        feats["atr_pct"] = feats["atr"] / close
        feats["rsi"] = rsi(close, self.rsi_window)
        for w in self.ma_windows:
            feats[f"sma_{w}"] = sma(close, w)
            feats[f"ema_{w}"] = ema(close, w)
            feats[f"dist_sma_{w}"] = distance_to(close, feats[f"sma_{w}"])
            feats[f"dist_ema_{w}"] = distance_to(close, feats[f"ema_{w}"])
        feats["bb_position"] = bollinger_position(close)
        feats["volume_ratio"] = volume_ratio(df["volume"])
        feats["vwap_dev"] = vwap_deviation(df)
        feats["gap"] = gap(df)
        feats["momentum_20"] = feats["ret_20"] if 20 in self.return_periods else returns(close, 20)
        feats["acceleration"] = (
            feats["ret_1"].diff() if 1 in self.return_periods else returns(close).diff()
        )
        feats["trend_strength"] = trend_strength(close, 50)
        feats["drawdown"] = rolling_drawdown(close)
        feats["high_20"] = df["high"].rolling(20, min_periods=20).max()
        feats["low_20"] = df["low"].rolling(20, min_periods=20).min()
        feats["prev_high_20"] = feats["high_20"].shift(1)
        feats["prev_low_20"] = feats["low_20"].shift(1)
        if "taker_buy_volume" in df.columns:
            # Signed order flow (intraday data): share of volume bought by aggressive takers,
            # mapped to [-1, 1] over the last n bars. Only uses bars up to and including t.
            signed = 2.0 * df["taker_buy_volume"] - df["volume"]
            for n in self.flow_windows:
                vol = df["volume"].rolling(n, min_periods=n).sum().replace(0.0, np.nan)
                feats[f"flow_imbalance_{n}"] = signed.rolling(n, min_periods=n).sum() / vol

        out = pd.concat(
            [
                df[["open", "high", "low", "close", "volume"]],
                pd.DataFrame(feats, index=df.index),
                macd(close),
                candle_geometry(df),
                candlestick_patterns(df),
                self.regime.classify(df),
            ],
            axis=1,
        )
        return out
