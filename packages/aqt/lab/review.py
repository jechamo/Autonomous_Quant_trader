"""Review live rules against their *forward* results — learning from good and bad outcomes.

Research says a rule worked in the past; only the forward shadow book says whether it still
works. For every active rule:

* **promote** a challenger to champion when its forward evidence clears the same thresholds the
  Risk Engine uses (from then on its signals can trade paper);
* **demote** a champion back to challenger when its evidence weakens;
* **retire** a rule once it has enough forward trades and the posterior probability that its EV
  is positive drops below ``retire_prob`` — or when it stopped producing signals at all.

Every transition writes a lesson comparing what research promised with what actually happened.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from aqt.lab.registry import RuleRegistry, RuleStatus
from aqt.risk.profile import RiskProfile
from aqt.statistics.edge import compute_edge_score
from aqt.stream.evidence import EvidenceRow
from aqt.stream.store import SQLiteStore


@dataclass(frozen=True)
class ReviewConfig:
    min_trades_retire: int = 30
    retire_prob: float = 0.2
    stale_days: float = 3.0


def forward_metrics(returns: list[float]) -> dict[str, Any]:
    r = np.asarray(returns, dtype=float)
    es = compute_edge_score(r)
    return {
        "n_trades": int(r.size),
        "mean_net_return": float(r.mean()) if r.size else 0.0,
        "win_rate": float((r > 0).mean()) if r.size else 0.0,
        "edge_score": es.score,
        "confidence": es.confidence,
        "prob_positive_ev": es.prob_positive_ev,
    }


def review_rules(
    store: SQLiteStore,
    live_run_id: str,
    profile: RiskProfile,
    evidence: Mapping[str, EvidenceRow] | None = None,
    cfg: ReviewConfig | None = None,
    clock: Callable[[], float] = time.time,
) -> list[dict[str, Any]]:
    """Apply promotions/demotions/retirements; returns the changes made.

    ``evidence`` is the live engine's FDR-adjusted table when available (what the Risk Engine
    really sees); otherwise the unadjusted forward statistics are used.
    """
    cfg = cfg or ReviewConfig()
    registry = RuleRegistry(store, clock)
    now = clock()
    changes: list[dict[str, Any]] = []

    def change(rule_id: str, status: RuleStatus, reason: str, fwd: dict[str, Any]) -> None:
        registry.set_status(rule_id, status, reason, {"forward": fwd})
        changes.append({"rule_id": rule_id, "status": str(status), "reason": reason})

    for rule in registry.active():
        fwd = forward_metrics(store.strategy_returns(live_run_id, rule.rule_id))
        row = (evidence or {}).get(rule.rule_id)
        edge = row.edge_score if row is not None else fwd["edge_score"]
        conf = row.confidence if row is not None else fwd["confidence"]
        promised = rule.metrics.get("research", {}).get("oos_ev")
        promised_txt = f"{promised:+.3%}" if isinstance(promised, float) else "?"
        n = fwd["n_trades"]

        if n >= cfg.min_trades_retire and fwd["prob_positive_ev"] < cfg.retire_prob:
            reason = (
                f"retirada: {n} operaciones forward con EV {fwd['mean_net_return']:+.3%} "
                f"(research prometía {promised_txt}); P(EV>0)={fwd['prob_positive_ev']:.2f}"
            )
            change(rule.rule_id, RuleStatus.RETIRED, reason, fwd)
            registry.add_lesson("retirement", f"{rule.rule_id} — {reason}", rule.rule_id, fwd)
        elif n == 0 and now - rule.updated_at > cfg.stale_days * 86_400:
            reason = (
                f"retirada: sin señales en {cfg.stale_days:g} días (el mercado ya no la activa)"
            )
            change(rule.rule_id, RuleStatus.RETIRED, reason, fwd)
            registry.add_lesson("retirement", f"{rule.rule_id} — {reason}", rule.rule_id, fwd)
        elif (
            rule.status == RuleStatus.CHALLENGER
            and edge >= profile.min_edge_score
            and conf >= profile.min_confidence
        ):
            reason = (
                f"campeona: evidencia forward suficiente ({n} operaciones, EV "
                f"{fwd['mean_net_return']:+.3%}, edge {edge:.0f}); ya puede operar en paper"
            )
            change(rule.rule_id, RuleStatus.CHAMPION, reason, fwd)
            registry.add_lesson("promotion", f"{rule.rule_id} — {reason}", rule.rule_id, fwd)
        elif rule.status == RuleStatus.CHAMPION and (
            edge < profile.min_edge_score or conf < profile.min_confidence
        ):
            reason = f"vuelve a challenger: la evidencia forward se debilitó (edge {edge:.0f})"
            change(rule.rule_id, RuleStatus.CHALLENGER, reason, fwd)
    return changes
