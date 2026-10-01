from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from aqt.features.engine import FeatureEngine
from aqt.strategies.dsl import Condition, ExitRules, Rule, StrategySpec
from aqt.strategies.intraday import INTRADAY_CATALOG
from aqt.stream.bars import BarAggregator
from aqt.stream.dsl_strategy import DslStreamStrategy, ResearchBarBook
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Quote
from aqt.stream.features import FeatureSnapshot
from aqt.stream.history import kline_events, klines_frame, resample_klines

SYM = "BTCUSDC"
T0 = 1_700_000_040_000  # ms, on a minute boundary


def klines(seconds: int, seed: int = 3, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows, p = [], 100.0
    for i in range(seconds):
        o = p
        p *= math.exp(drift + rng.normal(0, 0.0004))
        v = float(rng.exponential(1.0)) + 0.01
        tb = v * float(np.clip(0.5 + (p / o - 1) * 800 + rng.normal(0, 0.15), 0, 1))
        rows.append(
            [T0 + i * 1000, o, max(o, p) * 1.0001, min(o, p) * 0.9999, p, v, 0, 0, 1, tb, 0, 0]
        )
    return klines_frame(rows)


RULE = StrategySpec(
    name="parity",
    family="test",
    entry=Rule(all_of=[Condition(left="flow_imbalance_5", op=">", right=0.1),
                       Condition(left="close", op=">", right="ema_20")]),
    exit=ExitRules(stop_atr_mult=2.0, target_atr_mult=4.0, max_holding_bars=10,
                   exit_signal=Rule(all_of=[Condition(left="rsi", op=">", right=70)])),
)  # fmt: skip


def _snap(ts: float) -> FeatureSnapshot:
    return FeatureSnapshot(
        SYM, ts, 100.0, 1, 1, 0.001, 0, 0, 100, 0, 0, 100, False, 0.0001, 1, 99, True
    )


def test_resample_keeps_flow_and_ohlc() -> None:
    df = klines(180)
    bars = resample_klines(df, "1min")
    assert len(bars) == 3 and list(bars.columns) == [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "taker_buy_volume",
    ]
    first = df.iloc[:60]
    assert bars.iloc[0]["open"] == first["open"].iloc[0]
    assert bars.iloc[0]["high"] == first["high"].max() and bars.iloc[0]["low"] == first["low"].min()
    assert bars.iloc[0]["volume"] == pytest.approx(first["volume"].sum())
    assert bars.iloc[0]["taker_buy_volume"] == pytest.approx(first["taker_buy_volume"].sum())
    assert resample_klines(klines_frame([])).empty


def test_flow_features_are_causal() -> None:
    bars = resample_klines(klines(3600), "1min")
    full = FeatureEngine().compute(bars)
    cut = FeatureEngine().compute(bars.iloc[:40])
    for col in ("flow_imbalance_5", "flow_imbalance_15"):
        pd.testing.assert_series_equal(full[col].iloc[:40], cut[col], check_names=False)
        assert full[col].dropna().between(-1, 1).all()


def test_live_rule_matches_backtester_signals() -> None:
    """Same ticks → same research bars → same features → same entries as run_backtest sees."""
    df = klines(3 * 3600)
    research = FeatureEngine().compute(resample_klines(df, "1min"))
    expected = {int(t.timestamp()) for t in research.index[RULE.entry_signal(research).to_numpy()]}
    assert expected  # the rule must fire for the test to mean anything

    strat = DslStreamStrategy(spec=RULE, symbol=SYM, timeframe_s=60, engine_bar_s=5)
    agg = BarAggregator(SYM, 5.0)
    fired: set[int] = set()
    for e in kline_events(df, SYM):
        bars = agg.on_quote(e) if isinstance(e, Quote) else agg.on_trade(e)
        for bar in bars:
            strat.on_bar(bar)
            intent = strat.entry(_snap(bar.end))
            if intent is not None:
                fired.add(int(bar.end) - 60)  # decided on the close of the bar starting here
                assert intent.stop_pct > 0 and intent.max_hold_bars == 10 * 12
    # The last research bar is never closed in the live stream (no later event): drop it.
    last = int(research.index[-1].timestamp())
    assert fired == expected - {last}


def test_dsl_strategy_runs_inside_the_engine() -> None:
    df = klines(3 * 3600, drift=0.00002)
    book = ResearchBarBook()
    book.preload(SYM, 60.0, FeatureEngine().compute(resample_klines(df, "1min")))
    strat = DslStreamStrategy(spec=RULE, symbol=SYM, book=book)
    eng = StreamingEngine(EngineConfig(symbols=(SYM,), bar_seconds=5.0), strategies=[strat])
    for e in kline_events(df, SYM):
        eng.on_event(e)
    assert strat.strategy_id.startswith("test:BTCUSDC:")
    row = eng.snapshot()["strategies"][0]
    assert row["signals"] > 0 and row["cost_blocked"] == 0  # validated rules skip the generic gate
    assert eng.evidence.table()[strat.strategy_id].n_trades > 0


def test_seeded_book_needs_no_warmup() -> None:
    bars = resample_klines(klines(3600), "1min")
    book = ResearchBarBook()
    book.seed(SYM, 60.0, bars)
    s = book.series(SYM, 60.0)
    assert len(s.bars) == 60 and s.features is not None and "flow_imbalance_15" in s.features


def test_every_intraday_rule_renders_on_research_features() -> None:
    feats = FeatureEngine().compute(resample_klines(klines(5 * 3600), "1min"))
    for name, (spec, grid) in INTRADAY_CATALOG.items():
        assert grid, name
        sig = spec.entry_signal(feats)
        assert sig.dtype == bool and len(sig) == len(feats)
