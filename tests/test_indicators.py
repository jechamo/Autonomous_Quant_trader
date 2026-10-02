import numpy as np
import pandas as pd
from aqt.features import FeatureEngine
from aqt.indicators import (
    atr,
    bollinger_position,
    candle_geometry,
    rsi,
    streaks,
    trend_strength,
)


def test_rsi_bounds_and_extremes() -> None:
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert rsi(up).dropna().eq(100).all()
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert rsi(down).dropna().eq(0).all()
    flat = pd.Series(np.full(40, 5.0))
    assert rsi(flat).dropna().eq(50).all()


def test_atr_positive(ohlcv: pd.DataFrame) -> None:
    a = atr(ohlcv).dropna()
    assert (a > 0).all()


def test_candle_geometry_ranges(ohlcv: pd.DataFrame) -> None:
    g = candle_geometry(ohlcv).dropna()
    for col in ("upper_shadow", "lower_shadow", "body_range_ratio", "close_position"):
        assert g[col].between(-1e-9, 1 + 1e-9).all()
    total = g["upper_shadow"] + g["lower_shadow"] + g["body_range_ratio"]
    assert np.allclose(total, 1.0)


def test_streaks_count_consecutive_lower_and_higher_closes() -> None:
    close = pd.Series([10.0, 9.0, 8.0, 7.0, 7.0, 8.0, 9.0, 8.5])
    s = streaks(close)
    assert np.isnan(s["down_streak"].iloc[0]) and np.isnan(s["up_streak"].iloc[0])
    assert list(s["down_streak"].iloc[1:]) == [1, 2, 3, 0, 0, 0, 1]  # a flat close resets
    assert list(s["up_streak"].iloc[1:]) == [0, 0, 0, 0, 1, 2, 0]


def test_short_term_and_52_week_features(features: pd.DataFrame) -> None:
    assert features["rsi_2"].dropna().between(0, 100).all()
    # RSI(2) swings much more than RSI(14): it is the short-term oversold gauge.
    assert features["rsi_2"].std() > features["rsi"].std()
    near = features["dist_high_252"]
    assert near.iloc[:251].isna().all() and (near.dropna() <= 1e-12).all()
    assert (features["down_streak"].dropna() >= 0).all()


def test_bollinger_and_trend(ohlcv: pd.DataFrame) -> None:
    assert bollinger_position(ohlcv["close"]).dropna().between(-2, 3).all()
    up = pd.Series(np.exp(np.linspace(0, 1, 100) + np.sin(np.arange(100)) * 0.01))
    assert trend_strength(up, 50).dropna().iloc[-1] > 10


def test_features_have_no_look_ahead(ohlcv: pd.DataFrame) -> None:
    """Values at row t must not change when future rows are removed."""
    engine = FeatureEngine()
    full = engine.compute(ohlcv)
    cut = 700
    partial = engine.compute(ohlcv.iloc[:cut])
    pd.testing.assert_frame_equal(full.iloc[:cut], partial, check_freq=False)


def test_feature_engine_columns(features: pd.DataFrame) -> None:
    expected = {
        "ret_1",
        "ret_20",
        "volatility",
        "atr",
        "rsi",
        "ema_200",
        "dist_sma_50",
        "macd",
        "bb_position",
        "volume_ratio",
        "vwap_dev",
        "gap",
        "trend_strength",
        "drawdown",
        "body_size",
        "upper_shadow",
        "close_position",
        "pat_bullish_engulfing",
        "regime",
    }
    assert expected <= set(features.columns)
    assert features["regime"].dropna().str.contains("/").all()
