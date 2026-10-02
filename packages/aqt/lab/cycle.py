"""One Research Lab cycle: history → hypotheses → validation → golden check → challengers.

1. For every timeframe, load the history (1-minute: last days of 1-second klines; 15 min and
   up: months of klines/bars) and add cross-sectional + calendar features (``augment``).
2. ``run_study`` per timeframe — the intraday catalog below one hour, the swing catalog from one
   hour up: in-sample sweep with BH-FDR, frozen out-of-sample, walk-forward, Monte Carlo,
   parameter stability — then ONE global FDR across every variant of every family on every
   symbol and timeframe. Only ``CHALLENGER_CANDIDATE`` pairs go on.
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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

from aqt.analyst.hypotheses import HypothesisStore
from aqt.backtest.costs import CostModel
from aqt.features.cross_section import augment
from aqt.features.engine import FeatureEngine
from aqt.lab.registry import RuleRecord, RuleRegistry, RuleStatus
from aqt.news.book import NewsBook
from aqt.news.items import NewsItem
from aqt.research.study import StudyConfig, apply_global_fdr, run_study
from aqt.strategies.dsl import StrategySpec
from aqt.strategies.intraday import INTRADAY_CATALOG
from aqt.strategies.swing import SWING_CATALOG, swing_families_for
from aqt.stream.dsl_strategy import DslStreamStrategy, ResearchBarBook, rule_id_for
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Event
from aqt.stream.history import TIMEFRAME_SECONDS, kline_events, resample_bars, resample_klines
from aqt.stream.session import UsEquitySession
from aqt.stream.stocks import bar_events, with_bvc
from aqt.stream.store import SQLiteStore

KlineLoader = Callable[[str, int, int], pd.DataFrame]
BarLoader = Callable[[str, int, int], pd.DataFrame]
IntervalLoader = Callable[[str, int, int, str], pd.DataFrame]
NewsLoader = Callable[[Sequence[str], int, int], list[NewsItem]]
_TIMEFRAMES = {k: float(v) for k, v in TIMEFRAME_SECONDS.items()}


@dataclass(frozen=True)
class LabConfig:
    symbols: tuple[str, ...]
    quote: str = "USDC"
    days: float = 7.0
    timeframe: str = "1min"
    timeframes: tuple[str, ...] = ()  # several timeframes in one cycle (default: ``timeframe``)
    intraday_days: float = 7.0  # 1-minute research uses at most this much (1-second klines)
    daily_days: float = 1825.0  # daily bars need years: 252-bar warm-up + enough trades per symbol
    news_days: float = 1095.0  # headline history for the news_* features (needs a news loader)
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
    swing_families: tuple[str, ...] = tuple(SWING_CATALOG)
    include_ai_hypotheses: bool = True  # test the AI Analyst's pending proposals in the cycle
    workers: int = field(default_factory=lambda: max(1, (os.cpu_count() or 2) - 1))

    @property
    def timeframe_s(self) -> float:
        return _TIMEFRAMES[self.timeframe]

    @property
    def all_timeframes(self) -> tuple[str, ...]:
        return self.timeframes or (self.timeframe,)

    def catalog_for(self, timeframe: str, news: bool = False) -> tuple[str, tuple[str, ...]]:
        """Swing catalog from one hour up (holds overnight), intraday catalog below. Daily-only,
        equity-only and news swing families are left out where they cannot be tested."""
        tf_s = _TIMEFRAMES[timeframe]
        if tf_s >= 3600:
            return "swing", swing_families_for(self.swing_families, tf_s, self.session, news)
        return "intraday", self.families

    def days_for(self, timeframe: str) -> float:
        """Crypto 1-minute research is built from 1-second klines: cap how much is downloaded.
        Daily bars get ``daily_days`` of history."""
        if _TIMEFRAMES[timeframe] >= 86_400:
            return self.daily_days
        crypto_minute = timeframe == "1min" and self.session == "24/7"
        return min(self.days, self.intraday_days) if crypto_minute else self.days

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

    def bars(
        self, symbol: str, start_ms: int, end_ms: int, timeframe: str = "1min"
    ) -> pd.DataFrame: ...

    def events(
        self, symbol: str, start_ms: int, end_ms: int, timeframe: str = "1min"
    ) -> Iterable[Event]: ...


@dataclass
class KlineData:
    """Crypto: 1-minute bars from 1-second klines (tick replay for the golden check); longer
    timeframes straight from Binance klines (quote path synthesised from the bars)."""

    loader: KlineLoader
    timeframe: str = "1min"
    spread_pct: float = 0.0001
    interval_loader: IntervalLoader | None = None
    _cache: dict[tuple[str, int, int], pd.DataFrame] = field(default_factory=dict)

    def _klines(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        key = (symbol, start_ms, end_ms)
        if key not in self._cache:
            self._cache = {key: self.loader(symbol, start_ms, end_ms)}  # keep one symbol only
        return self._cache[key]

    def _interval(self) -> IntervalLoader:
        if self.interval_loader is None:
            from aqt.stream.history import load_binance_klines

            return load_binance_klines
        return self.interval_loader

    def bars(
        self, symbol: str, start_ms: int, end_ms: int, timeframe: str | None = None
    ) -> pd.DataFrame:
        tf = timeframe or self.timeframe
        if tf != "1min":
            return self._interval()(symbol, start_ms, end_ms, tf)
        df = self._klines(symbol, start_ms, end_ms)
        return resample_klines(df, tf) if not df.empty else df

    def events(
        self, symbol: str, start_ms: int, end_ms: int, timeframe: str | None = None
    ) -> Iterable[Event]:
        tf = timeframe or self.timeframe
        if tf != "1min":
            bars = self.bars(symbol, start_ms, end_ms, tf)
            return bar_events(bars, symbol, self.spread_pct, _TIMEFRAMES[tf])
        df = self.loader(symbol, start_ms, end_ms)
        return kline_events(df, symbol, self.spread_pct)


@dataclass
class BarData:
    """Stocks: 1-minute bars (with BVC flow) → bars at any timeframe + a quote path inside the
    trading session."""

    loader: BarLoader
    spread_pct: float = 0.0002

    def bars(
        self, symbol: str, start_ms: int, end_ms: int, timeframe: str = "1min"
    ) -> pd.DataFrame:
        minute = self.loader(symbol, start_ms, end_ms)
        if timeframe == "1min" or minute.empty:
            return minute
        return with_bvc(
            resample_bars(minute[["open", "high", "low", "close", "volume"]], timeframe)
        )

    def events(
        self, symbol: str, start_ms: int, end_ms: int, timeframe: str = "1min"
    ) -> Iterable[Event]:
        bars = self.bars(symbol, start_ms, end_ms, timeframe)
        return bar_events(bars, symbol, self.spread_pct, _TIMEFRAMES[timeframe], UsEquitySession())


def golden_check(
    data: LabData,
    research_features: pd.DataFrame,
    spec: StrategySpec,
    symbol: str,
    oos_start: pd.Timestamp,
    end_ms: int,
    cfg: LabConfig,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Replay the out-of-sample period through the live engine with only this rule.

    ``research_features`` are the (augmented, causal) features research computed for the symbol.
    """
    timeframe = timeframe or cfg.timeframe
    tf = _TIMEFRAMES[timeframe]
    book = ResearchBarBook()
    book.preload(symbol, tf, research_features)
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
    for event in data.events(symbol, int(oos_start.timestamp() * 1000), end_ms, timeframe):
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
    news_loader: NewsLoader | None = None,
) -> CycleResult:
    """``loader`` is a 1-second kline loader (crypto) or any :class:`LabData` (e.g. stocks).
    With a ``news_loader`` (stocks + Alpaca keys) the news features and families are tested."""
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
        summary, promoted = _cycle(registry, cfg, data, start_ms, end_ms, run_id, news_loader)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        registry.finish_run(run_id, {}, status="error", error=error)
        return CycleResult(run_id, {}, [], error)
    registry.finish_run(run_id, summary)
    return CycleResult(run_id, summary, promoted)


