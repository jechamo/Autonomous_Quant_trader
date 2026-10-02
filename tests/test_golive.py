from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from aqt.brokers.base import BrokerHealth
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Quote
from aqt.stream.golive import DAY, GateConfig, evaluate_gate, max_drawdown, session_returns
from aqt.stream.records import RoundTrip
from aqt.stream.store import SQLiteStore
from fastapi.testclient import TestClient

from services.trader.app import create_app
from services.trader.golive_monitor import GoLiveMonitor
from services.trader.notify import make_notifier
from services.trader.runtime import TraderRuntime

RUN = "live-USD-stocks-alpaca"
T0 = 1_700_000_000.0


def trip(ts: float, ret: float, notional: float = 1000.0) -> RoundTrip:
    return RoundTrip(
        book="paper", strategy_id="s", symbol="AAA", entry_ts=ts - 3600, exit_ts=ts,
        entry_price=100.0, exit_price=100 * (1 + ret), quantity=notional / 100,
        pnl=notional * ret, fees=1.0, net_return=ret, exit_reason="target",
    )  # fmt: skip


def paper_history(
    store: SQLiteStore, days: int = 30, edge: float = 0.004, kill_test: bool = True
) -> float:
    """A month of paper trading that beats Buy & Hold: 2 trades a day, mostly winners."""
    store.log_ops_event(RUN, T0 - 1, "session_start")
    eq, bh = 10_000.0, 10_000.0
    for h in range(days * 24 + 1):
        ts = T0 + h * 3600
        store.log_equity(RUN, ts, eq, eq, 0.0, bh)
        eq *= 1.0002
        bh *= 1.00005
    for d in range(days):
        for k, sign in enumerate((1, 1 if d % 5 else -1)):
            store.log_round_trip(RUN, trip(T0 + d * DAY + (k + 1) * 3600, sign * edge + 0.001 * k))
    if kill_test:
        store.log_ops_event(RUN, T0 + DAY, "kill_switch_on")
        store.log_ops_event(RUN, T0 + DAY + 60, "kill_switch_off")
    return T0 + days * DAY


def test_gate_passes_with_a_month_of_consistent_beating_paper() -> None:
    store = SQLiteStore()
    now = paper_history(store)
    rep = evaluate_gate(store, RUN, now, max_dd=0.10, external_venue=True)
    assert rep.ready, rep.summary()
    assert rep.passed == len(rep.criteria) == 10
    d = rep.to_dict()
    assert d["ready"] and not d["live_broker_available"] and "READY" in rep.summary()


@pytest.mark.parametrize(
    ("change", "failing"),
    [
        ("local_venue", {"venue", "reconciliation"}),
        ("mismatch", {"reconciliation"}),
        ("no_kill_test", {"kill_switch"}),
        ("too_soon", {"days", "trades", "consistency"}),
    ],
)
def test_gate_names_what_is_missing(change: str, failing: set[str]) -> None:
    store = SQLiteStore()
    now = paper_history(
        store, days=20 if change == "too_soon" else 30, kill_test=change != "no_kill_test"
    )
    if change == "mismatch":
        store.log_ops_event(RUN, T0 + 5 * DAY, "reconciliation_mismatch", "AAA 3 vs 2")
    rep = evaluate_gate(store, RUN, now, 0.10, external_venue=change != "local_venue")
    assert {c.key for c in rep.criteria if not c.ok} == failing, rep.summary()
    assert not rep.ready and "not ready" in rep.summary()


def test_empty_account_and_losing_account_fail_safely() -> None:
    rep = evaluate_gate(SQLiteStore(), RUN, T0, 0.10, external_venue=True)
    assert {c.key for c in rep.criteria if c.ok} == {"venue", "reconciliation"}
    assert not rep.ready
    store = SQLiteStore()
    now = paper_history(store, edge=-0.004)
    bad = {c.key for c in evaluate_gate(store, RUN, now, 0.10, True).criteria if not c.ok}
    assert {"net", "edge", "consistency"} <= bad


def test_session_returns_skip_restarts_and_drawdown() -> None:
    rows = [
        {"ts": 0.0, "equity": 100.0, "buy_hold": 100.0},
        {"ts": 5.0, "equity": 110.0, "buy_hold": 105.0},
        # restart: Buy & Hold resets to the initial cash; the jump must not count
        {"ts": 20.0, "equity": 110.0, "buy_hold": 100.0},
        {"ts": 25.0, "equity": 99.0, "buy_hold": 101.0},
        {"ts": 9_000.0, "equity": 50.0, "buy_hold": 50.0},  # gap > session_gap_s
        {"ts": 9_005.0, "equity": 55.0, "buy_hold": None},  # no benchmark logged
    ]
    eq, bh = session_returns(rows, [10.0], gap_s=3600)
    assert eq == pytest.approx([1.1, 0.9]) and bh == pytest.approx([1.05, 1.01])
    assert max_drawdown(eq) == pytest.approx(0.10)
    assert max_drawdown([]) == 0.0


class StubBroker:
    def __init__(self) -> None:
        self.h = BrokerHealth(ok=True, detail="")

    def health(self) -> BrokerHealth:
        return self.h


