from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from aqt.common.config import load_dotenv
from aqt.lab.cycle import BarData, LabConfig, run_research_cycle
from aqt.stream.alpaca import (
    AlpacaFeed,
    AlpacaParser,
    alpaca_credentials,
    parse_alpaca_bars,
    parse_calendar,
    stock_bar_loader,
)
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Quote, TradeTick
from aqt.stream.session import NY, AlwaysOpen, UsEquitySession, make_session
from aqt.stream.stocks import bar_events, bvc_taker_buy, parse_yahoo_chart, with_bvc
from aqt.stream.store import SQLiteStore
from typer.testing import CliRunner

from services.trader import cli as cli_module
from tests.test_stream import SMALL, Always, seed_evidence

TUE_1000 = datetime(2026, 9, 29, 10, 0, tzinfo=NY).timestamp()  # a Tuesday


def minute_bars(n: int, start: float, seed: int = 1, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.0008, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    idx = pd.to_datetime(start + 60 * np.arange(n), unit="s", utc=True)
    df = pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.0003,
         "low": np.minimum(open_, close) * 0.9997, "close": close,
         "volume": rng.exponential(1000, n) + 10},
        index=idx,
    )  # fmt: skip
    return with_bvc(df)


def test_us_equity_session() -> None:
    s = UsEquitySession()
    assert s.is_open(TUE_1000)
    assert s.seconds_to_close(TUE_1000) == pytest.approx(6 * 3600)
    assert not s.is_open(datetime(2026, 9, 29, 9, 29, tzinfo=NY).timestamp())
    assert not s.is_open(datetime(2026, 9, 29, 16, 0, tzinfo=NY).timestamp())
    assert not s.is_open(datetime(2026, 10, 3, 12, 0, tzinfo=NY).timestamp())  # Saturday
    assert s.seconds_to_close(datetime(2026, 10, 3, 12, 0, tzinfo=NY).timestamp()) == float("inf")
    holiday = UsEquitySession(holidays=frozenset({date(2026, 9, 29)}))
    assert not holiday.is_open(TUE_1000)
    assert AlwaysOpen().is_open(0) and AlwaysOpen().seconds_to_close(0) == float("inf")
    assert isinstance(make_session("us_equity"), UsEquitySession)
    with pytest.raises(ValueError):
        make_session("mars")


def _quotes(start: float, seconds: int, mid: float = 100.0) -> list[Quote]:
    return [
        Quote("AAPL", start + i + 0.5, mid * (1 + (0.0002 if i % 2 else 0)) - 0.01, 50,
              mid * (1 + (0.0002 if i % 2 else 0)) + 0.01, 50)
        for i in range(seconds)
    ]  # fmt: skip


def test_engine_is_intraday_only_for_stocks() -> None:
    cfg = EngineConfig(
        symbols=("AAPL",), bar_seconds=1.0, session="us_equity", latency_s=0.0,
        entry_cooldown_seconds=1e9, min_order_notional=1.0,
        feature_params=SMALL,
    )  # fmt: skip
    eng = StreamingEngine(cfg, strategies=[Always()])
    eng.set_adv("AAPL", 1e7)
    seed_evidence(eng)
    t_open = datetime(2026, 9, 29, 15, 40, tzinfo=NY).timestamp()
    for q in _quotes(t_open, 60):
        eng.on_event(q)
    assert "AAPL" in eng._positions  # entered at 15:40 (more than 15 minutes to the close)
    for q in _quotes(t_open + 60, 15 * 60):  # run to 15:56
        eng.on_event(q)
    trades = eng.paper_trades()
    assert trades and trades[0].exit_reason == "session_end"
    assert "AAPL" not in eng._positions and eng._shadow == {}
    snap = eng.snapshot()
    assert snap["counters"]["paper_trades"] == 1  # no new entries in the last 15 minutes
    closed = StreamingEngine(cfg, strategies=[Always()])
    seed_evidence(closed)
    for q in _quotes(datetime(2026, 10, 3, 12, 0, tzinfo=NY).timestamp(), 30):  # Saturday
        closed.on_event(q)
    assert closed.strategy_stats["always"]["signals"] == 0


def test_bvc_flow_estimate() -> None:
    df = minute_bars(300, TUE_1000)
    tb = bvc_taker_buy(df)
    assert ((tb >= 0) & (tb <= df["volume"] + 1e-9)).all()
    up = df["close"].pct_change() > 0
    frac = tb / df["volume"]
    assert frac[up].iloc[20:].mean() > 0.5 > frac[~up].iloc[20:].mean()
    pd.testing.assert_series_equal(bvc_taker_buy(df.iloc[:100]), tb.iloc[:100])  # causal


def test_parse_yahoo_chart() -> None:
    quote = {
        "open": [10, None, 10.2, 10.2],
        "high": [10.1, None, 10.1, 10.1],
        "low": [9.9, None, 10.0, 10.0],
        "close": [10.05, None, 10.0, 10.0],
        "volume": [100, None, None, None],
    }
    ts = [1790861400, 1790861460, 1790861520, 1790861520]
    payload = {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [quote]}}]}}
    df = parse_yahoo_chart(payload)
    assert len(df) == 2 and df.index.is_unique
    assert df["high"].iloc[1] == 10.2  # high repaired to cover the open
    assert df["volume"].iloc[1] == 0.0


def test_bar_events_are_ordered_and_signed() -> None:
    df = minute_bars(3, TUE_1000)
    ev = list(bar_events(df, "AAPL"))
    assert [e.ts for e in ev] == sorted(e.ts for e in ev)
    trades = [e for e in ev if isinstance(e, TradeTick)]
    total = sum(t.qty for t in trades[:2])
    assert total == pytest.approx(df["volume"].iloc[0])


