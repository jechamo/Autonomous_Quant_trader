import pandas as pd
import pytest
from aqt.backtest import CostModel
from aqt.backtest.costs import T212_FX_FEE
from aqt.data import (
    UNIVERSES,
    DataUnavailableError,
    YahooAdapter,
    generate_ohlcv,
    get_instrument,
    normalize_yahoo_frame,
    resolve_universe,
)


def _raw_yahoo(n: int = 30) -> pd.DataFrame:
    df = generate_ohlcv(n, seed=4)
    raw = df.rename(columns=str.capitalize)
    raw.index = raw.index.tz_convert("America/New_York")  # Yahoo returns exchange time
    raw["Dividends"] = 0.0
    return raw


def test_normalize_yahoo_frame() -> None:
    raw = _raw_yahoo()
    raw.iloc[3, raw.columns.get_loc("High")] = raw.iloc[3]["Close"] * 0.999  # rounding glitch
    raw.iloc[5, raw.columns.get_loc("Close")] = float("nan")
    raw = pd.concat([raw, raw.iloc[[-1]]])  # duplicated last bar
    df = normalize_yahoo_frame(raw)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(df.index.tz) == "UTC"
    assert (df.index == df.index.normalize()).all()
    assert len(df) == 29  # NaN row dropped, duplicate removed
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    with pytest.raises(DataUnavailableError):
        normalize_yahoo_frame(pd.DataFrame())


def test_adapter_retries_then_succeeds() -> None:
    calls: list[str] = []

    def flaky(symbol: str, start: str | None, end: str | None, interval: str) -> pd.DataFrame:
        calls.append(interval)
        if len(calls) < 2:
            raise ConnectionError("rate limited")
        return _raw_yahoo()

    df = YahooAdapter(fetch=flaky, backoff_seconds=0).get_ohlcv("SPY", "1d")
    assert len(df) == 30 and calls == ["1d", "1d"]


def test_adapter_reports_unavailable() -> None:
    def down(*_: object) -> pd.DataFrame:
        raise ConnectionError("403 CONNECT")

    with pytest.raises(DataUnavailableError, match=r"finance\.yahoo\.com"):
        YahooAdapter(fetch=down, retries=2, backoff_seconds=0).get_ohlcv("SPY", "1d")
    empty = YahooAdapter(fetch=lambda *_: pd.DataFrame(), backoff_seconds=0)
    with pytest.raises(DataUnavailableError):
        empty.get_ohlcv("SPY", "1d")
    with pytest.raises(ValueError):
        empty.get_ohlcv("SPY", "3m")


def test_universe() -> None:
    assert set(UNIVERSES["tradable"]) <= set(UNIVERSES["default"])
    assert "SPY" in UNIVERSES["proxies"] and "SPY" not in UNIVERSES["tradable"]
    assert all(get_instrument(s).currency == "EUR" for s in UNIVERSES["eur"])
    assert not get_instrument("ZZZZ").tradable_t212_eu
    assert resolve_universe("AAPL, SAN.MC") == ["AAPL", "SAN.MC"]
    assert resolve_universe("eur") == list(UNIVERSES["eur"])
    with pytest.raises(ValueError):
        resolve_universe(" , ")


def test_trading212_costs() -> None:
    eur = CostModel.trading212("EUR")
    usd = CostModel.trading212("usd")
    assert eur.fee_pct == usd.fee_pct == 0 and eur.fee_fixed == 0
    assert eur.fx_pct == 0 and usd.fx_pct == T212_FX_FEE
    assert usd.round_trip_pct(100) - eur.round_trip_pct(100) == pytest.approx(2 * T212_FX_FEE)
