from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
import pytest
from aqt.lab.registry import RuleRecord, RuleRegistry, RuleStatus
from aqt.strategies.intraday import INTRADAY_CATALOG
from aqt.stream.dsl_strategy import ResearchBarBook, rule_id_for
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.history import HistoricalFeed, kline_events
from aqt.stream.store import SQLiteStore
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from services.trader import cli as cli_module
from services.trader.app import create_app
from services.trader.lab_scheduler import LabScheduler
from services.trader.runtime import TraderRuntime
from tests.test_lab import T0, make_loader, synthetic_klines

SYM = "PLANTUSDC"


def _engine(store: SQLiteStore) -> StreamingEngine:
    return StreamingEngine(EngineConfig(symbols=(SYM,), run_id="live-USDC"), store=store)


def _promote_one(store: SQLiteStore) -> str:
    reg = RuleRegistry(store)
    spec = INTRADAY_CATALOG["flow_momentum"][0].render()
    rid = rule_id_for(spec, SYM)
    reg.upsert(RuleRecord(rid, SYM, 60.0, spec))
    reg.set_status(rid, RuleStatus.CHALLENGER, "test")
    return rid


def test_scheduler_runs_research_reviews_and_hot_loads_rules() -> None:
    store = SQLiteStore()
    eng = _engine(store)
    calls: list[float] = []

    async def research(end_ts: float) -> str:
        calls.append(end_ts)
        _promote_one(store)
        return ""

    clock = [1_000.0]
    lab = LabScheduler(
        eng, store, ResearchBarBook(), research, every_s=3600, clock=lambda: clock[0]
    )
    assert lab.state.next_due == 1_000.0  # never researched: due immediately
    n_base = len(eng.strategies)
    asyncio.run(lab.run_now())
    assert calls == [1_000.0]
    assert len(eng.strategies) == n_base + 1  # the promoted rule now trades in shadow
    st = lab.status()
    assert st["rules"]["challenger"] == 1 and st["next_due"] == 1_000 + 3600 and not st["running"]
    ov = lab.overview()
    assert ov["rules"][0]["status"] == "challenger" and ov["rules"][0]["live"] is not None
    assert {"runs", "events", "lessons"} <= set(ov)


def test_scheduler_survives_failing_research_and_pauses_simulations() -> None:
    store = SQLiteStore()
    paused: list[bool] = []

    async def boom(end_ts: float) -> str:
        raise RuntimeError("network down")

    lab = LabScheduler(_engine(store), store, ResearchBarBook(), boom, on_pause=paused.append)
    asyncio.run(lab.run_now())
    assert "network down" in lab.state.last_error and paused == [True, False]
    off = LabScheduler(_engine(store), store, ResearchBarBook(), None)
    assert not off.state.enabled and off.state.next_due is None
    assert not off.trigger()
    asyncio.run(off.run_now())  # no-op without a research runner


def test_lab_endpoints() -> None:
    store = SQLiteStore()
    eng = _engine(store)

    async def research(end_ts: float) -> str:
        await asyncio.sleep(0.05)
        return ""

    lab = LabScheduler(eng, store, ResearchBarBook(), research, every_s=0, poll_s=0.01)
    rt = TraderRuntime(eng, store, feed=None, clock=lambda: 1.0, tick_seconds=0.01, lab=lab)
    with TestClient(create_app(rt)) as client:
        assert client.get("/api/research").json()["status"]["enabled"] is False  # every_s=0
        assert client.get("/api/state").json()["lab"]["rules"]["challenger"] == 0
    lab.state.enabled = True
    with TestClient(create_app(rt)) as client:
        assert client.post("/api/research/run").json() == {"started": True}
        assert client.post("/api/research/run").json() == {"started": False}  # already running
    plain = TraderRuntime(_engine(SQLiteStore()), SQLiteStore(), feed=None, clock=lambda: 1.0)
    with TestClient(create_app(plain)) as client:
        assert client.get("/api/research").json()["status"] == {"enabled": False}
        assert client.post("/api/research/run").status_code == 409


def test_historical_feed_pause() -> None:
    events = list(kline_events(synthetic_klines(0.01, seed=1, planted=False), SYM))
    feed = HistoricalFeed(events, T0 / 1000, T0 / 1000 + 900, speed=0)

    async def go() -> int:
        feed.pause(True)
        got: list[object] = []

        async def consume() -> None:
            async for e in feed.events():
                got.append(e)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        held = len(got)
        assert feed.info().paused
        feed.pause(False)
        await task
        return held

    assert asyncio.run(go()) == 0
    assert feed.info().finished and not feed.info().paused


def test_simulate_learn_headless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = {SYM: synthetic_klines(4.2, seed=1, planted=True, start_ms=T0)}
    loader = make_loader(data)

    def load(symbol: str, start_ms: int, end_ms: int, **_: object) -> pd.DataFrame:
        return loader(symbol, start_ms, end_ms)

    monkeypatch.setattr("aqt.stream.history.load_klines_1s", load)
    monkeypatch.setattr("aqt.stream.binance.fetch_symbol_info", lambda _s: {})
    end = pd.Timestamp(T0 + int(4.2 * 86_400_000) - 3_600_000, unit="ms", tz="UTC")
    res = CliRunner().invoke(
        cli_module.app,
        ["simulate", "--symbols", SYM, "--hours", "4", "--learn", "--lab-days", "3",
         "--research-every", "2", "--workers", "1", "--families", "flow_momentum",
         "--headless", "--end", end.strftime("%Y-%m-%dT%H:%M:%S"),
         "--db", str(tmp_path / "sim.sqlite")],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    assert "initial research" in res.output and "research #2" in res.output
    assert "Research Lab:" in res.output and "Buy & Hold" in res.output
    reg = RuleRegistry(SQLiteStore(tmp_path / "sim.sqlite"))
    assert len(reg.runs()) >= 2
