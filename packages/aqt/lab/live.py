"""Turn the registry's active rules into engine strategies (and keep them in sync)."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from aqt.lab.meta import MetaFilteredStrategy, load_model
from aqt.lab.registry import RuleRecord, RuleRegistry
from aqt.stream.dsl_strategy import DslStreamStrategy, PanelDslStrategy, ResearchBarBook
from aqt.stream.engine import StreamingEngine
from aqt.stream.strategies import StreamStrategy, default_stream_strategies

log = logging.getLogger(__name__)


def _dsl(
    r: RuleRecord,
    strategy_id: str,
    book: ResearchBarBook,
    bar_seconds: float,
    universe: tuple[str, ...] = (),
) -> StreamStrategy:
    assert r.spec is not None
    if r.symbol == "*":  # pooled rule: one strategy over the whole universe
        return PanelDslStrategy(
            spec=r.spec,
            symbols=universe,
            strategy_id=strategy_id,
            timeframe_s=r.timeframe_s,
            engine_bar_s=bar_seconds,
            book=book,
            description=f"[{r.status}] {r.spec.description or r.spec.name} (todos los valores)",
        )
    return DslStreamStrategy(
        spec=r.spec,
        symbol=r.symbol,
        strategy_id=strategy_id,
        timeframe_s=r.timeframe_s,
        engine_bar_s=bar_seconds,
        book=book,
        description=f"[{r.status}] {r.spec.description or r.spec.name}",
    )


def rule_strategies(
    rules: Iterable[RuleRecord], symbols: Iterable[str], book: ResearchBarBook, bar_seconds: float
) -> list[StreamStrategy]:
    """One live strategy per active rule whose symbol is in the engine's universe.

    Meta rules wrap a *fresh* instance of their parent (DSL rule or baseline strategy) with the
    learned filter, so parent and filtered version keep independent state and evidence.
    """
    ordered = tuple(dict.fromkeys(symbols))
    universe = set(ordered)
    baseline = {s.strategy_id for s in default_stream_strategies(bar_seconds)}
    out: list[StreamStrategy] = []
    for r in rules:
        if r.symbol != "*" and r.symbol not in universe:
            continue
        if not r.is_meta:
            out.append(_dsl(r, r.rule_id, book, bar_seconds, ordered))
            continue
        base_id = str(r.meta["base"])
        if r.spec is not None:
            inner = _dsl(r, base_id, book, bar_seconds, ordered)
        elif base_id in baseline:
            inner = next(
                s for s in default_stream_strategies(bar_seconds) if s.strategy_id == base_id
            )
        else:
            continue
        try:
            model = load_model(r.meta["model_path"], r.meta["model_sha"])
        except (OSError, ValueError) as exc:
            log.warning("skipping %s: %s", r.rule_id, exc)
            continue
        out.append(
            MetaFilteredStrategy(
                inner=inner,
                model=model,
                feature_names=list(r.meta["features"]),
                threshold=float(r.meta["threshold"]),
                strategy_id=r.rule_id,
            )
        )
    return out


def sync_engine_rules(
    engine: StreamingEngine,
    registry: RuleRegistry,
    book: ResearchBarBook,
    baseline: bool = True,
) -> dict[str, list[str]]:
    """Make the engine run exactly: baseline strategies + the registry's active rules."""
    base = default_stream_strategies(engine.cfg.bar_seconds) if baseline else []
    rules = rule_strategies(registry.active(), engine.symbols, book, engine.cfg.bar_seconds)
    return engine.set_strategies([*base, *rules])
