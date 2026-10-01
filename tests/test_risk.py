from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from aqt.common.types import OrderSide
from aqt.risk import (
    ABSOLUTE_LIMITS,
    MarketState,
    Portfolio,
    Position,
    RiskAction,
    RiskEngine,
    RiskProfile,
    Signal,
    StrategyEvidence,
)
from hypothesis import given, settings
from hypothesis import strategies as st

NOW = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)


def portfolio(**kw: object) -> Portfolio:
    base = dict(cash=1000.0, equity_peak=1000.0, day_start_equity=1000.0)
    base.update(kw)
    return Portfolio(**base)  # type: ignore[arg-type]


def signal(**kw: object) -> Signal:
    base = dict(
        signal_id="s1",
        strategy_id="momentum",
        symbol="SPY",
        side=OrderSide.BUY,
        entry_price=100.0,
        stop_price=96.0,
        created_at=NOW,
    )
    base.update(kw)
    return Signal(**base)  # type: ignore[arg-type]


def market(**kw: object) -> MarketState:
    base = dict(
        symbol="SPY",
        last_data_at=NOW - timedelta(seconds=60),
        now=NOW,
        bid=99.98,
        ask=100.02,
        avg_daily_volume=1e6,
    )
    base.update(kw)
    return MarketState(**base)  # type: ignore[arg-type]


def evidence(**kw: object) -> StrategyEvidence:
    base = dict(
        strategy_id="momentum",
        edge_score=70.0,
        p_win=0.6,
        avg_win=0.05,
        avg_loss=0.02,
        expected_gross_edge=0.02,
        confidence=0.99,
        n_trades=400,
    )
    base.update(kw)
    return StrategyEvidence(**base)  # type: ignore[arg-type]


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine(RiskProfile.from_aggressiveness(50))


# --------------------------------------------------------------------------- profile


def test_slider_is_monotonic_and_clamped() -> None:
    lo, mid, hi = (RiskProfile.from_aggressiveness(x) for x in (0, 50, 100))
    assert lo.risk_per_trade < mid.risk_per_trade < hi.risk_per_trade
    assert lo.min_edge_score > mid.min_edge_score > hi.min_edge_score
    assert lo.cash_reserve > hi.cash_reserve
    assert hi.risk_per_trade <= ABSOLUTE_LIMITS.max_risk_per_trade
    assert hi.max_portfolio_exposure <= 1.0
    with pytest.raises(ValueError):
        RiskProfile.from_aggressiveness(101)


def test_manual_profile_cannot_breach_absolute_limits() -> None:
    p = RiskProfile.from_aggressiveness(50)
    with pytest.raises(ValueError):
        replace(p, risk_per_trade=0.10)
    with pytest.raises(ValueError):
        replace(p, max_portfolio_exposure=1.5)  # leverage
    with pytest.raises(ValueError):
        replace(p, cash_reserve=0.0)


@given(st.floats(0, 100))
def test_any_slider_value_respects_limits(level: float) -> None:
    p = RiskProfile.from_aggressiveness(level)
    assert 0 < p.risk_per_trade <= ABSOLUTE_LIMITS.max_risk_per_trade
    assert p.kelly_coefficient <= ABSOLUTE_LIMITS.max_kelly_coefficient
    assert p.cash_reserve >= ABSOLUTE_LIMITS.min_cash_reserve


# --------------------------------------------------------------------------- engine


def test_happy_path_approves(engine: RiskEngine) -> None:
    d = engine.evaluate(portfolio(), signal(), market(), evidence())
    assert d.action is RiskAction.APPROVE, d.reasons
    assert d.approved and d.reasons == []
    assert d.sizing is not None and d.sizing.limiting_factor == "fractional_kelly"
    assert d.notional == pytest.approx(1000 * 0.44 * 0.30, rel=1e-3)
    assert d.quantity * (100.02 - 96) <= 1000 * engine.profile.risk_per_trade


@pytest.mark.parametrize(
    ("check", "kwargs"),
    [
        ("kill_switch", {"kill_switch": True}),
        ("api_health", {"market": market(api_healthy=False)}),
        ("reconciliation", {"portfolio": portfolio(reconciled=False)}),
        ("stale_data", {"market": market(last_data_at=NOW - timedelta(hours=2))}),
        ("stale_data", {"market": market(last_data_at=NOW + timedelta(minutes=5))}),
        ("trading_hours", {"market": market(market_open=False)}),
        (
            "duplicate_order",
            {"portfolio": portfolio(pending_order_keys=frozenset({"momentum:SPY:BUY:s1"}))},
        ),
        ("symbol_match", {"market": market(symbol="QQQ")}),
        ("valid_quote", {"market": market(bid=101.0, ask=100.0)}),
        ("max_daily_loss", {"portfolio": portfolio(day_start_equity=1100.0, equity_peak=1100.0)}),
        ("max_drawdown", {"portfolio": portfolio(equity_peak=1300.0)}),
        ("consecutive_losses", {"portfolio": portfolio(consecutive_losses=10)}),
        ("max_spread", {"market": market(bid=99.0, ask=101.0)}),
        ("max_slippage", {"market": market(expected_slippage_pct=0.01)}),
        ("min_liquidity", {"market": market(avg_daily_volume=0)}),
        ("evidence", {"evidence": None}),
        ("evidence_strategy", {"evidence": evidence(strategy_id="other")}),
        ("min_edge_score", {"evidence": evidence(edge_score=10)}),
        ("min_confidence", {"evidence": evidence(confidence=0.6)}),
        ("min_expected_net_edge", {"evidence": evidence(expected_gross_edge=0.004)}),
        ("valid_stop", {"signal": signal(stop_price=101.0)}),
        ("valid_stop", {"signal": signal(stop_price=0.0)}),
        ("min_order_notional", {"evidence": evidence(p_win=0.25)}),
    ],
)
def test_each_check_rejects(engine: RiskEngine, check: str, kwargs: dict[str, object]) -> None:
    args = {
        "portfolio": portfolio(),
        "signal": signal(),
        "market": market(),
        "evidence": evidence(),
    }
    kill = bool(kwargs.pop("kill_switch", False))
    args.update(kwargs)
    d = engine.evaluate(
        args["portfolio"],
        args["signal"],
        args["market"],
        args["evidence"],
        kill_switch=kill,  # type: ignore[arg-type]
    )
    assert d.action is RiskAction.REJECT
    assert check in {c.name for c in d.checks if not c.passed}
    assert d.quantity == 0


