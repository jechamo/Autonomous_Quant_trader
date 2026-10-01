import numpy as np
import pandas as pd
import pytest
from aqt.backtest import CostModel, run_backtest
from aqt.strategies import Condition, ExitRules, Rule, StrategySpec
from conftest import make_bars


def _spec(**exit_kw: object) -> StrategySpec:
    return StrategySpec(
        name="test",
        family="test",
        entry=Rule(all_of=[Condition(left="go", op="==", right=1)]),
        exit=ExitRules(**exit_kw),  # type: ignore[arg-type]
    )


def _with_signal(df: pd.DataFrame, at: list[int]) -> pd.DataFrame:
    df = df.copy()
    df["go"] = 0.0
    df.iloc[at, df.columns.get_loc("go")] = 1.0
    return df


FLAT = (100.0, 100.5, 99.5, 100.0)


def test_entry_next_open_and_stop_same_bar() -> None:
    df = _with_signal(make_bars([FLAT, (100, 100.5, 97, 98.5), FLAT, FLAT]), [0])
    res = run_backtest(df, _spec(stop_atr_mult=2.0), CostModel.zero())
    (t,) = res.trades
    assert t.entry_time == df.index[1]
    assert t.entry_price == 100
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(98.0)
    assert t.net_return == pytest.approx(-0.02)


def test_gap_through_stop_fills_at_open() -> None:
    df = _with_signal(make_bars([FLAT, FLAT, (95, 95.5, 94, 95), FLAT]), [0])
    (t,) = run_backtest(df, _spec(stop_atr_mult=2.0), CostModel.zero()).trades
    assert t.exit_price == 95 and t.exit_reason == "stop"


def test_target() -> None:
    df = _with_signal(make_bars([FLAT, FLAT, (100.5, 104, 100.2, 103.5), FLAT]), [0])
    (t,) = run_backtest(df, _spec(stop_atr_mult=2.0, target_atr_mult=3.0), CostModel.zero()).trades
    assert t.exit_reason == "target" and t.exit_price == pytest.approx(103.0)


def test_stop_wins_when_both_touched() -> None:
    df = _with_signal(make_bars([FLAT, FLAT, (100, 104, 97, 101), FLAT]), [0])
    (t,) = run_backtest(df, _spec(stop_atr_mult=2.0, target_atr_mult=3.0), CostModel.zero()).trades
    assert t.exit_reason == "stop"


def test_max_holding_and_exit_signal() -> None:
    df = _with_signal(make_bars([FLAT] * 6), [0])
    (t,) = run_backtest(df, _spec(stop_atr_mult=5.0, max_holding_bars=2), CostModel.zero()).trades
    assert t.exit_reason == "max_holding" and t.exit_time == df.index[3]

    df["out"] = [0, 0, 1, 0, 0, 0]
    spec = _spec(
        stop_atr_mult=5.0,
        max_holding_bars=None,
        exit_signal=Rule(all_of=[Condition(left="out", op="==", right=1)]),
    )
    (t,) = run_backtest(df, spec, CostModel.zero()).trades
    assert t.exit_reason == "signal" and t.exit_time == df.index[3]


def test_signal_on_last_bar_does_not_trade_and_end_of_data_closes() -> None:
    df = _with_signal(make_bars([FLAT] * 4), [3])
    assert run_backtest(df, _spec(), CostModel.zero()).trades == []
    df = _with_signal(make_bars([FLAT] * 4), [1])
    (t,) = run_backtest(df, _spec(max_holding_bars=None), CostModel.zero()).trades
    assert t.exit_reason == "end_of_data"


def test_costs_reduce_returns_and_equity_matches_trades(features: pd.DataFrame) -> None:
    from aqt.strategies import get_strategy

    spec, _ = get_strategy("breakout")
    gross = run_backtest(features, spec, CostModel.zero())
    net = run_backtest(features, spec, CostModel())
    assert len(gross.trades) == len(net.trades) > 0
    assert (net.trade_returns < gross.trade_returns).all()
    assert np.allclose(gross.trade_returns, gross.gross_trade_returns)
    # With a single position at full exposure, compounded bar returns == compounded trades.
    for res in (gross, net):
        assert res.equity.iloc[-1] == pytest.approx(np.prod(1 + res.trade_returns), rel=1e-9)
    assert set(net.exposure.unique()) <= {0.0, 1.0}
    assert not net.trades_frame().empty


def test_cost_model_validation() -> None:
    with pytest.raises(ValueError):
        CostModel(spread_pct=-1)
    c = CostModel(fee_fixed=1.0, fee_pct=0, fx_pct=0, spread_pct=0, slippage_pct=0)
    assert c.round_trip_pct(100) == pytest.approx(0.02)