def _load_news(
    cfg: LabConfig, end_ms: int, loader: NewsLoader | None
) -> tuple[NewsBook | None, dict[str, Any]]:
    """Headlines for the news features; a news outage only switches the news families off."""
    if loader is None:
        return None, {"enabled": False}
    start_ms = end_ms - int(cfg.news_days * 86_400_000)
    try:
        items = loader(cfg.symbols, start_ms, end_ms)
    except Exception as exc:
        return None, {"enabled": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    book = NewsBook(start_ms / 1000, end_ms / 1000)
    book.add(items)
    return book, {"enabled": True, "headlines": len(items), "days": cfg.news_days}


def _cycle(
    registry: RuleRegistry,
    cfg: LabConfig,
    data: LabData,
    start_ms: int,
    end_ms: int,
    run_id: int,
    news_loader: NewsLoader | None = None,
) -> tuple[dict[str, Any], list[str]]:
    costs = cfg.costs
    news, news_info = _load_news(cfg, end_ms, news_loader)
    hyp_store = HypothesisStore(registry.store) if cfg.include_ai_hypotheses else None
    tested_hyps: dict[str, int] = {}  # AI hypothesis name -> id
    studies: list[tuple[str, Any]] = []
    augmented: dict[str, dict[str, pd.DataFrame]] = {}
    n_bars: dict[str, int] = {}
    for tf in cfg.all_timeframes:
        tf_start = end_ms - int(cfg.days_for(tf) * 86_400_000)
        raw = {}
        for sym in cfg.symbols:
            b = data.bars(sym, tf_start, end_ms, tf)
            if not b.empty:
                raw[sym] = b
                n_bars[f"{sym}@{tf}"] = len(b)
        if not raw:
            continue
        augmented[tf] = augment(raw, _TIMEFRAMES[tf], cfg.session, news)
        catalog, families = cfg.catalog_for(tf, news=news is not None)
        ai_specs: dict[str, tuple[StrategySpec, dict[str, list[float | int]]]] = {}
        pending = hyp_store.pending(tf) if hyp_store is not None else []
        columns: set[str] = set()
        if pending:
            columns = set(FeatureEngine().compute(next(iter(augmented[tf].values()))).columns)
        for h in pending:
            spec = h["spec_obj"]
            used = spec.entry.features_used() | (
                spec.exit.exit_signal.features_used() if spec.exit.exit_signal else set()
            )
            if not used <= columns:
                continue  # e.g. news features without a news source: stays pending
            ai_specs[h["name"]] = (spec, h["grid_obj"])
            tested_hyps[h["name"]] = h["id"]
        study = run_study(
            augmented[tf],
            [*families, *ai_specs],
            StudyConfig(
                timeframe=tf,
                fdr_q=cfg.fdr_q,
                oos_fraction=cfg.oos_fraction,
                walk_forward_windows=cfg.walk_forward_windows,
                monte_carlo_sims=cfg.monte_carlo_sims,
                min_trades=cfg.min_trades,
                name=f"lab-{run_id}-{tf}",
                catalog=catalog,
            ),
            cost_for=lambda _s: costs,
            instrument_for=lambda _s: (True, cfg.quote),
            workers=cfg.workers,
            specs=ai_specs,
        )
        studies.append((tf, study))

    # One FDR over every hypothesis of every timeframe: testing more is paid for with stricter bars.
    tagged = [(tf, pair) for tf, study in studies for pair in study.pairs]
    n_hypotheses, n_discoveries = apply_global_fdr([p for _, p in tagged], cfg.fdr_q)
    candidates = [(tf, p) for tf, p in tagged if p.decision == "CHALLENGER_CANDIDATE"]

    failed: Counter[str] = Counter()
    best: list[dict[str, Any]] = []
    per_tf: dict[str, int] = {}
    for tf, pair in tagged:
        if pair.report is None:
            continue
        per_tf[tf] = per_tf.get(tf, 0) + len(pair.report["multiple_testing"]["p_values"])
        failed.update(pair.report["verdict"]["failed"])
        best.append({**pair.summary(), "timeframe": tf})
    best.sort(key=lambda r: r.get("oos_ev") or -np.inf, reverse=True)

    golden_results: list[dict[str, Any]] = []
    new_candidates: list[RuleRecord] = []
    rule_of: dict[int, str] = {}  # id(pair) -> rule id that passed the golden check
    for tf, pair in candidates:
        assert pair.report is not None
        tf_s = _TIMEFRAMES[tf]
        spec = StrategySpec.model_validate(pair.report["selected_strategy"]["spec"])
        oos_start = pd.Timestamp(pair.report["out_of_sample"]["period"][0])
        features = FeatureEngine().compute(augmented[tf][pair.symbol])
        golden = golden_check(data, features, spec, pair.symbol, oos_start, end_ms, cfg, tf)
        rid = rule_id_for(spec, pair.symbol, tf_s)
        research = {
            k: pair.summary().get(k)
            for k in ("oos_trades", "oos_ev", "oos_p_value", "wf_oos_ev", "edge_score",
                      "global_adjusted_p", "net_ev_full")
        }  # fmt: skip
        research["timeframe"] = tf
        golden_results.append({"rule_id": rid, "timeframe": tf, **golden})
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
                timeframe_s=tf_s,
                spec=spec,
                research_run=run_id,
                metrics={"research": research, "golden": golden},
                meta={"timeframe": tf, "overnight": tf_s >= 3600},
            ),
            reason=f"research run #{run_id}",
        )
        new_candidates.append(rule)
        rule_of[id(pair)] = rid

    promoted = _promote(registry, new_candidates, cfg.max_active)
    if hyp_store is not None:
        _record_ai_verdicts(hyp_store, tested_hyps, tagged, rule_of, promoted, run_id)
    top_fail = ", ".join(f"{k} ({v})" for k, v in failed.most_common(3)) or "-"
    symbols = sorted({sym for tf in augmented for sym in augmented[tf]})
    summary = {
        "symbols": symbols,
        "timeframes": list(augmented),
        "n_bars": n_bars,
        "hypotheses_by_timeframe": per_tf,
        "families": list(cfg.families) + list(cfg.swing_families),
        "news": news_info,
        "n_pairs": len(tagged),
        "n_hypotheses": n_hypotheses,
        "n_global_discoveries": n_discoveries,
        "n_candidates": len(candidates),
        "golden": golden_results,
        "promoted": promoted,
        "failed_checks": dict(failed.most_common()),
        "top_pairs": best[:10],
    }
    tfs = ", ".join(augmented) or "-"
    registry.add_lesson(
        "research",
        f"Ciclo #{run_id}: {n_hypotheses} hipótesis en {len(symbols)} símbolos y timeframes "
        f"{tfs}; {len(candidates)} candidatas, {len(promoted)} promovidas a challenger. "
        f"Fallos más comunes: {top_fail}.",
        None,
        {"n_hypotheses": n_hypotheses, "promoted": promoted},
    )
    return summary, promoted


