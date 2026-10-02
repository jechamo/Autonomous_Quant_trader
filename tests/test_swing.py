from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from aqt.features.cross_section import (
    XS_COLUMNS,
    augment,
    calendar_features,
    cross_sectional_features,
)
from aqt.features.engine import FeatureEngine
from aqt.lab.cycle import KlineData, LabConfig, run_research_cycle
from aqt.lab.registry import RuleRegistry
from aqt.strategies import resolve_strategy
from aqt.strategies.dsl import Condition, ExitRules, Rule, StrategySpec
from aqt.strategies.swing import SWING_CATALOG
from aqt.stream.bars import BarAggregator
from aqt.stream.dsl_strategy import DslStreamStrategy, ResearchBarBook, rule_id_for
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Quote
from aqt.stream.features import FeatureSnapshot
from aqt.stream.history import _kline_rows_to_bars, klines_frame, merge_events, resample_bars
from aqt.stream.session import NY, UsEquitySession
from aqt.stream.stocks import bar_events
from aqt.stream.store import SQLiteStore

from tests.test_stream import SMALL, Always, seed_evidence

H = 3600
T0 = 1_700_006_400  # epoch seconds on an hour boundary


def hourly(n: int, seed: int, drift: float = 0.0, start: int = T0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.004, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    vol = rng.exponential(100, n) + 1
    tb = vol * rng.uniform(0.3, 0.7, n)
    idx = pd.to_datetime(start + H * np.arange(n), unit="s", utc=True)
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.001,
         "low": np.minimum(open_, close) * 0.999, "close": close, "volume": vol,
         "taker_buy_volume": tb},
        index=idx,
    )  # fmt: skip


def test_cross_sectional_ranks_are_lagged_and_causal() -> None:
    idx = pd.date_range("2026-01-01", periods=80, freq="h", tz="UTC")
    a = pd.Series(np.linspace(100, 160, 80), index=idx)  # strongest
    b = pd.Series(np.linspace(100, 110, 80), index=idx)
    c = pd.Series(np.linspace(100, 70, 80), index=idx)  # weakest
    xs = cross_sectional_features({"A": a, "B": b, "C": c})
    assert list(xs["A"].columns) == list(XS_COLUMNS)
    row = 25
    assert xs["A"]["xs_rank_ret_5"].iloc[row] == 1.0 and xs["C"]["xs_rank_ret_5"].iloc[
        row
    ] == pytest.approx(1 / 3)
    assert xs["A"]["xs_n"].iloc[row] == 3
    # Lagged one panel bar: the value at t is the rank computed at t-1.
    unlagged_a_ret5 = a / a.shift(5) - 1
    assert np.isnan(xs["A"]["xs_rank_ret_5"].iloc[5]) and not np.isnan(unlagged_a_ret5.iloc[5])
    # Causal: truncating the future does not change the past.
    cut = cross_sectional_features({"A": a[:20], "B": b[:20], "C": c[:20]})
    pd.testing.assert_frame_equal(cut["A"], xs["A"].iloc[:20])
    assert xs["A"]["xs_rel_ret_20"].iloc[row] > 0 > xs["C"]["xs_rel_ret_20"].iloc[row]
    assert 0 <= xs["B"]["xs_breadth"].dropna().min() <= xs["B"]["xs_breadth"].dropna().max() <= 1


def test_calendar_features_and_passthrough() -> None:
    idx = pd.DatetimeIndex(
        [datetime(2026, 9, 29, 15, 0, tzinfo=NY), datetime(2026, 9, 29, 10, 0, tzinfo=NY)]
    )
    cal = calendar_features(idx.tz_convert("UTC"), H, "us_equity")
    assert list(cal["minutes_to_close"]) == [0.0, 300.0]  # bar ends at 16:00 / 11:00
    assert list(cal["day_of_week"]) == [1.0, 1.0]  # Tuesday in New York
    crypto = calendar_features(idx.tz_convert("UTC"), H, "24/7")
    assert "minutes_to_close" not in crypto
    bars = {"A": hourly(80, 1), "B": hourly(80, 2)}
    feats = FeatureEngine().compute(augment(bars, H)["A"])
    for col in (*XS_COLUMNS, "hour_utc", "day_of_week", "atr", "ema_50"):
        assert col in feats.columns


def test_month_calendar_uses_each_bars_own_trading_day() -> None:
    # A daily stock bar is labelled 00:00 UTC, which in New York is still the previous evening.
    idx = pd.DatetimeIndex(["2026-09-30", "2026-10-01"], tz="UTC")
    cal = calendar_features(idx, 86_400, "us_equity")
    assert list(cal["day_of_month"]) == [30.0, 1.0]
    assert list(cal["days_to_month_end"]) == [0.0, 30.0]
    assert list(cal["day_of_week"]) == [2.0, 3.0]  # Wednesday, Thursday
    crypto = calendar_features(pd.DatetimeIndex(["2026-02-27 23:00"], tz="UTC"), H, "24/7")
    assert crypto["day_of_month"].iloc[0] == 27 and crypto["days_to_month_end"].iloc[0] == 1


