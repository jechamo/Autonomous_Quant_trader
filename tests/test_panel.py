from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from aqt.backtest import CostModel
from aqt.features.engine import FeatureEngine
from aqt.lab.cycle import KlineData, LabConfig, run_research_cycle
from aqt.lab.live import rule_strategies
from aqt.lab.registry import RuleRecord, RuleRegistry
from aqt.research.panel import common_frontier, run_panel_research
from aqt.research.pipeline import ResearchConfig
from aqt.research.study import StudyConfig, run_panel_study, run_study
from aqt.strategies.dsl import Condition, ExitRules, Rule, StrategySpec
from aqt.stream.bars import BarAggregator
from aqt.stream.dsl_strategy import PanelDslStrategy, ResearchBarBook, rule_id_for
from aqt.stream.events import Quote
from aqt.stream.history import merge_events
from aqt.stream.stocks import bar_events
from aqt.stream.store import SQLiteStore

from tests.test_swing import XS_RULE, H, _snap, hourly

DAY = 86_400
STREAK = StrategySpec(
    name="streak4",
    family="test_streak",
    entry=Rule(all_of=[Condition(left="down_streak", op=">=", right="$n")]),
    exit=ExitRules(stop_atr_mult=3.0, max_holding_bars=2),
    params={"n": 4},
)
SPECS = {"streak4": (STREAK, {"n": [4]})}
COSTS = CostModel(fee_pct=0.0005, spread_pct=0.0002, slippage_pct=0.0002, fx_pct=0.0)


def daily(n: int, seed: int, edge: float, k: int = 4) -> pd.DataFrame:
    """Daily bars; with ``edge`` the two days after ``k`` lower closes in a row drift up."""
    rng = np.random.default_rng(seed)
    ret = np.empty(n)
    down = boost = 0
    for i in range(n):
        r = rng.normal(0.0003, 0.01)
        if boost:
            r += edge
            boost -= 1
        ret[i] = r
        down = down + 1 if r < 0 else 0
        if down >= k and edge:
            boost = 2
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[100.0], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.002,
         "low": np.minimum(open_, close) * 0.998, "close": close,
         "volume": rng.exponential(1000, n) + 100},
        index=pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC"),
    )  # fmt: skip


def rcfg(**kw: Any) -> ResearchConfig:
    base: dict[str, Any] = dict(
        symbol="*", timeframe="1d", strategy="streak4", spec=STREAK, grid={"n": [4, 5]},
        walk_forward_windows=3, monte_carlo_sims=200, min_trades=30, costs=COSTS,
    )  # fmt: skip
    base.update(kw)
    return ResearchConfig(**base)


def test_one_frontier_for_all_symbols_and_dates_as_the_unit() -> None:
    feats = {s: FeatureEngine().compute(daily(900, i, 0.008)) for i, s in enumerate("ABCD")}
    frontier = common_frontier(feats, 0.7)
    report = run_panel_research(feats, rcfg()).to_dict()
    assert report["out_of_sample"]["period"][0] == str(frontier)
    # Changing what happens after the frontier never changes the in-sample selection.
    shocked = dict(feats)
    b = feats["B"].copy()
    b.loc[b.index >= frontier, ["open", "high", "low", "close"]] *= 3.0
    shocked["B"] = b
    again = run_panel_research(shocked, rcfg()).to_dict()
    assert again["multiple_testing"]["p_values"] == report["multiple_testing"]["p_values"]
    assert again["selected_strategy"] == report["selected_strategy"]
    # Ten identical copies of a symbol are as much evidence as one: dates, not trades.
    one = run_panel_research({"A": feats["A"]}, rcfg()).to_dict()
    copies = run_panel_research({f"A{i}": feats["A"] for i in range(10)}, rcfg()).to_dict()
    assert copies["multiple_testing"]["p_values"] == one["multiple_testing"]["p_values"]
    assert copies["out_of_sample"]["n_trades"] == one["out_of_sample"]["n_trades"]
    assert copies["out_of_sample"]["n_trades_total"] == 10 * one["out_of_sample"]["n_trades_total"]


