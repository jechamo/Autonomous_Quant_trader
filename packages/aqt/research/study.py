"""Multi-symbol × multi-strategy study with *global* multiple-testing control.

Every parameter variant of every strategy on every symbol is one hypothesis. Benjamini–Hochberg
is applied across all of them: testing thousands of combinations makes some look excellent by
pure chance, so a pair can only become a Challenger candidate if its selected variant also
survives the study-wide FDR.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from aqt import __version__
from aqt.backtest import CostModel
from aqt.data.universe import get_instrument
from aqt.research.pipeline import ResearchConfig, run_research
from aqt.statistics import benjamini_hochberg

MIN_BARS = 600


@dataclass(frozen=True)
class StudyConfig:
    timeframe: str = "1d"
    fdr_q: float = 0.05
    oos_fraction: float = 0.3
    walk_forward_windows: int = 5
    monte_carlo_sims: int = 2000
    min_trades: int = 30
    seed: int = 7
    name: str = "study"
    catalog: str = "daily"


@dataclass
class PairResult:
    symbol: str
    strategy: str
    tradable: bool
    currency: str
    report: dict[str, Any] | None = None
    error: str | None = None
    survives_global_fdr: bool = False
    global_adjusted_p: float | None = None
    decision: str = "ERROR"

    def summary(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "tradable_t212_eu": self.tradable,
            "currency": self.currency,
            "decision": self.decision,
            "error": self.error,
        }
        if self.report is None:
            return base
        r = self.report
        return {
            **base,
            "selected": r["selected_strategy"]["name"],
            "local_verdict": r["verdict"]["decision"],
            "failed_checks": r["verdict"]["failed"],
            "oos_trades": r["out_of_sample"]["n_trades"],
            "oos_ev": r["out_of_sample"]["expected_value"],
            "oos_p_value": r["out_of_sample"]["p_value"],
            "net_ev_full": r["cost_analysis"]["net_ev"],
            "wf_oos_ev": r["walk_forward"]["oos_ev"],
            "edge_score": r["edge"]["score"],
            "survives_global_fdr": self.survives_global_fdr,
            "global_adjusted_p": self.global_adjusted_p,
        }


@dataclass
class StudyReport:
    config: StudyConfig
    pairs: list[PairResult]
    n_hypotheses: int
    n_global_discoveries: int
    data_hashes: dict[str, str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def study_hash(self) -> str:
        payload = "|".join(f"{k}:{v}" for k, v in sorted(self.data_hashes.items()))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def candidates(self) -> list[PairResult]:
        return [p for p in self.pairs if p.decision == "CHALLENGER_CANDIDATE"]

    def ranking(self) -> list[dict[str, Any]]:
        rows = [p.summary() for p in self.pairs]
        return sorted(
            rows,
            key=lambda r: (
                r["decision"] == "CHALLENGER_CANDIDATE",
                r.get("edge_score") or 0.0,
                r.get("oos_ev") or -np.inf,
            ),
            reverse=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": {
                "name": self.config.name,
                "generated_at": self.generated_at,
                "aqt_version": __version__,
                "study_hash": self.study_hash,
                "n_symbols": len({p.symbol for p in self.pairs}),
                "n_pairs": len(self.pairs),
                "n_errors": sum(p.error is not None for p in self.pairs),
                "n_hypotheses": self.n_hypotheses,
                "n_global_discoveries": self.n_global_discoveries,
                "n_candidates": len(self.candidates),
            },
            "config": self.config.__dict__,
            "ranking": self.ranking(),
        }


def _research_pair(
    df: pd.DataFrame, rcfg: ResearchConfig
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return run_research(df, rcfg).to_dict(), None
    except Exception as exc:  # one bad pair must not sink the study
        return None, f"{type(exc).__name__}: {exc}"


def run_study(
    data: Mapping[str, pd.DataFrame],
    strategies: Sequence[str],
    cfg: StudyConfig | None = None,
    cost_for: Callable[[str], CostModel] | None = None,
    instrument_for: Callable[[str], tuple[bool, str]] | None = None,
    workers: int = 1,
) -> StudyReport:
    """Run every (symbol, strategy) pair, then apply study-wide BH-FDR.

    ``instrument_for(symbol) -> (tradable, currency)`` defaults to the Trading 212 universe;
    the Research Lab passes its own for crypto pairs. ``workers > 1`` runs the pairs in parallel
    processes; results (and therefore the global FDR) are identical to a sequential run.
    """
    cfg = cfg or StudyConfig()

    def _t212(symbol: str) -> tuple[bool, str]:
        inst = get_instrument(symbol)
        return inst.tradable_t212_eu, inst.currency

    instrument_for = instrument_for or _t212
    cost_for = cost_for or (lambda s: CostModel.trading212(instrument_for(s)[1]))
    pairs: list[PairResult] = []
    data_hashes: dict[str, str] = {}
    jobs: list[tuple[PairResult, pd.DataFrame, ResearchConfig]] = []

    for symbol, df in data.items():
        tradable, currency = instrument_for(symbol)
        for strategy in strategies:
            pair = PairResult(symbol, strategy, tradable, currency)
            pairs.append(pair)
            if len(df) < MIN_BARS:
                pair.error = f"only {len(df)} bars (< {MIN_BARS})"
                continue
            rcfg = ResearchConfig(
                symbol=symbol,
                timeframe=cfg.timeframe,
                strategy=strategy,
                catalog=cfg.catalog,
                oos_fraction=cfg.oos_fraction,
                walk_forward_windows=cfg.walk_forward_windows,
                fdr_q=cfg.fdr_q,
                min_trades=cfg.min_trades,
                monte_carlo_sims=cfg.monte_carlo_sims,
                seed=cfg.seed,
                costs=cost_for(symbol),
            )
            jobs.append((pair, df, rcfg))

    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            outcomes = list(
                pool.map(_research_pair, [d for _, d, _ in jobs], [c for *_, c in jobs])
            )
    else:
        outcomes = [_research_pair(d, c) for _, d, c in jobs]
    for (pair, _, _), (report, error) in zip(jobs, outcomes, strict=True):
        if error is not None:
            pair.error = error
            continue
        pair.report = report
        assert report is not None
        data_hashes[pair.symbol] = report["meta"]["data_hash"]

    # Study-wide FDR over every variant tested.
    offsets: list[tuple[PairResult, int]] = []
    all_p: list[float] = []
    for pair in pairs:
        if pair.report is None:
            continue
        offsets.append((pair, len(all_p)))
        all_p.extend(pair.report["multiple_testing"]["p_values"])
    rejected, adjusted = benjamini_hochberg(np.array(all_p), cfg.fdr_q)

    for pair, offset in offsets:
        assert pair.report is not None
        idx = offset + int(pair.report["multiple_testing"]["selected_index"])
        pair.survives_global_fdr = bool(rejected[idx])
        pair.global_adjusted_p = float(adjusted[idx])
        local = pair.report["verdict"]["decision"]
        if local == "CHALLENGER_CANDIDATE" and pair.survives_global_fdr:
            pair.decision = "CHALLENGER_CANDIDATE" if pair.tradable else "EVIDENCE_ONLY"
        else:
            pair.decision = "REJECTED"

    for pair in pairs:
        if pair.error is not None:
            pair.decision = "ERROR"

    return StudyReport(
        config=replace(cfg),
        pairs=pairs,
        n_hypotheses=len(all_p),
        n_global_discoveries=int(rejected.sum()),
        data_hashes=data_hashes,
    )
