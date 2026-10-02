"""Research pipeline: data -> features -> strategy variants -> backtest -> validation -> verdict."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from aqt import __version__
from aqt.backtest import CostModel, run_backtest
from aqt.features import FeatureEngine
from aqt.statistics import (
    benjamini_hochberg,
    compute_edge_score,
    compute_metrics,
    mean_return_test,
    metrics_by_regime,
    monte_carlo_trades,
    parameter_stability,
    split_in_out_of_sample,
    walk_forward,
    wilson_interval,
)
from aqt.statistics.bayes import BetaPosterior
from aqt.strategies import StrategySpec, expand_grid, resolve_strategy

PERIODS_PER_YEAR = {
    "1d": 252,
    "1h": 252 * 7,
    "15m": 252 * 26,
    "5m": 252 * 78,
    # 24/7 markets (crypto): every minute of the year is a bar.
    "1min": 365 * 24 * 60,
    "5min": 365 * 24 * 12,
    "15min": 365 * 24 * 4,
}


@dataclass(frozen=True)
class ResearchConfig:
    symbol: str
    timeframe: str
    strategy: str
    catalog: str = "daily"  # which hypothesis catalog to resolve ``strategy`` from
    # An explicit rule + grid (e.g. an AI-proposed hypothesis) instead of a catalog entry.
    spec: StrategySpec | None = None
    grid: dict[str, list[float | int]] | None = None
    oos_fraction: float = 0.3
    walk_forward_windows: int = 5
    fdr_q: float = 0.05
    min_trades: int = 30
    monte_carlo_sims: int = 5000
    max_acceptable_drawdown: float = -0.20
    seed: int = 7
    notional: float = 100.0
    costs: CostModel = field(default_factory=CostModel)


@dataclass
class ResearchReport:
    meta: dict[str, Any]
    config: dict[str, Any]
    selected_strategy: dict[str, Any]
    multiple_testing: dict[str, Any]
    in_sample: dict[str, Any]
    out_of_sample: dict[str, Any]
    cost_analysis: dict[str, Any]
    walk_forward: dict[str, Any]
    monte_carlo: dict[str, Any]
    regimes: dict[str, Any]
    parameter_stability: dict[str, Any]
    edge: dict[str, Any]
    verdict: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


def _clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, float | np.floating):
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def _data_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256(pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes())
    return h.hexdigest()[:16]


def _regime_compatibility(by_regime: dict[str, dict[str, Any]], current: str | None) -> float:
    if current is None or current not in by_regime:
        return 0.5
    stats = by_regime[current]
    if stats["n_trades"] < 5:
        return 0.5
    return 1.0 if stats["expected_value"] > 0 else 0.0


def run_research(df: pd.DataFrame, cfg: ResearchConfig) -> ResearchReport:
    ppy = PERIODS_PER_YEAR.get(cfg.timeframe, 252)
    features = FeatureEngine().compute(df)
    if cfg.spec is not None:
        base, grid = cfg.spec, cfg.grid or {}
    else:
        base, grid = resolve_strategy(cfg.strategy, cfg.catalog)
    variants = expand_grid(base, grid)
    if all(v.params != base.params for v in variants):
        variants.insert(0, base.render())
    is_df, oos_df = split_in_out_of_sample(features, cfg.oos_fraction)

    # In-sample sweep + FDR control across every variant tested.
    is_results = [run_backtest(is_df, v, cfg.costs, cfg.notional) for v in variants]
    tests = [mean_return_test(r.trade_returns) for r in is_results]
    pvals = np.array([t.p_value for t in tests])
    rejected, adj = benjamini_hochberg(pvals, cfg.fdr_q)
    scores = [
        t.t_stat if r.trade_returns.size >= max(5, cfg.min_trades // 3) else -np.inf
        for t, r in zip(tests, is_results, strict=True)
    ]
    best = int(np.argmax(scores))
    spec = variants[best]
    is_res = is_results[best]
    is_metrics = compute_metrics(is_res.trade_returns, is_res.bar_returns, is_res.exposure, ppy)

    # Out-of-sample: the selected variant is frozen and evaluated once on unseen data.
    oos_res = run_backtest(oos_df, spec, cfg.costs, cfg.notional)
    oos_tr = oos_res.trade_returns
    oos_metrics = compute_metrics(oos_tr, oos_res.bar_returns, oos_res.exposure, ppy)
    oos_test = mean_return_test(oos_tr)
    wins = int((oos_tr > 0).sum())
    posterior = BetaPosterior().update(wins, int(oos_tr.size) - wins)

    # Cost awareness: same trades, gross vs net.
    full_res = run_backtest(features, spec, cfg.costs, cfg.notional)
    gross = full_res.gross_trade_returns
    net = full_res.trade_returns

    wf = walk_forward(features, variants, cfg.walk_forward_windows, costs=cfg.costs)
    wf_oos = wf.oos_returns
    mc = monte_carlo_trades(
        wf_oos if wf_oos.size else oos_tr,
        cfg.monte_carlo_sims,
        drawdown_threshold=cfg.max_acceptable_drawdown,
        seed=cfg.seed,
    )
    by_regime = metrics_by_regime(full_res.trades)
    last_regime = features["regime"].dropna()
    current_regime = str(last_regime.iloc[-1]) if len(last_regime) else None
    compat = _regime_compatibility(by_regime, current_regime)
    stability = parameter_stability(
        [float(r.trade_returns.mean()) if r.trades else 0.0 for r in is_results]
    )
    edge = compute_edge_score(
        oos_tr, p_value=oos_test.p_value, regime_compatibility=compat, min_trades=cfg.min_trades
    )

    checks = {
        "oos_positive_ev_after_costs": oos_metrics.expected_value > 0,
        "oos_statistically_significant": oos_test.p_value < 0.05,
        "survives_fdr_in_sample": bool(rejected[best]),
        "walk_forward_positive": bool(wf_oos.size and wf_oos.mean() > 0),
        "sufficient_oos_sample": oos_metrics.n_trades >= cfg.min_trades,
        "drawdown_within_limit": mc.max_drawdown_p95 > cfg.max_acceptable_drawdown,
        "parameter_stability": stability["fraction_positive"] >= 0.5,
        "edge_after_costs": bool(net.size and net.mean() > 0),
    }
    is_candidate = all(checks.values())

    return ResearchReport(
        meta={
            "generated_at": datetime.now(UTC).isoformat(),
            "aqt_version": __version__,
            "data_hash": _data_hash(df),
            "data_start": str(df.index[0]),
            "data_end": str(df.index[-1]),
            "n_bars": len(df),
        },
        config={
            **{k: v for k, v in asdict(cfg).items() if k not in ("costs", "spec", "grid")},
            "costs": asdict(cfg.costs),
            "round_trip_cost_pct": cfg.costs.round_trip_pct(cfg.notional),
        },
        selected_strategy={
            "name": spec.name,
            "family": spec.family,
            "config_hash": spec.config_hash(),
            "params": spec.params,
            "spec": spec.model_dump(mode="json"),
        },
        multiple_testing={
            "n_hypotheses": len(variants),
            "method": "benjamini_hochberg",
            "q": cfg.fdr_q,
            "n_discoveries": int(rejected.sum()),
            "selected_index": best,
            "variant_names": [v.name for v in variants],
            "p_values": [float(x) for x in pvals],
            "selected_raw_p": float(pvals[best]),
            "selected_adjusted_p": float(adj[best]),
        },
        in_sample={"period": [str(is_df.index[0]), str(is_df.index[-1])], **is_metrics.to_dict()},
        out_of_sample={
            "period": [str(oos_df.index[0]), str(oos_df.index[-1])],
            **oos_metrics.to_dict(),
            "win_rate_ci95": wilson_interval(wins, int(oos_tr.size)),
            "ev_ci95": [oos_test.ci_low, oos_test.ci_high],
            "p_value": oos_test.p_value,
            "bayes_p_win": posterior.mean,
            "bayes_p_win_credible95": posterior.credible_interval(),
        },
        cost_analysis={
            "n_trades": int(net.size),
            "gross_ev": float(gross.mean()) if gross.size else 0.0,
            "net_ev": float(net.mean()) if net.size else 0.0,
            "cost_per_trade": float((gross - net).mean()) if net.size else 0.0,
        },
        walk_forward=wf.to_dict(),
        monte_carlo=mc.to_dict(),
        regimes={"current": current_regime, "compatibility": compat, "by_regime": by_regime},
        parameter_stability=stability,
        edge=edge.to_dict(),
        verdict={
            "decision": "CHALLENGER_CANDIDATE" if is_candidate else "REJECTED",
            "checks": checks,
            "failed": [k for k, v in checks.items() if not v],
            "note": (
                "NO TRADE is a valid outcome: without a defensible edge the system stays in cash."
            ),
        },
    )
