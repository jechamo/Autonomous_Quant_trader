"""One Research Lab cycle: history → hypotheses → validation → golden check → challengers.

1. Load the last ``days`` of Binance 1-second klines per symbol and resample to research bars.
2. ``run_study`` over the intraday catalog: in-sample sweep with BH-FDR, frozen out-of-sample,
   walk-forward, Monte Carlo, parameter stability and a study-wide FDR across every variant of
   every family on every symbol. Only ``CHALLENGER_CANDIDATE`` pairs go on.
3. Golden check: the selected rule runs inside the real ``StreamingEngine`` on the out-of-sample
   ticks (latency, bid/ask, fees). The vectorised backtest and the live engine must agree that the
   rule makes money after costs; otherwise it is rejected and a lesson is written.
4. Survivors are registered and promoted to *challenger* (up to ``max_active`` live rules), which
   puts them in the live shadow book where they must earn forward evidence from zero.

Nothing here sends orders or changes risk limits: the lab only proposes rules.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

from aqt.backtest.costs import CostModel
from aqt.features.engine import FeatureEngine
from aqt.lab.registry import RuleRecord, RuleRegistry, RuleStatus
from aqt.research.study import StudyConfig, run_study
from aqt.strategies.dsl import StrategySpec
from aqt.strategies.intraday import INTRADAY_CATALOG
from aqt.stream.dsl_strategy import DslStreamStrategy, ResearchBarBook, rule_id_for
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Event
from aqt.stream.history import kline_events, resample_klines
from aqt.stream.stocks import bar_events
from aqt.stream.store import SQLiteStore

KlineLoader = Callable[[str, int, int], pd.DataFrame]
BarLoader = Callable[[str, int, int], pd.DataFrame]
_TIMEFRAMES = {"1min": 60.0, "5min": 300.0, "15min": 900.0}


@dataclass(frozen=True)
class LabConfig:
    symbols: tuple[str, ...]
    quote: str = "USDC"
    days: float = 7.0
    timeframe: str = "1min"
    fee_pct: float = 0.001
    spread_pct: float = 0.0001
    slippage_pct: float = 0.0005
    latency_s: float = 0.25
    fdr_q: float = 0.05
    min_trades: int = 30
    oos_fraction: float = 0.3
    walk_forward_windows: int = 4
    monte_carlo_sims: int = 1000
    max_active: int = 10
    golden_min_trades: int = 5
    session: str = "24/7"  # "us_equity" for stocks (no entries near the close, flat overnight)
    families: tuple[str, ...] = tuple(INTRADAY_CATALOG)
    workers: int = field(default_factory=lambda: max(1, (os.cpu_count() or 2) - 1))

    @property
    def timeframe_s(self) -> float:
        return _TIMEFRAMES[self.timeframe]

    @property
    def costs(self) -> CostModel:
        return CostModel(
            fee_pct=self.fee_pct,
            spread_pct=self.spread_pct,
            slippage_pct=self.slippage_pct,
            fx_pct=0.0,
        )


@dataclass
class CycleResult:
    run_id: int
    summary: dict[str, Any]
    promoted: list[str]
    error: str = ""


class LabData(Protocol):
    """Where a research cycle gets its bars (to study) and its ticks (for the golden check)."""

    def bars(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame: ...

    def events(self, symbol: str, start_ms: int, end_ms: int) -> Iterable[Event]: ...


@dataclass
class KlineData:
    """Crypto: Binance 1-second klines → research bars + tick replay."""

    loader: KlineLoader
    timeframe: str = "1min"
    spread_pct: float = 0.0001
    _cache: dict[tuple[str, int, int], pd.DataFrame] = field(default_factory=dict)

    def _klines(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        key = (symbol, start_ms, end_ms)
        if key not in self._cache:
            self._cache = {key: self.loader(symbol, start_ms, end_ms)}  # keep one symbol only
        return self._cache[key]

    def bars(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        df = self._klines(symbol, start_ms, end_ms)
        return resample_klines(df, self.timeframe) if not df.empty else df

    def events(self, symbol: str, start_ms: int, end_ms: int) -> Iterable[Event]:
        df = self.loader(symbol, start_ms, end_ms)
        return kline_events(df, symbol, self.spread_pct)


@dataclass
class BarData:
    """Stocks: 1-minute bars (with BVC flow) → research bars + a conservative quote path."""

    loader: BarLoader
    spread_pct: float = 0.0002

    def bars(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        return self.loader(symbol, start_ms, end_ms)

    def events(self, symbol: str, start_ms: int, end_ms: int) -> Iterable[Event]:
        return bar_events(self.loader(symbol, start_ms, end_ms), symbol, self.spread_pct)


def golden_check(
    data: LabData,
    research_bars: pd.DataFrame,
    spec: StrategySpec,
    symbol: str,
    oos_start: pd.Timestamp,
    end_ms: int,
    cfg: LabConfig,
) -> dict[str, Any]:
    """Replay the out-of-sample ticks through the live engine with only this rule."""
    tf = cfg.timeframe_s
    book = ResearchBarBook()
    book.preload(symbol, tf, FeatureEngine().compute(research_bars))
    strat = DslStreamStrategy(spec=spec, symbol=symbol, timeframe_s=tf, book=book)
    eng = StreamingEngine(
        EngineConfig(
            symbols=(symbol,),
            bar_seconds=5.0,
            fee_pct=cfg.fee_pct,
            expected_slippage_pct=cfg.slippage_pct,
            latency_s=cfg.latency_s,
            run_id="golden",
            session=cfg.session,
        ),
        strategies=[strat],
    )
    for event in data.events(symbol, int(oos_start.timestamp() * 1000), end_ms):
        eng.on_event(event)
    eng.shutdown()
    r = np.asarray(eng.evidence.returns(strat.strategy_id), dtype=float)
    mean = float(r.mean()) if r.size else 0.0
    return {
        "n_trades": int(r.size),
        "mean_net_return": mean,
        "win_rate": float((r > 0).mean()) if r.size else 0.0,
        "passed": bool(r.size >= cfg.golden_min_trades and mean > 0),
    }


def run_research_cycle(
    store: SQLiteStore,
    cfg: LabConfig,
    loader: KlineLoader | LabData,
    end_ms: int | None = None,
    clock: Callable[[], float] = time.time,
) -> CycleResult:
    """``loader`` is a 1-second kline loader (crypto) or any :class:`LabData` (e.g. stocks)."""
    data: LabData = (
        loader
        if isinstance(loader, KlineData | BarData)
        else KlineData(loader, cfg.timeframe, cfg.spread_pct)  # type: ignore[arg-type]
    )
    registry = RuleRegistry(store, clock)
    end_ms = end_ms if end_ms is not None else int(clock() * 1000) // 1000 * 1000
    start_ms = end_ms - int(cfg.days * 86_400_000)
    run_id = registry.start_run(
        {**asdict(cfg), "start_ms": start_ms, "end_ms": end_ms, "symbols": list(cfg.symbols)}
    )
    try:
        summary, promoted = _cycle(registry, cfg, data, start_ms, end_ms, run_id)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        registry.finish_run(run_id, {}, status="error", error=error)
        return CycleResult(run_id, {}, [], error)
    registry.finish_run(run_id, summary)
    return CycleResult(run_id, summary, promoted)


def _cycle(
    registry: RuleRegistry,
    cfg: LabConfig,
    data: LabData,
    start_ms: int,
    end_ms: int,
    run_id: int,
) -> tuple[dict[str, Any], list[str]]:
    bars: dict[str, pd.DataFrame] = {}
    for sym in cfg.symbols:
        b = data.bars(sym, start_ms, end_ms)
        if not b.empty:
            bars[sym] = b

    costs = cfg.costs
    study = run_study(
        bars,
        list(cfg.families),
        StudyConfig(
            timeframe=cfg.timeframe,
            fdr_q=cfg.fdr_q,
            oos_fraction=cfg.oos_fraction,
            walk_forward_windows=cfg.walk_forward_windows,
            monte_carlo_sims=cfg.monte_carlo_sims,
            min_trades=cfg.min_trades,
            name=f"lab-{run_id}",
            catalog="intraday",
        ),
        cost_for=lambda _s: costs,
        instrument_for=lambda _s: (True, cfg.quote),
        workers=cfg.workers,
    )

    failed: Counter[str] = Counter()
    best: list[dict[str, Any]] = []
    for pair in study.pairs:
        if pair.report is None:
            continue
        failed.update(pair.report["verdict"]["failed"])
        best.append(pair.summary())
    best.sort(key=lambda r: r.get("oos_ev") or -np.inf, reverse=True)

    golden_results: list[dict[str, Any]] = []
    new_candidates: list[RuleRecord] = []
    for pair in study.candidates:
        assert pair.report is not None
        spec = StrategySpec.model_validate(pair.report["selected_strategy"]["spec"])
        oos_start = pd.Timestamp(pair.report["out_of_sample"]["period"][0])
        golden = golden_check(data, bars[pair.symbol], spec, pair.symbol, oos_start, end_ms, cfg)
        rid = rule_id_for(spec, pair.symbol)
        research = {
            k: pair.summary().get(k)
            for k in ("oos_trades", "oos_ev", "oos_p_value", "wf_oos_ev", "edge_score",
                      "global_adjusted_p", "net_ev_full")
        }  # fmt: skip
        golden_results.append({"rule_id": rid, **golden})
        if not golden["passed"]:
            registry.add_lesson(
                "golden_reject",
                f"{rid}: superó la estadística (EV OOS {research['oos_ev']:+.3%}) pero en el motor "
                f"real dio {golden['mean_net_return']:+.3%} en {golden['n_trades']} operaciones; "
                "descartada (la ejecución real se come la ventaja).",
                rid,
                {"research": research, "golden": golden},
            )
            continue
        rule = registry.upsert(
            RuleRecord(
                rule_id=rid,
                symbol=pair.symbol,
                timeframe_s=cfg.timeframe_s,
                spec=spec,
                research_run=run_id,
                metrics={"research": research, "golden": golden},
            ),
            reason=f"research run #{run_id}",
        )
        new_candidates.append(rule)

    promoted = _promote(registry, new_candidates, cfg.max_active)
    top_fail = ", ".join(f"{k} ({v})" for k, v in failed.most_common(3)) or "—"
    summary = {
        "symbols": sorted(bars),
        "n_bars": {s: len(b) for s, b in bars.items()},
        "families": list(cfg.families),
        "n_pairs": len(study.pairs),
        "n_hypotheses": study.n_hypotheses,
        "n_global_discoveries": study.n_global_discoveries,
        "n_candidates": len(study.candidates),
        "golden": golden_results,
        "promoted": promoted,
        "failed_checks": dict(failed.most_common()),
        "top_pairs": best[:10],
    }
    registry.add_lesson(
        "research",
        f"Ciclo #{run_id}: {study.n_hypotheses} hipótesis en {len(bars)} símbolos; "
        f"{len(study.candidates)} candidatas, {len(promoted)} promovidas a challenger. "
        f"Fallos más comunes: {top_fail}.",
        None,
        {"n_hypotheses": study.n_hypotheses, "promoted": promoted},
    )
    return summary, promoted


def _promote(registry: RuleRegistry, candidates: list[RuleRecord], max_active: int) -> list[str]:
    """Fill free live slots with the best new candidates (by research edge score)."""
    slots = max_active - len(registry.active())
    ranked = sorted(
        (c for c in candidates if c.status == RuleStatus.CANDIDATE),
        key=lambda c: c.metrics.get("research", {}).get("edge_score") or 0.0,
        reverse=True,
    )
    promoted = []
    for rule in ranked[: max(slots, 0)]:
        registry.set_status(
            rule.rule_id,
            RuleStatus.CHALLENGER,
            "validated by research + golden check; must now earn forward evidence in shadow",
        )
        promoted.append(rule.rule_id)
    return promoted
