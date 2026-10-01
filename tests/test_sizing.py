import pytest
from aqt.sizing import PositionSizingEngine, kelly_fraction


def _size(**kw: float) -> float:
    base = dict(
        equity=500.0,
        entry_price=100.0,
        stop_price=96.0,
        p_win=0.6,
        avg_win=0.05,
        avg_loss=0.02,
        risk_per_trade=0.01,
        kelly_coefficient=1.0,
    )
    base.update(kw)
    return PositionSizingEngine().size(**base).notional  # type: ignore[arg-type]


def test_prd_examples() -> None:
    # 500 €, 1 % risk, 4 % stop -> 125 €; 10 % stop -> 50 €
    assert _size() == pytest.approx(125.0)
    assert _size(stop_price=90.0) == pytest.approx(50.0)


def test_fractional_kelly_limits() -> None:
    k = kelly_fraction(0.55, 0.04, 0.02)
    assert k == pytest.approx(0.55 - 0.45 / 2)
    res = PositionSizingEngine().size(
        equity=1000,
        entry_price=100,
        stop_price=99,
        p_win=0.55,
        avg_win=0.04,
        avg_loss=0.02,
        risk_per_trade=0.02,
        kelly_coefficient=0.25,
    )
    assert res.limiting_factor == "fractional_kelly"
    assert res.notional == pytest.approx(1000 * k * 0.25)
    assert res.max_loss == pytest.approx(res.notional * 0.01)


def test_no_edge_no_size() -> None:
    assert kelly_fraction(0.3, 0.01, 0.02) == 0
    assert kelly_fraction(0.6, 0, 0.02) == 0
    assert _size(p_win=0.2) == 0


def test_scales_with_capital() -> None:
    assert _size(equity=50_000) == pytest.approx(100 * _size(equity=500))


@pytest.mark.parametrize(
    "kw",
    [
        {"equity": 0},
        {"stop_price": 101},
        {"risk_per_trade": 0},
        {"kelly_coefficient": 2},
        {"entry_price": -1},
    ],
)
def test_invalid_inputs(kw: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        _size(**kw)
    with pytest.raises(ValueError):
        kelly_fraction(1.5, 1, 1)