def test_catalog_for_keeps_daily_and_equity_effects_where_documented() -> None:
    stocks = LabConfig(symbols=("A",), timeframes=("15min", "1h", "1d"), session="us_equity")
    hourly_families = stocks.catalog_for("1h")[1]
    assert "near_52w_high" not in hourly_families and "turn_of_month" not in hourly_families
    assert {"streak_reversion", "rsi2_reversion", "ibs_reversion"} <= set(hourly_families)
    assert {"near_52w_high", "turn_of_month"} <= set(stocks.catalog_for("1d")[1])
    crypto = LabConfig(symbols=("A",), session="24/7")
    daily_crypto = crypto.catalog_for("1d")[1]
    assert "turn_of_month" not in daily_crypto and "near_52w_high" in daily_crypto
    assert stocks.catalog_for("15min")[0] == "intraday"
    assert stocks.days_for("1d") == stocks.daily_days and stocks.days_for("1h") == stocks.days


def test_documented_rules_fire_on_their_textbook_setups() -> None:
    """A long daily uptrend, a new high, then three lower closes."""
    n = 260
    close = np.concatenate([np.linspace(100, 160, n - 3), [158.0, 156.0, 154.0]])
    open_ = np.concatenate([[100.0], close[:-1]])
    df = pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.001,
         "low": np.minimum(open_, close) * 0.999, "close": close, "volume": 1000.0},
        index=pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC"),
    )  # fmt: skip
    feats = FeatureEngine().compute(augment({"A": df}, 86_400, "us_equity")["A"])
    streak = SWING_CATALOG["streak_reversion"][0].entry_signal(feats)
    assert streak.iloc[-1] and not streak.iloc[-2]  # three lower closes, not two
    assert SWING_CATALOG["rsi2_reversion"][0].entry_signal(feats).iloc[-1]
    assert SWING_CATALOG["near_52w_high"][0].entry_signal(feats).iloc[-4]  # at the high
    month_end = SWING_CATALOG["turn_of_month"][0].entry_signal(feats)
    assert month_end.sum() >= 8 and (feats["days_to_month_end"][month_end] <= 2).all()


def test_swing_catalog_renders_on_augmented_features() -> None:
    bars = {s: hourly(300, i) for i, s in enumerate("ABCD")}
    feats = FeatureEngine().compute(augment(bars, H)["A"])
    for name, (spec, grid) in SWING_CATALOG.items():
        assert grid and resolve_strategy(name, "swing")[0] is spec
        sig = spec.entry_signal(feats)
        assert sig.dtype == bool and len(sig) == len(feats)
    with pytest.raises(KeyError):
        resolve_strategy("nope", "swing")


XS_RULE = StrategySpec(
    name="xs_parity",
    family="test",
    entry=Rule(all_of=[Condition(left="xs_rank_ret_5", op=">", right=0.6)]),
    exit=ExitRules(stop_atr_mult=2.0, max_holding_bars=5),
)


def _snap(sym: str, ts: float) -> FeatureSnapshot:
    return FeatureSnapshot(
        sym, ts, 100.0, 1, 1, 0.001, 0, 0, 100, 0, 0, 100, False, 0.0001, 1, 99, True
    )


def test_live_cross_sectional_rule_matches_research() -> None:
    """Three symbols, hourly bars: the live book's lagged ranks match research entries."""
    raw = {s: hourly(120, i) for i, s in enumerate(("AAA", "BBB", "CCC"))}
    research = {s: FeatureEngine().compute(f) for s, f in augment(raw, H).items()}
    feats = research["AAA"]
    # Like run_backtest and the live engine: no trade until the ATR stop can be measured.
    tradable = XS_RULE.entry_signal(feats) & feats["atr"].notna()
    expected = {int(t.timestamp()) for t in feats.index[tradable.to_numpy()]}
    assert expected
    book = ResearchBarBook()
    strat = DslStreamStrategy(spec=XS_RULE, symbol="AAA", timeframe_s=H, book=book)
    aggs = {s: BarAggregator(s, 5.0) for s in raw}
    fired: set[int] = set()
    events = merge_events([bar_events(raw[s], s, 0.0001, H) for s in raw])
    for e in events:
        bars = aggs[e.symbol].on_quote(e) if isinstance(e, Quote) else aggs[e.symbol].on_trade(e)
        for bar in bars:
            strat.on_bar(bar)
            if bar.symbol == "AAA":
                seq_before = strat._entry_seq
                intent = strat.entry(_snap("AAA", bar.end))
                if intent is not None:
                    fired.add(int(book.series("AAA", H).bars[-1][0]))
                assert strat._entry_seq >= seq_before
    last = int(research["AAA"].index[-1].timestamp())
    assert fired == expected - {last}
    assert strat.overnight and rule_id_for(XS_RULE, "AAA", H).endswith("@1h")