def test_alpaca_parser_signs_trades() -> None:
    p = AlpacaParser(clock=lambda: 5.0)
    assert p.parse({"T": "q", "S": "AAPL", "bp": 99.9, "bs": 3, "ap": 100.1, "as": 4}) == Quote(
        "AAPL", 5.0, 99.9, 3, 100.1, 4
    )
    buy = p.parse({"T": "t", "S": "AAPL", "p": 100.1, "s": 10})
    sell = p.parse({"T": "t", "S": "AAPL", "p": 99.9, "s": 5})
    assert isinstance(buy, TradeTick) and not buy.buyer_is_maker
    assert isinstance(sell, TradeTick) and sell.buyer_is_maker
    uptick = p.parse({"T": "t", "S": "AAPL", "p": 100.0, "s": 1})  # inside: tick rule (up)
    assert isinstance(uptick, TradeTick) and not uptick.buyer_is_maker
    assert p.parse({"T": "q", "S": "AAPL", "bp": 2, "bs": 1, "ap": 1, "as": 1}) is None
    assert p.parse({"T": "t", "S": "AAPL"}) is None
    assert p.parse({"T": "success", "msg": "connected"}) is None
    first = AlpacaParser().parse({"T": "t", "S": "MSFT", "p": 10, "s": 1})
    assert isinstance(first, TradeTick)


def test_alpaca_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    assert alpaca_credentials({}) is None
    assert alpaca_credentials({"ALPACA_API_KEY_ID": "k", "ALPACA_API_SECRET_KEY": "s"}) == (
        "k",
        "s",
    )
    feed = AlpacaFeed(["aapl"], "k", "secret-value")
    assert "secret-value" not in repr(feed) and feed.symbols == ["AAPL"]
    with pytest.raises(ValueError):
        AlpacaFeed([], "k", "s")
    assert parse_calendar([{"date": "2026-09-29"}]) == {date(2026, 9, 29)}
    body = {"bars": {"AAPL": [
        {"t": "2026-09-29T13:31:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10},  # 09:31 NY
        {"t": "2026-09-29T12:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10},  # pre-market
    ]}}  # fmt: skip
    bars = parse_alpaca_bars(body, "AAPL")
    assert len(bars) == 1 and bars["close"].iloc[0] == 1.5
    empty = parse_alpaca_bars({}, "AAPL")
    assert empty.empty and str(empty.index.tz) == "UTC"  # holidays concat with real days
    assert len(pd.concat([bars, empty])) == 1
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    assert stock_bar_loader({})[0] == "yahoo"
    assert stock_bar_loader({"ALPACA_API_KEY_ID": "k", "ALPACA_API_SECRET_KEY": "s"})[0] == "alpaca"


def test_load_dotenv(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("# comment\nA=1\nB = 'two'\nC=\"x\"\nbroken\nA=ignored\n", encoding="utf-8")
    env = {"C": "already"}
    assert load_dotenv(str(f), env) == ["A", "B"]
    assert env == {"A": "1", "B": "two", "C": "already"}
    assert load_dotenv(str(tmp_path / "missing"), env) == []


def test_lab_cycle_runs_on_stock_bars() -> None:
    days = [
        datetime(2026, 9, d, 9, 30, tzinfo=NY).timestamp() for d in (21, 22, 23, 24, 25, 28, 29)
    ]
    frames = [minute_bars(390, t, seed=i) for i, t in enumerate(days)]
    data = pd.concat(frames)

    def loader(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        lo = pd.Timestamp(start_ms, unit="ms", tz="UTC")
        hi = pd.Timestamp(end_ms, unit="ms", tz="UTC")
        return data[(data.index >= lo) & (data.index < hi)]

    cfg = LabConfig(
        symbols=("AAPL",), quote="USD", days=10, fee_pct=0.00002, spread_pct=0.0002,
        session="us_equity", families=("bollinger_reversion",), workers=1, monte_carlo_sims=200,
    )  # fmt: skip
    end_ms = int((days[-1] + 7 * 3600) * 1000)
    res = run_research_cycle(SQLiteStore(), cfg, BarData(loader, 0.0002), end_ms=end_ms)
    assert res.error == "" and res.summary["n_hypotheses"] > 0
    assert res.summary["n_bars"]["AAPL@1min"] == 7 * 390


def test_cli_stocks_requires_alpaca_keys_for_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    monkeypatch.setattr(cli_module, "load_dotenv", lambda *a, **k: [])
    res = CliRunner().invoke(cli_module.app, ["run", "--market", "stocks", "--no-open"])
    assert res.exit_code == 2 and "alpaca.markets" in res.output
    bad = CliRunner().invoke(cli_module.app, ["research", "--market", "forex"])
    assert bad.exit_code != 0


def test_cli_simulate_stocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    start = datetime(2026, 9, 29, 9, 30, tzinfo=NY).timestamp()

    def loader(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        df = minute_bars(390, start, seed=len(symbol))
        lo = pd.Timestamp(start_ms, unit="ms", tz="UTC")
        return df[df.index >= lo]

    monkeypatch.setattr(cli_module, "_stock_loader", lambda: loader)
    end = datetime(2026, 9, 29, 16, 0, tzinfo=NY).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    args = ["simulate", "--market", "stocks", "--symbols", "AAPL,MSFT", "--hours", "6.5"]
    args += ["--headless", "--end", end, "--db", str(tmp_path / "s.sqlite")]
    res = CliRunner().invoke(cli_module.app, args)
    assert res.exit_code == 0, res.output
    assert "USD" in res.output and "AAPL, MSFT" in res.output
