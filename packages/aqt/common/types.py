"""Shared primitive types."""

from __future__ import annotations

from enum import StrEnum

import pandas as pd

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(StrEnum):
    NEW = "NEW"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Validate an OHLCV frame: DatetimeIndex, sorted, unique, required columns, sane prices."""
    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("OHLCV frame must have a DatetimeIndex")
    if not df.index.is_monotonic_increasing:
        raise ValueError("OHLCV index must be sorted ascending")
    if df.index.has_duplicates:
        raise ValueError("OHLCV index has duplicate timestamps")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLCV prices must be strictly positive")
    if (df["high"] < df[["open", "close", "low"]].max(axis=1) - 1e-9).any():
        raise ValueError("high must be >= open, close and low")
    if (df["low"] > df[["open", "close"]].min(axis=1) + 1e-9).any():
        raise ValueError("low must be <= open and close")
    if (df["volume"] < 0).any():
        raise ValueError("volume must be non-negative")
    return df
