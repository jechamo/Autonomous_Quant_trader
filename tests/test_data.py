from pathlib import Path

import pandas as pd
import pytest
from aqt.common.types import validate_ohlcv
from aqt.data import CsvAdapter, ParquetStore, SyntheticAdapter, generate_ohlcv


def test_synthetic_is_valid_and_deterministic() -> None:
    a = generate_ohlcv(500, seed=3)
    b = generate_ohlcv(500, seed=3)
    validate_ohlcv(a)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(generate_ohlcv(500, seed=4))


def test_synthetic_adapter_slices() -> None:
    df = SyntheticAdapter(n=300).get_ohlcv("SPY", "1d", start="2015-03-01", end="2015-06-01")
    assert df.index[0] >= pd.Timestamp("2015-03-01", tz="UTC")
    assert df.index[-1] <= pd.Timestamp("2015-06-01", tz="UTC")


def test_parquet_roundtrip(tmp_path: Path) -> None:
    df = generate_ohlcv(200, seed=1)
    store = ParquetStore(tmp_path)
    store.write("SPY", "1d", df)
    assert store.symbols("1d") == ["SPY"]
    back = store.get_ohlcv("SPY", "1d")
    pd.testing.assert_frame_equal(back, df, check_freq=False, check_names=False)
    part = store.get_ohlcv("SPY", "1d", start=str(df.index[50].date()))
    assert len(part) == 150
    with pytest.raises(FileNotFoundError):
        store.get_ohlcv("QQQ", "1d")


def test_csv_adapter(tmp_path: Path) -> None:
    df = generate_ohlcv(50, seed=2)
    out = df.reset_index().rename(columns=str.capitalize)
    out = out.rename(columns={"Timestamp": "Date"})
    out.to_csv(tmp_path / "AAA_1d.csv", index=False)
    back = CsvAdapter(tmp_path).get_ohlcv("AAA", "1d")
    assert len(back) == 50
    assert list(back.columns) == ["open", "high", "low", "close", "volume"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.drop(columns="volume"),
        lambda d: d.iloc[::-1],
        lambda d: d.assign(close=-1.0),
        lambda d: d.assign(high=d["low"] * 0.5),
        lambda d: d.reset_index(drop=True),
    ],
)
def test_validate_rejects_bad_frames(mutate) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        validate_ohlcv(mutate(generate_ohlcv(20)))