def test_pooling_finds_a_weak_effect_that_no_single_symbol_can_prove() -> None:
    planted = {f"S{i}": daily(1100, i, 0.008) for i in range(10)}
    cfg = StudyConfig(timeframe="1d", walk_forward_windows=3, monte_carlo_sims=200)
    per_symbol = run_study(planted, ["streak4"], cfg, lambda _s: COSTS, lambda _s: (True, "USD"),
                           specs=SPECS)  # fmt: skip
    assert not per_symbol.candidates
    assert all(
        "sufficient_oos_sample" in p.report["verdict"]["failed"]
        for p in per_symbol.pairs
        if p.report
    )
    pooled = run_panel_study(planted, ["streak4"], cfg, lambda _s: COSTS, specs=SPECS)
    (pair,) = pooled.pairs
    assert pair.symbol == "*" and pair.decision == "CHALLENGER_CANDIDATE", pair.summary()
    assert pair.report is not None and pair.report["out_of_sample"]["n_trades"] >= 30
    noise = {f"S{i}": daily(1100, 50 + i, 0.0) for i in range(10)}
    (quiet,) = run_panel_study(noise, ["streak4"], cfg, lambda _s: COSTS, specs=SPECS).pairs
    assert quiet.decision == "REJECTED"
    (alone,) = run_panel_study({"S0": planted["S0"]}, ["streak4"], cfg, specs=SPECS).pairs
    assert alone.decision == "ERROR" and "needs >= 2 symbols" in (alone.error or "")


def test_lab_promotes_one_pooled_rule_that_trades_every_symbol() -> None:
    n = 1250
    data = {f"S{i}USDC": daily(n, i, 0.01) for i in range(8)}

    def interval_loader(symbol: str, start_ms: int, end_ms: int, timeframe: str) -> pd.DataFrame:
        assert timeframe == "1d"
        return data[symbol]

    cfg = LabConfig(
        symbols=tuple(data), timeframes=("1d",), swing_families=("streak_reversion",),
        min_trades=30, walk_forward_windows=3, monte_carlo_sims=200, workers=1,
        include_ai_hypotheses=False, fee_pct=0.0005, slippage_pct=0.0002,
    )  # fmt: skip
    end_ms = int((data["S0USDC"].index[-1].timestamp() + DAY) * 1000)
    store = SQLiteStore()
    lab = KlineData(lambda *a: pd.DataFrame(), interval_loader=interval_loader)
    res = run_research_cycle(store, cfg, lab, end_ms=end_ms, clock=lambda: 1e9)
    assert res.error == "", res.error
    (rule,) = RuleRegistry(store).active()
    assert rule.symbol == "*" and rule.rule_id.endswith("@1d") and ":*:" in rule.rule_id
    golden = next(g for g in res.summary["golden"] if g["rule_id"] == rule.rule_id)
    assert golden["passed"] and golden["symbols"] == len(data)
    (live,) = rule_strategies([rule], tuple(data), ResearchBarBook(), 5.0)
    assert isinstance(live, PanelDslStrategy) and set(live.legs) == set(data)
    assert live.strategy_id == rule.rule_id and live.overnight


def test_pooled_rule_live_matches_research_on_every_symbol() -> None:
    raw = {s: hourly(120, i) for i, s in enumerate(("AAA", "BBB", "CCC"))}
    from aqt.features.cross_section import augment

    research = {s: FeatureEngine().compute(f) for s, f in augment(raw, H).items()}
    expected = {
        (s, int(t.timestamp()))
        for s, feats in research.items()
        for t in feats.index[(XS_RULE.entry_signal(feats) & feats["atr"].notna()).to_numpy()]
    }
    assert {s for s, _ in expected} == set(raw)
    book = ResearchBarBook()
    strat = PanelDslStrategy(spec=XS_RULE, symbols=tuple(raw), timeframe_s=H, book=book)
    assert strat.strategy_id == rule_id_for(XS_RULE, "*", H)
    aggs = {s: BarAggregator(s, 5.0) for s in raw}
    fired: set[tuple[str, int]] = set()
    for e in merge_events([bar_events(raw[s], s, 0.0001, H) for s in raw]):
        bars = aggs[e.symbol].on_quote(e) if isinstance(e, Quote) else aggs[e.symbol].on_trade(e)
        for bar in bars:
            strat.on_bar(bar)
            intent = strat.entry(_snap(bar.symbol, bar.end))
            if intent is not None:
                assert intent.strategy_id == strat.strategy_id
                fired.add((bar.symbol, int(book.series(bar.symbol, H).bars[-1][0])))
    last = {(s, int(f.index[-1].timestamp())) for s, f in research.items()}
    assert fired == expected - last
    assert strat.entry(_snap("ZZZ", 0.0)) is None and strat.should_exit(_snap("ZZZ", 0.0)) is False
    reg = RuleRegistry(SQLiteStore())
    rec = RuleRecord(rule_id_for(XS_RULE, "*", H), "*", H, XS_RULE)
    reg.upsert(rec)
    assert reg.get(rec.rule_id) is not None
