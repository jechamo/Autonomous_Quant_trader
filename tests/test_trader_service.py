from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aqt.brokers.base import BrokerError
from aqt.brokers.paper import PaperExchange
from aqt.stream.binance import FeedStatus
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Event
from aqt.stream.store import SQLiteStore
from aqt.stream.synthetic import synthetic_ticks
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from services.trader.app import create_app
from services.trader.cli import app as cli
from services.trader.runtime import TraderRuntime
from tests.test_stream import SYM, make_engine, q, seed_evidence, warm


def _runtime(store: SQLiteStore | None = None) -> TraderRuntime:
    store = store or SQLiteStore()
    eng = StreamingEngine(EngineConfig(symbols=(SYM,), bar_seconds=1.0), store=store)
    return TraderRuntime(eng, store, feed=None, clock=lambda: 1_700_000_000.0, tick_seconds=0.01)


def test_api_state_control_and_persistence(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "a.sqlite")
    rt = _runtime(store)
    with TestClient(create_app(rt)) as client:
        state = client.get("/api/state").json()
        assert state["mode"] == "PAPER" and state["feed"]["last_error"] == "no feed"
        r = client.post("/api/control", json={"kill_switch": True, "aggressiveness": 20})
        assert r.json() == {"kill_switch": True, "paused": False, "aggressiveness": 20.0}
        assert client.post("/api/control", json={"aggressiveness": 150}).status_code == 422
        off = client.post("/api/control", json={"kill_switch": False}).json()
        assert off["kill_switch"] is False and not rt.engine.kill_switch
        assert client.post("/api/control", json={"kill_switch": True}).json()["kill_switch"]
        r = client.post("/api/control", json={"flatten": True})
        assert r.json()["paused"] is True
        assert client.get("/api/trades?book=paper").json() == []
        assert client.get("/api/trades?book=bogus").status_code == 400
        assert isinstance(client.get("/api/decisions").json(), list)
        assert isinstance(client.get("/api/equity").json(), list)
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["kill_switch"] is True
        assert "AQT Streaming" in client.get("/").text
    # Controls survive a restart.
    rt2 = _runtime(store)
    assert rt2.engine.kill_switch and rt2.engine.paused
    assert rt2.engine.profile.aggressiveness == 20.0


def test_foreign_origins_are_refused() -> None:
    with TestClient(create_app(_runtime())) as client:
        bad = {"origin": "https://evil.example"}
        assert (
            client.post("/api/control", json={"kill_switch": False}, headers=bad).status_code == 403
        )
        assert (
            client.get("/api/state", headers={"origin": "http://localhost:8000"}).status_code == 200
        )
        assert client.get("/api/state", headers={"origin": "http://[::1]:8000"}).status_code == 200
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws", headers=bad) as ws:
            ws.receive_json()


class _FakeFeed:
    def __init__(self, events: list[Event]) -> None:
        self.status = FeedStatus()
        self._events = events

    async def events(self) -> AsyncIterator[Event]:
        self.status.connected = True
        for e in self._events:
            self.status.messages += 1
            self.status.last_message_at = e.ts
            yield e
            await asyncio.sleep(0)


def test_runtime_consumes_feed_records_ticks_and_stops_cleanly() -> None:
    events = synthetic_ticks(seconds=30, seed=2)
    store = SQLiteStore()
    eng = StreamingEngine(EngineConfig(symbols=(SYM,), bar_seconds=1.0), store=store)
    rt = TraderRuntime(
        eng, store, _FakeFeed(events), clock=lambda: events[-1].ts, tick_seconds=0.01
    )

    async def go() -> None:
        rt.start()
        await asyncio.sleep(0.3)
        await rt.stop()

    asyncio.run(go())
    assert eng.events == len(events)
    assert sum(r["n"] for r in store.tick_summary()) == len(events)
    snap = rt.snapshot()
    assert snap["feed"]["connected"] and snap["feed"]["messages"] == len(events)


def test_crashed_task_pauses_engine() -> None:
    class Boom(_FakeFeed):
        async def events(self) -> AsyncIterator[Event]:
            raise RuntimeError("boom")
            yield  # pragma: no cover

    rt = _runtime()
    rt.feed = Boom([])

    async def go() -> None:
        rt.start()
        await asyncio.sleep(0.05)
        await rt.stop()

    asyncio.run(go())
    assert rt.engine.paused and not rt.engine.feed_healthy


def test_cli_replay_and_ticks(tmp_path: Path) -> None:
    db = tmp_path / "ticks.sqlite"
    store = SQLiteStore(db)
    for e in synthetic_ticks(seconds=900, seed=4, vol_per_sqrt_s=0.0005):
        store.record(e)
    store.close()
    runner = CliRunner()
    res = runner.invoke(cli, ["ticks", "--db", str(db)])
    assert res.exit_code == 0 and SYM in res.output
    out = tmp_path / "replay.sqlite"
    res = runner.invoke(cli, ["replay", "--db", str(db), "--bar-seconds", "2", "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "Shadow evidence" in res.output and "Paper book" in res.output
    empty = runner.invoke(cli, ["replay", "--db", str(tmp_path / "none.sqlite")])
    assert empty.exit_code == 1


def test_cli_refuses_live_and_public_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["run", "--host", "0.0.0.0", "--no-exchange-info", "--no-open"])
    assert res.exit_code != 0
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    res = runner.invoke(cli, ["run", "--no-exchange-info", "--no-open"])
    assert res.exit_code == 2 and "LIVE is not available" in res.output


def test_engine_handles_exchange_rejections(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = make_engine()
    seed_evidence(eng)
    eng.broker.healthy = False  # unhealthy API: the Risk Engine refuses before any order
    warm(eng)
    assert eng._positions == {}
    assert any("api_health" in r for d in eng.decisions for r in d.reasons)

    eng1 = make_engine()
    seed_evidence(eng1)

    def boom(_: object) -> None:
        raise BrokerError("exchange down")

    monkeypatch.setattr(eng1.broker, "place_order", boom)
    warm(eng1)
    assert eng1._positions == {}
    assert any(d.action == "BROKER_ERROR" for d in eng1.decisions)

    eng2 = make_engine()
    seed_evidence(eng2)
    eng2.broker.min_notional = 10_000.0  # exchange minimum above what risk allows
    warm(eng2)
    assert eng2._positions == {}
    assert any(d.action == "BROKER_REJECT" for d in eng2.decisions)


def test_engine_drops_orders_rejected_at_execution() -> None:
    eng = make_engine()
    eng.broker = PaperExchange(cash=100.0, latency_s=0.0, min_notional=1.0)
    seed_evidence(eng)
    ts = warm(eng, 0.0, 5)
    eng.broker.cash = 0.0  # cash vanishes between order and fill
    eng.on_event(q(ts + 0.5, 100.0))
    eng.on_event(q(ts + 0.6, 100.0))
    assert not any(m.side == "BUY" for m in eng._pending.values())
    assert eng.reconciled