def _record_ai_verdicts(
    hyp_store: HypothesisStore,
    tested: dict[str, int],
    tagged: list[tuple[str, Any]],
    rule_of: dict[int, str],
    promoted: list[str],
    run_id: int,
) -> None:
    """Write back what the lab concluded about each AI hypothesis (the analyst reads it next)."""
    for name, hid in tested.items():
        pairs = [p for _, p in tagged if p.strategy == name and p.report is not None]
        rules = [rule_of[id(p)] for p in pairs if id(p) in rule_of]
        best = max(pairs, key=lambda p: p.summary().get("oos_ev") or -np.inf, default=None)
        failed: Counter[str] = Counter()
        for p in pairs:
            failed.update(p.report["verdict"]["failed"])
        verdict = {
            "symbols_tested": len(pairs),
            "best_symbol": best.symbol if best else None,
            "best_oos_ev": best.summary().get("oos_ev") if best else None,
            "best_oos_trades": best.summary().get("oos_trades") if best else None,
            "candidates": sum(p.decision == "CHALLENGER_CANDIDATE" for p in pairs),
            "rules": rules,
            "failed_checks": dict(failed.most_common(4)),
        }
        status = "promoted" if any(r in promoted for r in rules) else "rejected"
        hyp_store.mark(hid, status, verdict, run_id)


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
