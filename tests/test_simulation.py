from __future__ import annotations

import asyncio
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Quote, TradeTick
from aqt.stream.features import FeatureParams
from aqt.stream.history import HistoricalFeed, kline_events, klines_frame, merge_events
from aqt.stream.store import SQLiteStore
from aqt.stream.strategies import default_stream_strategies, scaled_features
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from services.trader import cli as cli_module
from services.trader.app import create_app
from services.trader.runtime import TraderRuntime

T0 = 1_700_000_000_000  # ms


def fake_klines(
    n: int = 600, price: float = 100.0, seed: int = 1, start_ms: int = T0
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    p = price
    for i in range(n):
        o = p
        p *= math.exp(rng.normal(0, 0.0005))
        hi, lo = max(o, p) * 1.0002, min(o, p) * 0.9998
        v = float(rng.exponential(1.0))
        rows.append([start_ms + i * 1000, str(o), str(hi), str(lo), str(p), str(v), 0, "0", 1,
                     str(v * rng.uniform(0, 1)), "0", "0"])  # fmt: skip
    return klines_frame(rows)


def test_klines_become_conservative_quotes_and_signed_trades() -> None:
    df = klines_frame(
        [
            [T0, "100", "101", "99", "100.5", "2.0", 0, "0", 3, "1.5", "0", "0"],  # up-second
            [T0 + 1000, "100.5", "100.6", "99.5", "99.8", "1.0", 0, "0", 1, "0", "0", "0"],
            [T0, "100", "101", "99", "100.5", "2.0", 0, "0", 3, "1.5", "0", "0"],  # duplicate
        ]
    )
    assert len(df) == 2
    ev = list(kline_events(df, "X", spread_pct=0.0002))
    quotes = [e for e in ev if isinstance(e, Quote)]
    mids = [round(q.mid, 6) for q in quotes[:4]]
    assert mids == [100.0, 99.0, 101.0, 100.5]  # up-second visits the low first
    assert [round(q.mid, 6) for q in quotes[4:8]] == [100.5, 100.6, 99.5, 99.8]
    assert quotes[0].ask / quotes[0].bid - 1 == pytest.approx(0.0002, rel=1e-3)
    assert quotes[0].bid_qty == quotes[0].ask_qty == 2.0  # depth = traded volume, neutral book
    trades = [e for e in ev if isinstance(e, TradeTick)]
    assert [(t.qty, t.buyer_is_maker) for t in trades] == [(1.5, False), (0.5, True), (1.0, True)]
    assert [e.ts for e in ev] == sorted(e.ts for e in ev)


def test_merge_is_time_ordered() -> None:
    a = list(kline_events(fake_klines(30, seed=1), "A"))
    b = list(kline_events(fake_klines(30, seed=2, start_ms=T0 + 500), "B"))
    merged = list(merge_events([a, b]))
    assert len(merged) == len(a) + len(b)
    assert [e.ts for e in merged] == sorted(e.ts for e in merged)


def test_historical_feed_runs_in_simulated_time() -> None:
    events = list(kline_events(fake_klines(50), "X"))
    feed = HistoricalFeed(events, T0 / 1000, T0 / 1000 + 50, speed=0)
    assert feed.info().progress == 0.0

    async def drain() -> int:
        return len([e async for e in feed.events()])

    assert asyncio.run(drain()) == len(events)
    info = feed.info()
    assert info.finished and info.progress == pytest.approx(1.0, abs=0.02)
    assert feed.now() == events[-1].ts and feed.status.healthy(feed.now())
    paced = HistoricalFeed(events[:9], T0 / 1000, T0 / 1000 + 2, speed=1000)
    assert sum(1 for _ in asyncio.run(_collect(paced))) == 9
    with pytest.raises(ValueError):
        paced.set_speed(-1)
    with pytest.raises(ValueError):
        HistoricalFeed([], 0, 1, speed=-2)


async def _collect(feed: HistoricalFeed) -> list[object]:
    return [e async for e in feed.events()]


def test_engine_tracks_buy_and_hold_and_unfiltered_shadow() -> None:
    events = list(kline_events(fake_klines(900, seed=4), "X"))
    eng = StreamingEngine(EngineConfig(symbols=("X",), bar_seconds=5.0, initial_cash=10_000))
    for e in events:
        eng.on_event(e)
    first, last = events[0], [e for e in events if isinstance(e, Quote)][-1]
    assert isinstance(first, Quote)
    assert eng.buy_hold_equity == pytest.approx(10_000 * last.mid / first.mid)
    snap = eng.snapshot()
    assert snap["account"]["buy_hold_equity"] == pytest.approx(eng.buy_hold_equity)
    assert all("bh" in p for p in snap["equity"])
    for s in snap["strategies"]:
        r = eng.evidence.returns(s["strategy_id"])
        assert s["shadow_cum_return"] == pytest.approx(float(np.prod([1 + x for x in r]) - 1))
    assert eng.first_ts == first.ts


def test_strategies_use_features_scaled_to_their_horizon() -> None:
    catalog = default_stream_strategies(bar_seconds=5.0)
    slow = next(s for s in catalog if s.strategy_id == "momentum_20m")
    assert slow.features == scaled_features(240)
    assert slow.features is not None and slow.features.slow_span == 240
    eng = StreamingEngine(EngineConfig(symbols=("X",)))
    st = eng.symbols["X"]
    assert len(st.scaled) == len({s.features for s in catalog})
    assert st.warmup_needed == max(p.warmup for p in st.scaled) > FeatureParams().warmup


def test_simulation_runtime_reports_progress_and_speed() -> None:
    events = list(kline_events(fake_klines(120), "X"))
    feed = HistoricalFeed(events, T0 / 1000, T0 / 1000 + 120, speed=0)
    store = SQLiteStore()
    eng = StreamingEngine(EngineConfig(symbols=("X",), run_id="sim-test"), store=store)
    store.set_setting("kill_switch", "true")  # a live setting must not leak into a simulation
    rt = TraderRuntime(eng, store, feed, record=False, clock=feed.now, persist_controls=False)
    assert not eng.kill_switch
    with TestClient(create_app(rt)) as client:
        client.post("/api/control", json={"speed": 50, "kill_switch": True})
        assert feed.speed == 50 and eng.kill_switch
        assert store.get_setting("kill_switch") == "true"  # untouched by the simulation
        state = client.get("/api/state").json()
        assert state["mode"] == "SIMULATION"
        assert set(state["simulation"]) >= {"progress", "speed", "sim_ts", "finished"}
        assert client.post("/api/control", json={"speed": -1}).status_code == 422


def test_cli_simulate_headless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_load(symbol: str, start_ms: int, end_ms: int, **_: object) -> pd.DataFrame:
        return fake_klines(1800, seed=len(symbol), start_ms=start_ms)

    def no_info(_: object) -> dict[str, object]:
        raise RuntimeError("offline")

    monkeypatch.setattr("aqt.stream.history.load_klines_1s", fake_load)
    monkeypatch.setattr("aqt.stream.binance.fetch_symbol_info", no_info)
    res = CliRunner().invoke(
        cli_module.app,
        ["simulate", "--symbols", "BTCUSDC,ETHUSDC", "--hours", "0.5", "--cash", "10000",
         "--headless", "--end", "2026-09-30T00:00", "--db", str(tmp_path / "sim.sqlite")],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    assert "Buy & Hold" in res.output and "Portfolio" in res.output and "USDC" in res.output
    bad = CliRunner().invoke(
        cli_module.app, ["simulate", "--symbols", "BTCUSDC,ETHEUR", "--headless"]
    )
    assert bad.exit_code != 0
