"""Panel (pooled) research: one rule evaluated on every symbol of the universe at once.

Daily anomalies fire a few times a year per stock, so tested symbol by symbol almost every one
fails for lack of out-of-sample trades even when the effect exists; the studies behind them
measure the effect across many stocks. This module runs the same pipeline as
:func:`aqt.research.pipeline.run_research` — in-sample sweep with BH-FDR, frozen out-of-sample,
walk-forward, Monte Carlo, parameter stability, costs — on the pooled trades of all symbols, and
returns a report with the same schema (so the global FDR, the lab and the dashboard need no
special case). Two rules keep it honest:

* **One calendar for everyone.** The in-/out-of-sample frontier and the walk-forward windows are
  dates shared by all symbols: nothing after the frontier of any symbol informs the selection.
* **Dates, not trades, are the observations.** Trades entered on the same bar are correlated
  (the whole market moves together), so they are averaged per entry date and every significance
  test, sample-size check and Monte Carlo uses those daily means. Ten copies of one stock are
  worth exactly as much evidence as one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from aqt import __version__
from aqt.backtest import Trade, run_backtest
from aqt.research.pipeline import PERIODS_PER_YEAR, ResearchConfig, ResearchReport
from aqt.statistics import (
    benjamini_hochberg,
    compute_edge_score,
    compute_metrics,
    mean_return_test,
    metrics_by_regime,
    monte_carlo_trades,
    parameter_stability,
    wilson_interval,
)
from aqt.statistics.bayes import BetaPosterior
from aqt.statistics.validation import WalkForwardResult, WalkForwardWindow
from aqt.strategies import StrategySpec, expand_grid, resolve_strategy

Frames = Mapping[str, pd.DataFrame]


def date_means(trades: Sequence[Trade], gross: bool = False) -> np.ndarray:
    """Mean return of the trades entered on each bar, in time order (one value per date)."""
    if not trades:
        return np.empty(0)
    s = pd.Series(
        [t.gross_return if gross else t.net_return for t in trades],
        index=pd.DatetimeIndex([t.entry_time for t in trades]),
    )
    return s.groupby(level=0).mean().sort_index().to_numpy(dtype=float)


def common_frontier(features: Frames, fraction: float) -> pd.Timestamp:
    """The date splitting the union of all bars at ``fraction`` (same for every symbol)."""
    stamps = pd.DatetimeIndex(sorted(set().union(*(f.index for f in features.values()))))
    return stamps[int(len(stamps) * fraction)]


def _slice(
    features: Frames, lo: pd.Timestamp | None, hi: pd.Timestamp | None
) -> dict[str, pd.DataFrame]:
    out = {}
    for sym, f in features.items():
        mask = np.ones(len(f), dtype=bool)
        if lo is not None:
            mask &= f.index >= lo
        if hi is not None:
            mask &= f.index < hi
        part = f[mask]
        if len(part) >= 2:
            out[sym] = part
    return out


def trades_by_symbol(
    features: Frames, spec: StrategySpec, cfg: ResearchConfig
) -> dict[str, list[Trade]]:
    return {s: run_backtest(f, spec, cfg.costs, cfg.notional).trades for s, f in features.items()}


def pooled_trades(features: Frames, spec: StrategySpec, cfg: ResearchConfig) -> list[Trade]:
    return [t for ts in trades_by_symbol(features, spec, cfg).values() for t in ts]


def _score(means: np.ndarray, min_n: int) -> float:
    return mean_return_test(means).t_stat if means.size >= min_n else -np.inf


def panel_walk_forward(
    features: Frames, variants: Sequence[StrategySpec], cfg: ResearchConfig
) -> WalkForwardResult:
    """Anchored walk-forward with window frontiers shared by every symbol."""
    stamps = pd.DatetimeIndex(sorted(set().union(*(f.index for f in features.values()))))
    bounds = np.linspace(0, len(stamps), cfg.walk_forward_windows + 2, dtype=int)
    edge = [stamps[min(b, len(stamps) - 1)] for b in bounds]
    windows: list[WalkForwardWindow] = []
    oos: list[Trade] = []
    for k in range(1, cfg.walk_forward_windows + 1):
        train = _slice(features, None, edge[k])
        last = k == cfg.walk_forward_windows
        test = _slice(features, edge[k], None if last else edge[k + 1])
        if not train or not test:
            continue
        best, best_score, best_ev = variants[0], -np.inf, 0.0
        for v in variants:
            means = date_means(pooled_trades(train, v, cfg))
            score = _score(means, 5)
            if score > best_score:
                best, best_score, best_ev = v, score, float(means.mean()) if means.size else 0.0
        trades = pooled_trades(test, best, cfg)
        oos.extend(trades)
        tm = date_means(trades)
        windows.append(
            WalkForwardWindow(
                train_start=str(edge[0]),
                train_end=str(edge[k]),
                test_start=str(edge[k]),
                test_end=str(edge[k + 1]),
                selected=best.name,
                is_ev=best_ev,
                oos_ev=float(tm.mean()) if tm.size else 0.0,
                oos_trades=int(tm.size),
            )
        )
    return WalkForwardResult(windows=windows, oos_trades=oos)


def _hash(df: pd.DataFrame) -> str:
    raw = pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()[:8]


def run_panel_research(features: Frames, cfg: ResearchConfig) -> ResearchReport:
    """``features``: the FeatureEngine output of every symbol (same timeframe)."""
    features = {s: f for s, f in features.items() if len(f) >= 2}
    if not features:
        raise ValueError("no symbol with data")
    ppy = PERIODS_PER_YEAR.get(cfg.timeframe, 252)
    if cfg.spec is not None:
        base, grid = cfg.spec, cfg.grid or {}
    else:
        base, grid = resolve_strategy(cfg.strategy, cfg.catalog)
    variants = expand_grid(base, grid)
    if all(v.params != base.params for v in variants):
        variants.insert(0, base.render())
    frontier = common_frontier(features, 1 - cfg.oos_fraction)
    is_feats, oos_feats = _slice(features, None, frontier), _slice(features, frontier, None)

    is_trades = [pooled_trades(is_feats, v, cfg) for v in variants]
    is_means = [date_means(t) for t in is_trades]
    tests = [mean_return_test(m) for m in is_means]
    pvals = np.array([t.p_value for t in tests])
    rejected, adj = benjamini_hochberg(pvals, cfg.fdr_q)
    scores = [_score(m, max(5, cfg.min_trades // 3)) for m in is_means]
    best = int(np.argmax(scores))
    spec = variants[best]
    is_metrics = compute_metrics(is_means[best], periods_per_year=ppy)

    oos_by_symbol = trades_by_symbol(oos_feats, spec, cfg)
    oos_trades = [t for ts in oos_by_symbol.values() for t in ts]
    oos_means = date_means(oos_trades)
    oos_metrics = compute_metrics(oos_means, periods_per_year=ppy)
    oos_test = mean_return_test(oos_means)
    wins = int((oos_means > 0).sum())
    posterior = BetaPosterior().update(wins, int(oos_means.size) - wins)

    full_trades = pooled_trades(features, spec, cfg)
    net, gross = date_means(full_trades), date_means(full_trades, gross=True)

    wf = panel_walk_forward(features, variants, cfg)
    wf_means = date_means(wf.oos_trades)
    mc = monte_carlo_trades(
        wf_means if wf_means.size else oos_means,
        cfg.monte_carlo_sims,
        drawdown_threshold=cfg.max_acceptable_drawdown,
        seed=cfg.seed,
    )
    stability = parameter_stability([float(m.mean()) if m.size else 0.0 for m in is_means])
    compat = 0.5  # regimes differ across symbols: neutral
    edge = compute_edge_score(
        oos_means, p_value=oos_test.p_value, regime_compatibility=compat, min_trades=cfg.min_trades
    )
    checks = {
        "oos_positive_ev_after_costs": oos_metrics.expected_value > 0,
        "oos_statistically_significant": oos_test.p_value < 0.05,
        "survives_fdr_in_sample": bool(rejected[best]),
        "walk_forward_positive": bool(wf_means.size and wf_means.mean() > 0),
        "sufficient_oos_sample": oos_metrics.n_trades >= cfg.min_trades,  # dates, not trades
        "drawdown_within_limit": mc.max_drawdown_p95 > cfg.max_acceptable_drawdown,
        "parameter_stability": stability["fraction_positive"] >= 0.5,
        "edge_after_costs": bool(net.size and net.mean() > 0),
    }
    is_candidate = all(checks.values())
    hashes = "|".join(f"{s}:{_hash(f)}" for s, f in sorted(features.items()))
    first = min(f.index[0] for f in features.values())
    last = max(f.index[-1] for f in features.values())
    wf_dict = wf.to_dict()
    wf_dict["oos_ev"] = float(wf_means.mean()) if wf_means.size else 0.0
    return ResearchReport(
        meta={
            "generated_at": datetime.now(UTC).isoformat(),
            "aqt_version": __version__,
            "data_hash": hashlib.sha256(hashes.encode()).hexdigest()[:16],
            "data_start": str(first),
            "data_end": str(last),
            "n_bars": int(sum(len(f) for f in features.values())),
            "panel": {"symbols": sorted(features), "unit": "entry date"},
        },
        config={
            **{k: v for k, v in asdict(cfg).items() if k not in ("costs", "spec", "grid")},
            "symbol": "*",
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
        in_sample={"period": [str(first), str(frontier)], **is_metrics.to_dict()},
        out_of_sample={
            "period": [str(frontier), str(last)],
            **oos_metrics.to_dict(),
            "n_trades_total": len(oos_trades),
            "trades_by_symbol": {sym: len(ts) for sym, ts in sorted(oos_by_symbol.items())},
            "win_rate_ci95": wilson_interval(wins, int(oos_means.size)),
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
        walk_forward=wf_dict,
        monte_carlo=mc.to_dict(),
        regimes={
            "current": None,
            "compatibility": compat,
            "by_regime": metrics_by_regime(full_trades),
        },
        parameter_stability=stability,
        edge=edge.to_dict(),
        verdict={
            "decision": "CHALLENGER_CANDIDATE" if is_candidate else "REJECTED",
            "checks": checks,
            "failed": [k for k, v in checks.items() if not v],
            "note": "Pooled over the universe; observations are entry dates, not trades.",
        },
    )
