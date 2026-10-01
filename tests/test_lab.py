from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from aqt.features.engine import FeatureEngine
from aqt.lab.cycle import LabConfig, run_research_cycle
from aqt.lab.registry import RuleRecord, RuleRegistry, RuleStatus
from aqt.lab.review import ReviewConfig, review_rules
from aqt.risk.profile import RiskProfile
from aqt.strategies.intraday import INTRADAY_CATALOG
from aqt.stream.dsl_strategy import DslStreamStrategy, ResearchBarBook, rule_id_for
from aqt.stream.engine import EngineConfig, StreamingEngine, _VirtualTrade
from aqt.stream.history import kline_events, klines_frame, resample_klines
from aqt.stream.records import RoundTrip
from aqt.stream.store import SQLiteStore
from aqt.stream.strategies import EntryIntent

T0 = 1_700_000_040_000  # ms, minute aligned
DAY_MS = 86_400_000


def synthetic_klines(days: float, seed: int, planted: bool, start_ms: int = T0) -> pd.DataFrame:
    """1-second klines; with ``planted`` every hour has a 30-minute buying burst (+1.2 %)."""
    n = int(days * 86_400)
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0, 0.0002, n)
    flow = 0.5 + rng.normal(0.0, 0.1, n)
    if planted:
        for k in range(1800, n - 1800, 3600):
            ret[k : k + 1800] += 0.012 / 1800
            flow[k : k + 1800] += 0.3
    close = 100.0 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[100.0], close[:-1]])
    vol = rng.exponential(1.0, n) + 0.1
    tb = vol * np.clip(flow, 0.0, 1.0)
    t = start_ms + np.arange(n) * 1000
    rows = np.column_stack(
        [t, open_, np.maximum(open_, close) * 1.0001, np.minimum(open_, close) * 0.9999, close,
         vol, np.zeros(n), np.zeros(n), np.ones(n), tb, np.zeros(n), np.zeros(n)]
    )  # fmt: skip
    return klines_frame(rows.tolist())