class StubEngine:
    def __init__(self) -> None:
        self.cfg = EngineConfig(symbols=("AAA",), run_id=RUN)
        self.broker = StubBroker()
        self.reconciled = True

        class P:
            max_drawdown = 0.10

        self.profile = P()


def test_monitor_records_incidents_and_notifies_once_per_flip() -> None:
    store = SQLiteStore()
    now = [paper_history(store)]
    sent: list[tuple[str, str]] = []
    eng = StubEngine()
    mon = GoLiveMonitor(
        eng,  # type: ignore[arg-type]
        store,
        lambda t, m: sent.append((t, m)),
        external_venue=True,
        clock=lambda: now[0],
    )
    mon.begin()
    eng.broker.h = BrokerHealth(ok=False, detail="HTTP 503")
    mon.sample()
    eng.broker.h = BrokerHealth(ok=True, detail="")
    mon.sample()
    eng.reconciled = False
    mon.sample()  # one bad sample is a transient (fill in flight)
    assert not store.ops_events(RUN, kinds=["reconciliation_mismatch"])
    eng.reconciled = True
    mon.sample()
    kinds = [e["kind"] for e in store.ops_events(RUN)]
    assert kinds[-2:] == ["broker_down", "broker_recovered"]

    assert mon.evaluate().ready and len(sent) == 1 and "listo para real" in sent[0][0]
    mon.evaluate()
    assert len(sent) == 1  # no repeat while it stays ready
    eng.reconciled = False
    mon.sample()
    mon.sample()  # persists → incident → the gate drops
    eng.reconciled = True
    mon.sample()
    assert [e["kind"] for e in store.ops_events(RUN)][-2:] == [
        "reconciliation_mismatch",
        "reconciliation_ok",
    ]
    assert not mon.evaluate().ready and "ya no está listo" in sent[1][0]
    ov = mon.overview()
    assert ov["events"][0]["kind"] == "gate_lost" and ov["total"] == 10
    assert all(e["kind"] != "session_start" for e in ov["events"])


def test_runtime_api_kill_switch_events_and_loop() -> None:
    store = SQLiteStore()
    eng = StreamingEngine(EngineConfig(symbols=("AAA",), run_id=RUN), store=store)
    clock = [T0]
    mon = GoLiveMonitor(
        eng, store, lambda t, m: None, external_venue=False, clock=lambda: clock[0], sample_s=0.01
    )
    rt = TraderRuntime(eng, store, feed=None, clock=lambda: clock[0], tick_seconds=0.01, golive=mon)
    with TestClient(create_app(rt)) as client:
        client.post("/api/control", json={"kill_switch": True})
        client.post("/api/control", json={"kill_switch": True})  # no change, no event
        client.post("/api/control", json={"kill_switch": False})
        g = client.get("/api/golive").json()
        assert g["enabled"] and g["total"] == 10 and not g["ready"]
        crit = {c["key"]: c for c in g["criteria"]}
        assert crit["kill_switch"]["ok"] and not crit["venue"]["ok"]
        assert client.get("/api/state").json()["golive"]["total"] == 10
    kinds = [e["kind"] for e in store.ops_events(RUN)]
    assert kinds.count("kill_switch_on") == 1 and "session_start" in kinds

    plain = TraderRuntime(eng, store, feed=None, clock=lambda: T0)
    with TestClient(create_app(plain)) as client:
        assert client.get("/api/golive").json() == {"enabled": False}

    async def run_loop() -> None:
        task = asyncio.create_task(mon.loop())
        await asyncio.sleep(0.05)
        task.cancel()

    mon.engine = None  # type: ignore[assignment]  # a crash inside the loop is contained
    asyncio.run(run_loop())


def test_engine_logs_the_buy_and_hold_benchmark() -> None:
    store = SQLiteStore()
    eng = StreamingEngine(EngineConfig(symbols=("AAA",), run_id=RUN), store=store)
    for i in range(3):
        eng.on_event(Quote("AAA", T0 + 10 * i, 100.0 + i, 5.0, 100.1 + i, 5.0))
    rows = store.equity_curve(RUN)
    assert rows and rows[-1]["buy_hold"] == pytest.approx(eng.buy_hold_equity)


def test_notifier_ntfy_json_and_failures() -> None:
    seen: list[httpx.Request] = []

    def ok(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200)

    make_notifier({}, httpx.MockTransport(ok))("t", "m")
    assert not seen  # no webhook configured: log only
    make_notifier({"NOTIFY_WEBHOOK_URL": "https://ntfy.sh/my-topic"}, httpx.MockTransport(ok))(
        "Listo · real", "mensaje"
    )
    assert seen[0].content == b"mensaje" and seen[0].headers["Title"] == "Listo  real"
    hook = {"NOTIFY_WEBHOOK_URL": "https://hooks.slack.com/services/x"}
    make_notifier(hook, httpx.MockTransport(ok))("T", "M")
    assert json.loads(seen[1].content) == {"text": "T\nM", "content": "T\nM"}

    def fail(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    make_notifier(hook, httpx.MockTransport(fail))("T", "M")  # never raises


def test_gate_config_is_strict_by_default() -> None:
    cfg = GateConfig()
    assert (cfg.min_days, cfg.min_trades, cfg.max_p_value) == (28.0, 50, 0.05)
    assert (cfg.weeks, cfg.min_positive_weeks) == (4, 3)
