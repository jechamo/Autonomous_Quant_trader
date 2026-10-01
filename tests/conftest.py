from __future__ import annotations

import pandas as pd
import pytest
from aqt.data import generate_ohlcv
from aqt.features import FeatureEngine


@pytest.fixture(scope="session")
def ohlcv() -> pd.DataFrame:
    return generate_ohlcv(1200, seed=11)


@pytest.fixture(scope="session")
def features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    return FeatureEngine().compute(ohlcv)


def make_bars(rows: list[tuple[float, float, float, float]], atr: float = 1.0) -> pd.DataFrame:
    """Hand-made bars (open, high, low, close) with a constant ATR column for backtest tests."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1000.0
    df["atr"] = atr
    return df
