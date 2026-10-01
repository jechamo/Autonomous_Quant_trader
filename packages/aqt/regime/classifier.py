"""Simple, causal market-regime classifier: trend × volatility."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from aqt.indicators import rolling_volatility, sma


class TrendRegime(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"


class VolRegime(StrEnum):
    LOW = "low_vol"
    MEDIUM = "medium_vol"
    HIGH = "high_vol"


@dataclass(frozen=True)
class RegimeClassifier:
    trend_window: int = 200
    slope_window: int = 20
    vol_window: int = 20
    vol_rank_window: int = 252
    sideways_band: float = 0.02

    def classify(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        ma = sma(close, self.trend_window)
        dist = close / ma - 1.0
        slope = ma / ma.shift(self.slope_window) - 1.0

        trend = np.select(
            [
                (dist > self.sideways_band) & (slope > 0),
                (dist < -self.sideways_band) & (slope < 0),
            ],
            [TrendRegime.BULL.value, TrendRegime.BEAR.value],
            default=TrendRegime.SIDEWAYS.value,
        )
        trend_s = pd.Series(trend, index=df.index, dtype=object).where(ma.notna() & slope.notna())

        vol = rolling_volatility(close, self.vol_window)
        vol_rank = vol.rolling(self.vol_rank_window, min_periods=60).rank(pct=True)
        vol_lbl = np.select(
            [vol_rank < 1 / 3, vol_rank < 2 / 3],
            [VolRegime.LOW.value, VolRegime.MEDIUM.value],
            default=VolRegime.HIGH.value,
        )
        vol_s = pd.Series(vol_lbl, index=df.index, dtype=object).where(vol_rank.notna())

        regime = (trend_s + "/" + vol_s).where(trend_s.notna() & vol_s.notna())
        return pd.DataFrame(
            {"trend_regime": trend_s, "vol_regime": vol_s, "regime": regime}, index=df.index
        )