def test_swing_positions_survive_the_close_intraday_ones_do_not() -> None:
    def run(overnight: bool) -> StreamingEngine:
        strat = Always()
        strat.overnight = overnight
        cfg = EngineConfig(
            symbols=("AAPL",), bar_seconds=1.0, session="us_equity", latency_s=0.0,
            entry_cooldown_seconds=1e9, min_order_notional=1.0, feature_params=SMALL,
        )  # fmt: skip
        eng = StreamingEngine(cfg, strategies=[strat])
        eng.set_adv("AAPL", 1e7)
        seed_evidence(eng)
        t = datetime(2026, 9, 29, 15, 40, tzinfo=NY).timestamp()
        for i in range(16 * 60):  # 15:40 -> 15:56
            mid = 100 * (1 + (0.0002 if i % 2 else 0))
            eng.on_event(Quote("AAPL", t + i + 0.5, mid - 0.01, 50, mid + 0.01, 50))
        return eng

    swing = run(True)
    assert "AAPL" in swing._positions and swing.paper_trades() == []
    intraday = run(False)
    assert intraday.paper_trades()[0].exit_reason == "session_end"


def test_bar_events_are_squeezed_into_the_session() -> None:
    idx = pd.DatetimeIndex(
        [datetime(2026, 9, 29, 9, 0, tzinfo=NY), datetime(2026, 9, 29, 20, 0, tzinfo=NY)]
    )
    bars = pd.DataFrame(
        {"open": [10.0, 11], "high": [11.0, 12], "low": [9.0, 10], "close": [10.5, 11.5],
         "volume": [100.0, 100]},
        index=idx.tz_convert("UTC"),
    )  # fmt: skip
    ev = list(bar_events(bars, "X", seconds=H, session=UsEquitySession()))
    open_ts = datetime(2026, 9, 29, 9, 30, tzinfo=NY).timestamp()
    assert ev and all(
        open_ts <= e.ts < open_ts + 1800 for e in ev
    )  # 09:30-10:00, after-hours bar dropped
    plain = list(bar_events(bars, "X", seconds=H))
    assert plain[0].ts == idx[0].timestamp()


def test_resample_and_kline_rows() -> None:
    minute = pd.DataFrame(
        {"open": [1.0, 2, 3, 4], "high": [2.0, 3, 4, 5], "low": [0.5, 1, 2, 3],
         "close": [2.0, 3, 4, 5], "volume": [1.0, 1, 1, 1],
         "taker_buy_volume": [0.5, 0.5, 0.5, 0.5]},
        index=pd.to_datetime([T0, T0 + 60, T0 + H, T0 + H + 60], unit="s", utc=True),
    )  # fmt: skip
    hourly_bars = resample_bars(minute, "1h")
    assert list(hourly_bars["open"]) == [1.0, 3.0] and list(hourly_bars["volume"]) == [2.0, 2.0]
    assert hourly_bars.index[0].timestamp() == T0
    rows = [[T0 * 1000, "1", "2", "0.5", "1.5", "10", 0, "0", 1, "4", "0", "0"]]
    bars = _kline_rows_to_bars(rows)
    assert bars.index[0].timestamp() == T0 and bars["taker_buy_volume"].iloc[0] == 4.0
    assert klines_frame(rows)["open_time"].iloc[0] == T0 * 1000


def test_multi_timeframe_cycle_finds_a_cross_sectional_leader() -> None:
    """One symbol drifts up steadily (a persistent leader); five are noise. Hourly research with
    the swing catalog must promote a rule on the leader only, and nothing on the noise."""
    n = 24 * 120
    data = {"LEADUSDC": hourly(n, 1, drift=0.0006)}
    for i in range(5):
        data[f"N{i}USDC"] = hourly(n, 10 + i)

    def interval_loader(symbol: str, start_ms: int, end_ms: int, timeframe: str) -> pd.DataFrame:
        assert timeframe == "1h"
        df = data[symbol]
        lo, hi = (
            pd.Timestamp(start_ms, unit="ms", tz="UTC"),
            pd.Timestamp(end_ms, unit="ms", tz="UTC"),
        )
        return df[(df.index >= lo) & (df.index < hi)]

    def no_seconds(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        raise AssertionError("1-second klines must not be requested for hourly research")

    cfg = LabConfig(
        symbols=tuple(data), days=130, timeframes=("1h",), swing_families=("xs_momentum",),
        min_trades=10, walk_forward_windows=3, monte_carlo_sims=200, workers=1,
    )  # fmt: skip
    store = SQLiteStore()
    end_ms = (T0 + n * H) * 1000
    lab_data = KlineData(no_seconds, interval_loader=interval_loader)
    res = run_research_cycle(store, cfg, lab_data, end_ms=end_ms, clock=lambda: 1e9)
    assert res.error == "", res.error
    assert res.summary["timeframes"] == ["1h"] and res.summary["hypotheses_by_timeframe"]["1h"] > 0
    active = RuleRegistry(store).active()
    assert active, res.summary["top_pairs"][:3]
    assert {r.symbol for r in active} == {"LEADUSDC"}
    rule = active[0]
    assert rule.timeframe_s == H and rule.meta["overnight"] and rule.rule_id.endswith("@1h")