def test_max_positions(engine: RiskEngine) -> None:
    held = {
        f"S{i}": Position(f"S{i}", 1.0, 10.0, 10.0) for i in range(engine.profile.max_positions)
    }
    d = engine.evaluate(portfolio(positions=held, cash=950.0), signal(), market(), evidence())
    assert "max_positions" in {c.name for c in d.checks if not c.passed}


def test_adjust_size_when_position_cap_binds(engine: RiskEngine) -> None:
    held = {"SPY": Position("SPY", 1.5, 100.0, 100.0)}  # 150 € already in SPY
    d = engine.evaluate(portfolio(cash=850.0, positions=held), signal(), market(), evidence())
    assert d.action is RiskAction.ADJUST_SIZE
    assert "max_position_pct" in d.adjustments
    assert d.notional <= 1000 * engine.profile.max_position_pct - 150 + 1e-6
    assert d.notional < d.requested_notional


def test_portfolio_exposure_cap(engine: RiskEngine) -> None:
    held = {"QQQ": Position("QQQ", 7.0, 100.0, 100.0)}  # 70 % invested > 60 % cap
    d = engine.evaluate(portfolio(cash=300.0, positions=held), signal(), market(), evidence())
    assert d.action is RiskAction.REJECT
    assert "max_portfolio_exposure" in d.adjustments


def test_cash_reserve_cap() -> None:
    profile = replace(
        RiskProfile.from_aggressiveness(50), max_portfolio_exposure=0.9, cash_reserve=0.5
    )
    eng = RiskEngine(profile)
    held = {"QQQ": Position("QQQ", 4.0, 100.0, 100.0)}
    d = eng.evaluate(portfolio(cash=600.0, positions=held), signal(), market(), evidence())
    assert d.action is RiskAction.ADJUST_SIZE
    assert d.adjustments == ("cash_reserve",)
    assert d.notional <= 600 - 500 + 1e-6


def test_sell_exits_allowed_shorts_forbidden(engine: RiskEngine) -> None:
    held = {"SPY": Position("SPY", 2.0, 90.0, 100.0)}
    sell = signal(side=OrderSide.SELL)
    d = engine.evaluate(portfolio(positions=held, consecutive_losses=99), sell, market(), None)
    assert d.action is RiskAction.APPROVE and d.quantity == 2.0
    short = engine.evaluate(portfolio(), sell, market(), evidence())
    assert short.action is RiskAction.REJECT
    assert "no_short_selling" in {c.name for c in short.checks if not c.passed}
    killed = engine.evaluate(portfolio(positions=held), sell, market(), None, kill_switch=True)
    assert killed.action is RiskAction.REJECT


def test_small_account_100_eur() -> None:
    eng = RiskEngine(RiskProfile.from_aggressiveness(20))
    d = eng.evaluate(
        portfolio(cash=100.0, equity_peak=100.0, day_start_equity=100.0),
        signal(),
        market(),
        evidence(),
    )
    assert d.approved
    assert d.quantity * (100.02 - 96) <= 100 * eng.profile.risk_per_trade + 1e-9
    assert d.notional <= 100 * eng.profile.max_position_pct + 1e-9


@settings(max_examples=200, deadline=None)
@given(
    level=st.floats(0, 100),
    cash=st.floats(10, 1e6),
    stop=st.floats(50, 99.9),
    p_win=st.floats(0.3, 0.9),
    avg_win=st.floats(0.005, 0.2),
    avg_loss=st.floats(0.005, 0.2),
)
def test_property_approved_orders_never_exceed_limits(
    level: float, cash: float, stop: float, p_win: float, avg_win: float, avg_loss: float
) -> None:
    eng = RiskEngine(RiskProfile.from_aggressiveness(level))
    pf = portfolio(cash=cash, equity_peak=cash, day_start_equity=cash)
    ev = evidence(p_win=p_win, avg_win=avg_win, avg_loss=avg_loss, edge_score=90)
    d = eng.evaluate(pf, signal(stop_price=stop), market(), ev)
    if d.approved:
        p = eng.profile
        assert d.quantity * (100.02 - stop) <= cash * p.risk_per_trade * (1 + 1e-6)
        assert d.notional <= cash * p.max_position_pct + 1e-6
        assert d.notional <= cash * (1 - p.cash_reserve) + 1e-6
        assert d.notional <= cash  # never leverage
