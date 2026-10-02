"""Learn filters from each live strategy's wins and losses and register them as challengers."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from aqt.lab.meta import MetaConfig, save_model, train_meta_filter
from aqt.lab.registry import RuleRecord, RuleRegistry, RuleStatus
from aqt.stream.store import SQLiteStore


def model_dir_for(store: SQLiteStore) -> Path:
    if store.path == ":memory:":
        return Path(tempfile.gettempdir()) / "aqt-models"
    return Path(store.path).parent / "models"


def learn_meta_filters(
    store: SQLiteStore,
    run_id: str,
    registry: RuleRegistry,
    strategy_ids: Iterable[str],
    cfg: MetaConfig | None = None,
    max_active: int = 10,
    model_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Train a filter per strategy whose shadow history grew enough since the last attempt.

    A strategy is retried only after its trade count grew by 50 % (no re-mining the same data);
    each attempt — accepted or not — leaves a lesson.
    """
    cfg = cfg or MetaConfig()
    model_dir = model_dir or model_dir_for(store)
    has_child = {
        r.meta.get("base") for r in registry.rules() if r.is_meta and r.status != RuleStatus.RETIRED
    }
    out: list[dict[str, Any]] = []
    for sid in strategy_ids:
        if "~meta" in sid or sid in has_child:
            continue
        trades = store.strategy_trades(run_id, sid)
        n = len(trades)
        key = f"meta_last_n:{run_id}:{sid}"
        last_n = int(store.get_setting(key) or 0)
        if n < cfg.min_trades or n < last_n * 1.5:
            continue
        store.set_setting(key, str(n))
        res = train_meta_filter([c for _, c in trades], [r for r, _ in trades], cfg)
        top = ", ".join(list(res.importance)[:3]) or "-"
        if res.accepted and len(registry.active()) < max_active:
            path, sha = save_model(res.model, model_dir, re.sub(r"[^A-Za-z0-9_.-]", "_", sid))
            base = registry.get(sid)
            rec = RuleRecord(
                rule_id=f"{sid}~meta-{sha[:6]}",
                symbol=base.symbol if base else "*",
                timeframe_s=base.timeframe_s if base else 0.0,
                spec=base.spec if base else None,
                metrics={"meta": res.summary()},
                meta={
                    "kind": "meta",
                    "base": sid,
                    "model_path": path,
                    "model_sha": sha,
                    "threshold": res.threshold,
                    "features": res.features,
                },
                parent_id=sid,
            )
            registry.upsert(rec, reason="meta-learning on its parent's trades")
            registry.set_status(
                rec.rule_id,
                RuleStatus.CHALLENGER,
                "filter improves the parent out of fold; must now prove itself in shadow",
            )
            text = (
                f"{sid}: de {n} operaciones (EV {res.ev_all:+.3%}) aprendió a quedarse con el "
                f"{res.kept_fraction:.0%} de las señales (EV {res.ev_kept:+.3%} fuera de muestra, "
                f"p={res.p_value:.3f}). Pesan más: {top}. Nueva versión a prueba en sombra."
            )
            out.append({"strategy_id": sid, "accepted": True, "rule_id": rec.rule_id})
        else:
            why = res.reason if res.accepted is False else "sin hueco para más reglas vivas"
            text = (
                f"{sid}: analizadas {n} operaciones (EV {res.ev_all:+.3%}); no hay un patrón "
                f"fiable que separe ganadoras de perdedoras ({why}). "
                f"Variables más informativas: {top}."
            )
            out.append({"strategy_id": sid, "accepted": False, "reason": why})
        registry.add_lesson("learning", text, sid, res.summary())
    return out
