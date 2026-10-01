"""Multi-symbol × multi-strategy study with *global* multiple-testing control.

Every parameter variant of every strategy on every symbol is one hypothesis. Benjamini–Hochberg
is applied across all of them: testing thousands of combinations makes some look excellent by
pure chance, so a pair can only become a Challenger candidate if its selected variant also
survives the study-wide FDR.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
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


def run_study(
    data: Mapping[str, pd.DataFrame],
    strategies: Sequence[str],
    cfg: StudyConfig | None = None,
    cost_for: Callable[[str], CostModel] | None = None,
) -> StudyReport:
    """Run every (symbol, strategy) pair, then apply study-wide BH-FDR."""
    cfg = cfg or StudyConfig()
    cost_for = cost_for or (lambda s: CostModel.trading212(get_instrument(s).currency))
    pairs: list[PairResult] = []
    data_hashes: dict[str, str] = {}

    for symbol, df in data.items():
        inst = get_instrument(symbol)
        for strategy in strategies:
            pair = PairResult(symbol, strategy, inst.tradable_t212_eu, inst.currency)
            pairs.append(pair)
            if len(df) < MIN_BARS:
                pair.error = f"only {len(df)} bars (< {MIN_BARS})"
                continue
            rcfg = ResearchConfig(
                symbol=symbol,
                timeframe=cfg.timeframe,
                strategy=strategy,
                oos_fraction=cfg.oos_fraction,
                walk_forward_windows=cfg.walk_forward_windows,
                fdr_q=cfg.fdr_q,
                min_trades=cfg.min_trades,
                monte_carlo_sims=cfg.monte_carlo_sims,
                seed=cfg.seed,
                costs=cost_for(symbol),
            )
            try:
                pair.report = run_research(df, rcfg).to_dict()
            except Exception as exc:  # one bad pair must not sink the study
                pair.error = f"{type(exc).__name__}: {exc}"
                continue
            data_hashes[symbol] = pair.report["meta"]["data_hash"]

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
