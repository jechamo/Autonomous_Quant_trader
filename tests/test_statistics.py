import numpy as np
import pandas as pd
import pytest
from aqt.statistics import (
    BetaPosterior,
    benjamini_hochberg,
    compute_edge_score,
    compute_metrics,
    max_drawdown,
    mean_return_test,
    monte_carlo_trades,
    parameter_stability,
    purged_kfold_splits,
    split_in_out_of_sample,
    walk_forward,
    wilson_interval,
)
from aqt.strategies import expand_grid, get_strategy


def test_metrics_basic() -> None:
    m = compute_metrics(np.array([0.02, -0.01, 0.03, -0.01]))
    assert m.n_trades == 4
    assert m.win_rate == 0.5
    assert m.avg_win == pytest.approx(0.025)
    assert m.avg_loss == pytest.approx(0.01)
    assert m.expected_value == pytest.approx(0.0075)
    assert m.profit_factor == pytest.approx(2.5)
    assert max_drawdown([1, 2, 1, 3]) == pytest.approx(-0.5)
    empty = compute_metrics(np.array([]))
    assert empty.n_trades == 0 and empty.expected_value == 0


def test_win_rate_is_not_ev() -> None:
    """90 % win rate with large losses is still negative EV."""
    tr = np.array([0.01] * 9 + [-0.2])
    m = compute_metrics(tr)
    assert m.win_rate == 0.9 and m.expected_value < 0


def test_wilson_interval() -> None:
    lo, hi = wilson_interval(95, 100)
    assert lo == pytest.approx(0.8882, abs=1e-3) and hi == pytest.approx(0.9785, abs=1e-3)
    lo2, hi2 = wilson_interval(9500, 10000)
    assert hi2 - lo2 < (hi - lo) / 5
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(5, 3)


def test_bayes_evidence_scales_with_sample() -> None:
    small = BetaPosterior().update(95, 5)
    big = BetaPosterior().update(9500, 500)
    assert small.mean == pytest.approx(big.mean, abs=0.01)
    assert big.std < small.std / 5
    lo, hi = big.credible_interval()
    assert lo < 0.95 < hi
    sequential = BetaPosterior()
    for won in [True, False, True]:
        sequential = sequential.update_one(won)
    assert sequential == BetaPosterior().update(2, 1)
    assert sequential.n_observations == 3
    assert BetaPosterior().breakeven_win_rate(2.0, 1.0) == pytest.approx(1 / 3)
    with pytest.raises(ValueError):
        BetaPosterior(0, 1)


def test_mean_return_test() -> None:
    rng = np.random.default_rng(0)
    assert mean_return_test(rng.normal(0.01, 0.02, 500)).p_value < 0.001
    assert mean_return_test(rng.normal(-0.01, 0.02, 500)).p_value > 0.99
    assert mean_return_test(np.array([0.1])).p_value == 1.0


def test_benjamini_hochberg() -> None:
    p = np.array([0.01, 0.04, 0.03, 0.005, 0.5])
    rej, adj = benjamini_hochberg(p, 0.05)
    assert rej.tolist() == [True, True, True, True, False]
    assert adj[3] == pytest.approx(0.025)
    assert (adj >= p).all()


def test_fdr_controls_false_discoveries_under_null() -> None:
    rng = np.random.default_rng(1)
    p = rng.uniform(size=10_000)
    assert (p < 0.05).sum() > 400  # naive testing "discovers" hundreds of fake edges
    assert benjamini_hochberg(p, 0.05)[0].sum() <= 5


def test_monte_carlo() -> None:
    mc = monte_carlo_trades(np.array([0.02, -0.01] * 50), n_simulations=500, seed=1)
    assert mc.final_return_p5 <= mc.final_return_p50 <= mc.final_return_p95
    assert mc.max_drawdown_p95 <= mc.max_drawdown_p50 <= 0
    assert 0 <= mc.prob_loss <= 1
    assert monte_carlo_trades(np.array([])).final_return_p50 == 0


def test_purged_kfold() -> None:
    splits = purged_kfold_splits(100, 5, embargo=3)
    assert len(splits) == 5
    for train, test in splits:
        assert not set(train) & set(test)
        gap_lo = test.min() - 3
        gap_hi = test.max() + 3
        assert not ((train >= gap_lo) & (train <= gap_hi)).any()
    with pytest.raises(ValueError):
        purged_kfold_splits(3, 5)


def test_split_and_walk_forward(features: pd.DataFrame) -> None:
    is_df, oos_df = split_in_out_of_sample(features, 0.25)
    assert is_df.index[-1] < oos_df.index[0]
    assert len(oos_df) == len(features) - int(len(features) * 0.75)
    spec, grid = get_strategy("breakout")
    wf = walk_forward(features, expand_grid(spec, grid)[:3], n_windows=3)
    assert len(wf.windows) == 3
    for w in wf.windows:
        assert w.train_end < w.test_start
    assert isinstance(wf.to_dict()["efficiency"], float)


def test_parameter_stability() -> None:
    robust = parameter_stability([0.01, 0.012, 0.009, 0.011])
    lucky = parameter_stability([-0.01, -0.02, 0.05, -0.005])
    assert robust["stability_score"] > 0.7
    assert lucky["stability_score"] == 0
    assert parameter_stability([])["n_variants"] == 0


def test_edge_score() -> None:
    rng = np.random.default_rng(3)
    good = compute_edge_score(rng.normal(0.01, 0.02, 300))
    assert good.has_edge and good.score > 30
    bad = compute_edge_score(rng.normal(-0.01, 0.02, 300))
    assert bad.score == 0 and not bad.has_edge
    assert compute_edge_score(rng.normal(0.01, 0.02, 300), regime_compatibility=0).score == 0
    tiny = compute_edge_score(np.array([0.01, 0.02]))
    assert tiny.score < good.score
