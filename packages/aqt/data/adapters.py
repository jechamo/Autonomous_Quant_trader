"""MarketDataAdapter abstraction: strategies never depend on a concrete data vendor."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from aqt.common.types import OHLCV_COLUMNS, validate_ohlcv
from aqt.data.synthetic import generate_ohlcv


class MarketDataAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Return a validated OHLCV frame indexed by UTC timestamp."""

    @staticmethod
    def _slice(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
        if start is not None:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]
        return df


class SyntheticAdapter(MarketDataAdapter):
    name = "synthetic"

    def __init__(self, n: int = 2500, seed: int = 42) -> None:
        self.n = n
        self.seed = seed

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        # Symbol-dependent but deterministic seed.
        sym_seed = self.seed + sum(ord(c) for c in symbol)
        df = generate_ohlcv(self.n, seed=sym_seed, timeframe=timeframe)
        return validate_ohlcv(self._slice(df, start, end))


class CsvAdapter(MarketDataAdapter):
    """Reads ``<root>/<symbol>_<timeframe>.csv`` with a ``timestamp`` column."""

    name = "csv"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        path = self.root / f"{symbol}_{timeframe}.csv"
        df = pd.read_csv(path)
        df.columns = [c.lower() for c in df.columns]
        ts_col = "timestamp" if "timestamp" in df.columns else "date"
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
        df = df.set_index(ts_col).sort_index()
        df.index.name = "timestamp"
        df = df[list(OHLCV_COLUMNS)].astype(float)
        return validate_ohlcv(self._slice(df, start, end))
