"""Historical data store: Parquet files queried through DuckDB.

Layout: ``<root>/<timeframe>/<symbol>.parquet``. Bulk history lives here, not in Postgres.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from aqt.common.types import OHLCV_COLUMNS, validate_ohlcv
from aqt.data.adapters import MarketDataAdapter


class ParquetStore(MarketDataAdapter):
    name = "parquet"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, symbol: str, timeframe: str) -> Path:
        return self.root / timeframe / f"{symbol}.parquet"

    def write(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Path:
        validate_ohlcv(df)
        path = self._path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = df[list(OHLCV_COLUMNS)].copy()
        out.index.name = "timestamp"
        out.reset_index().to_parquet(path, index=False)
        return path

    def symbols(self, timeframe: str) -> list[str]:
        folder = self.root / timeframe
        return sorted(p.stem for p in folder.glob("*.parquet")) if folder.exists() else []

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        path = self._path(symbol, timeframe)
        if not path.exists():
            raise FileNotFoundError(path)
        query = "SELECT * FROM read_parquet(?) WHERE 1=1"
        params: list[object] = [str(path)]
        if start is not None:
            query += " AND timestamp >= ?"
            params.append(pd.Timestamp(start, tz="UTC").to_pydatetime())
        if end is not None:
            query += " AND timestamp <= ?"
            params.append(pd.Timestamp(end, tz="UTC").to_pydatetime())
        query += " ORDER BY timestamp"
        with duckdb.connect() as con:
            df = con.execute(query, params).df()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        return validate_ohlcv(df[list(OHLCV_COLUMNS)].astype(float))
