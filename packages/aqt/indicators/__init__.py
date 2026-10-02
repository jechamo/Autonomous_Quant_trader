"""Technical indicators.

Convention: every value at row ``t`` uses only information available at the *close* of bar
``t``. Execution happens at the open of ``t+1`` (enforced by the backtester), which keeps the
whole pipeline free of look-ahead bias.
"""

from aqt.indicators.core import (
    atr,
    bollinger_position,
    candle_geometry,
    distance_to,
    ema,
    gap,
    log_returns,
    macd,
    returns,
    rolling_drawdown,
    rolling_volatility,
    rsi,
    sma,
    streaks,
    trend_strength,
    true_range,
    volume_ratio,
    vwap_deviation,
)

__all__ = [
    "atr",
    "bollinger_position",
    "candle_geometry",
    "distance_to",
    "ema",
    "gap",
    "log_returns",
    "macd",
    "returns",
    "rolling_drawdown",
    "rolling_volatility",
    "rsi",
    "sma",
    "streaks",
    "trend_strength",
    "true_range",
    "volume_ratio",
    "vwap_deviation",
]