def make_loader(data: dict[str, pd.DataFrame]):  # type: ignore[no-untyped-def]
    def load(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        df = data.get(symbol, klines_frame([]))
        return df[(df.open_time >= start_ms) & (df.open_time < end_ms)]

    return load


LAB = LabConfig(
    symbols=("PLANTUSDC", "NOISEUSDC"),
    days=3.0,
    min_trades=10,
    walk_forward_windows=3,
    monte_carlo_sims=300,
    families=("flow_momentum", "flow_breakout"),
    workers=1,
)


@pytest.fixture(scope="module")
def cycle_store() -> tuple[SQLiteStore, object]:
    data = {
        "PLANTUSDC": synthetic_klines(3.0, seed=1, planted=True),
        "NOISEUSDC": synthetic_klines(3.0, seed=2, planted=False),
    }
    store = SQLiteStore()
    result = run_research_cycle(
        store, LAB, make_loader(data), end_ms=T0 + 3 * DAY_MS, clock=lambda: 1e9
    )
    return store, result


def test_cycle_discovers_planted_edge_and_ignores_noise(cycle_store) -> None:  # type: ignore[no-untyped-def]
    store, result = cycle_store
    assert result.error == "", result.error
    reg = RuleRegistry(store)
    active = reg.active()
    assert active, result.summary
    assert all(r.symbol == "PLANTUSDC" for r in active)  # nothing promoted on a random walk
    assert set(result.promoted) == {r.rule_id for r in active}
    rule = active[0]
    assert rule.status == RuleStatus.CHALLENGER
    assert rule.metrics["golden"]["passed"] and rule.metrics["research"]["oos_ev"] > 0
    assert rule.rule_id == rule_id_for(rule.spec, "PLANTUSDC")
    s = result.summary
    assert s["n_hypotheses"] > 20 and s["n_candidates"] >= 1 and s["failed_checks"]
    runs = reg.runs()
    assert runs[0]["status"] == "done" and runs[0]["summary"]["promoted"] == result.promoted
    events = reg.events()
    assert any(e["to_status"] == "challenger" for e in events)
    assert any(lesson["kind"] == "research" for lesson in reg.lessons())


def test_promoted_rule_trades_in_the_live_engine(cycle_store) -> None:  # type: ignore[no-untyped-def]
    store, _ = cycle_store
    rule = RuleRegistry(store).active()[0]
    data = synthetic_klines(0.5, seed=9, planted=True, start_ms=T0 + 3 * DAY_MS)
    book = ResearchBarBook()
    book.preload(rule.symbol, 60.0, FeatureEngine().compute(resample_klines(data, "1min")))
    strat = DslStreamStrategy(spec=rule.spec, symbol=rule.symbol, book=book)
    eng = StreamingEngine(EngineConfig(symbols=(rule.symbol,)), strategies=[strat])
    for e in kline_events(data, rule.symbol):
        eng.on_event(e)
    r = eng.evidence.returns(rule.rule_id)
    assert len(r) >= 3 and float(np.mean(r)) > 0


def test_cycle_error_is_recorded() -> None:
    def broken(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        raise RuntimeError("offline")

    store = SQLiteStore()
    res = run_research_cycle(store, LAB, broken, end_ms=T0)
    assert "offline" in res.error
    assert RuleRegistry(store).runs()[0]["status"] == "error"


def _rule(reg: RuleRegistry, status: RuleStatus, name: str = "flow_momentum") -> RuleRecord:
    spec = INTRADAY_CATALOG[name][0].render()
    rec = RuleRecord(rule_id_for(spec, "XUSDC"), "XUSDC", 60.0, spec,
                     metrics={"research": {"oos_ev": 0.004}})  # fmt: skip
    reg.upsert(rec)
    reg.set_status(rec.rule_id, status, "test")
    return rec


def _trades(store: SQLiteStore, rule_id: str, returns: list[float]) -> None:
    for i, r in enumerate(returns):
        store.log_round_trip(
            "live-USDC",
            RoundTrip("shadow", rule_id, "XUSDC", i, i + 1, 100, 100 * (1 + r), 0, 0, 0, r, "t"),
        )


def test_review_retires_losers_and_promotes_winners() -> None:
    store = SQLiteStore()
    reg = RuleRegistry(store, clock=lambda: 1_000.0)
    profile = RiskProfile.from_aggressiveness(50)
    loser = _rule(reg, RuleStatus.CHALLENGER, "flow_momentum")
    winner = _rule(reg, RuleStatus.CHALLENGER, "flow_breakout")
    weak_champ = _rule(reg, RuleStatus.CHAMPION, "trend_pullback")
    stale = _rule(reg, RuleStatus.CHALLENGER, "vwap_reversion")
    _trades(store, loser.rule_id, [-0.004 if i % 5 else 0.002 for i in range(40)])
    _trades(store, winner.rule_id, [0.006 if i % 8 else -0.002 for i in range(60)])
    _trades(store, weak_champ.rule_id, [0.001, -0.001, 0.0005])
    changes = review_rules(
        store,
        "live-USDC",
        profile,
        cfg=ReviewConfig(stale_days=1),
        clock=lambda: 1_000 + 2 * 86_400,
    )
    status = {r.rule_id: r.status for r in RuleRegistry(store).rules()}
    assert status[loser.rule_id] == RuleStatus.RETIRED
    assert status[winner.rule_id] == RuleStatus.CHAMPION
    assert status[weak_champ.rule_id] == RuleStatus.CHALLENGER
    assert status[stale.rule_id] == RuleStatus.RETIRED
    assert len(changes) == 4
    kinds = {lesson["kind"] for lesson in RuleRegistry(store).lessons()}
    assert {"retirement", "promotion"} <= kinds
    retired = RuleRegistry(store).get(loser.rule_id)
    assert retired is not None and retired.metrics["forward"]["n_trades"] == 40


def test_registry_upsert_and_transitions() -> None:
    store = SQLiteStore()
    reg = RuleRegistry(store, clock=lambda: 5.0)
    rec = _rule(reg, RuleStatus.CHALLENGER)
    again = reg.upsert(RuleRecord(rec.rule_id, "XUSDC", 60.0, rec.spec, metrics={"x": 1}))
    assert again.status == RuleStatus.CHALLENGER and again.metrics == {"x": 1}
    reg.set_status(rec.rule_id, RuleStatus.CHALLENGER, "no-op")  # same status: no event
    assert [e["to_status"] for e in reg.events()] == ["challenger", "candidate"]
    with pytest.raises(KeyError):
        reg.set_status("missing", RuleStatus.RETIRED, "x")
    assert rec.to_dict()["status"] == "candidate"  # the record object itself is unchanged


def test_engine_hot_swaps_strategies_and_retires_gracefully() -> None:
    spec = INTRADAY_CATALOG["flow_momentum"][0].render()
    data = synthetic_klines(0.4, seed=3, planted=True)
    book = ResearchBarBook()
    book.preload("PLANTUSDC", 60.0, FeatureEngine().compute(resample_klines(data, "1min")))
    dsl = DslStreamStrategy(spec=spec, symbol="PLANTUSDC", book=book)
    eng = StreamingEngine(EngineConfig(symbols=("PLANTUSDC",)))
    base = list(eng.strategies)
    assert eng.set_strategies([*base, dsl])["added"] == [dsl.strategy_id]
    assert dsl.strategy_id in eng.evidence.strategy_ids
    events = list(kline_events(data, "PLANTUSDC"))
    half = len(events) // 2
    for e in events[:half]:
        eng.on_event(e)
    # Give the rule an open shadow trade, then let the lab remove it.
    intent = EntryIntent(dsl.strategy_id, "PLANTUSDC", eng.now, 0.5, 0.5, 10**6, "t")
    eng._shadow[(dsl.strategy_id, "PLANTUSDC")] = _VirtualTrade(intent, eng.now)
    assert eng.set_strategies(base)["removed"] == [dsl.strategy_id]
    assert dsl.strategy_id in eng._retiring  # open trade: managed, but no new entries
    assert dsl.strategy_id in [s.strategy_id for s in eng.strategies]
    del eng._shadow[(dsl.strategy_id, "PLANTUSDC")]
    for e in events[half:]:
        eng.on_event(e)
    assert dsl.strategy_id not in [s.strategy_id for s in eng.strategies]
    assert dsl.strategy_id not in eng.evidence.strategy_ids
    # Without open trades a removal is immediate.
    eng.set_strategies([*base, dsl])
    eng.set_strategies(base)
    assert dsl.strategy_id not in eng.evidence.strategy_ids and not eng._retiring
    with pytest.raises(ValueError):
        eng.set_strategies([dsl, dsl])
