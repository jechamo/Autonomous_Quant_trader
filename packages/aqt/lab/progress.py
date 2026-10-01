"""How far the system has learned, as numbers a progress bar can show (read-only).

- **funnel**: every hypothesis the Research Lab has examined and how many survived each stage;
- **rules**: each live rule's way from challenger to champion (forward evidence vs the
  thresholds the Risk Engine uses);
- **ml**: each strategy's way to a meta-learning attempt (shadow trades with context vs what the
  trainer needs) and what the last attempt concluded;
- **ai**: the AI Analyst's proposals and the lab's verdicts;
- **feed**: the latest things that happened (research cycles, rule changes, lessons, AI ideas,
  shadow and paper trades), newest first.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from aqt.analyst.hypotheses import HypothesisStore
from aqt.lab.meta import MetaConfig
from aqt.lab.registry import RuleRegistry, RuleStatus
from aqt.lab.review import forward_metrics
from aqt.stream.evidence import EvidenceRow
from aqt.stream.store import SQLiteStore

STATUS_ES = {
    "candidate": "candidata",
    "challenger": "challenger",
    "champion": "champion",
    "retired": "retirada",
}


def _clamp(x: float) -> float:
    return 0.0 if math.isnan(x) else max(0.0, min(1.0, x))


def funnel(store: SQLiteStore) -> dict[str, Any]:
    runs = store.query(
        "SELECT id, finished_at, summary FROM research_runs WHERE status='done' ORDER BY id"
    )
    sums = {"hyp": 0, "fdr": 0, "cand": 0, "golden": 0}
    for r in runs:
        s = json.loads(r["summary"] or "{}")
        sums["hyp"] += int(s.get("n_hypotheses") or 0)
        sums["fdr"] += int(s.get("n_global_discoveries") or 0)
        sums["cand"] += int(s.get("n_candidates") or 0)
        sums["golden"] += sum(bool(g.get("passed")) for g in s.get("golden") or [])
    ever = {
        r["to_status"]: r["n"]
        for r in store.query(
            "SELECT to_status, COUNT(DISTINCT rule_id) n FROM rule_events GROUP BY to_status"
        )
    }
    stages = [
        ("Hipótesis examinadas", sums["hyp"]),
        ("Pasan el filtro estadístico global", sums["fdr"]),
        ("Candidatas (fuera de muestra, walk-forward, Monte Carlo)", sums["cand"]),
        ("Superan la prueba en el motor real", sums["golden"]),
        ("Challengers (prueba en vivo, en sombra)", ever.get("challenger", 0)),
        ("Champions (operan en paper)", ever.get("champion", 0)),
    ]
    return {
        "cycles": len(runs),
        "last_cycle_at": runs[-1]["finished_at"] if runs else None,
        "stages": [{"label": k, "n": n} for k, n in stages],
    }


def rule_progress(
    store: SQLiteStore,
    registry: RuleRegistry,
    run_id: str,
    evidence: Mapping[str, EvidenceRow],
    min_edge: float,
    min_conf: float,
) -> list[dict[str, Any]]:
    out = []
    for rule in registry.active():
        row = evidence.get(rule.rule_id)
        fwd = forward_metrics(store.strategy_returns(run_id, rule.rule_id))
        edge = row.edge_score if row is not None else fwd["edge_score"]
        conf = row.confidence if row is not None else fwd["confidence"]
        done = rule.status == RuleStatus.CHAMPION
        out.append(
            {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "symbol": rule.symbol,
                "status": str(rule.status),
                "n_trades": fwd["n_trades"],
                "edge_score": edge,
                "confidence": conf,
                "progress": 1.0 if done else _clamp(min(edge / min_edge, conf / min_conf)),
                "goal": f"edge ≥ {min_edge:.0f} y confianza ≥ {min_conf:.0%}",
            }
        )
    return sorted(out, key=lambda r: -r["progress"])


def ml_progress(
    store: SQLiteStore,
    registry: RuleRegistry,
    run_id: str,
    strategy_ids: Iterable[str],
    cfg: MetaConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or MetaConfig()
    counts = {
        r["strategy_id"]: r["n"]
        for r in store.query(
            "SELECT strategy_id, COUNT(*) n FROM round_trips WHERE run_id=? AND book='shadow' "
            "AND context IS NOT NULL GROUP BY strategy_id",
            (run_id,),
        )
    }
    children = {
        r.meta.get("base"): r
        for r in registry.rules()
        if r.is_meta and r.status != RuleStatus.RETIRED
    }
    last_lesson = {
        r["rule_id"]: r["text"]
        for r in store.query("SELECT rule_id, text FROM lessons WHERE kind='learning' ORDER BY id")
    }
    rows = []
    for sid in strategy_ids:
        if "~meta" in sid:
            continue
        n = int(counts.get(sid, 0))
        last_n = int(store.get_setting(f"meta_last_n:{run_id}:{sid}") or 0)
        needed = max(cfg.min_trades, math.ceil(last_n * 1.5)) if last_n else cfg.min_trades
        child = children.get(sid)
        if child is not None:
            state, progress = "filtro aprendido", 1.0
        elif n >= needed:
            state, progress = "listo para entrenar", 1.0
        else:
            state = "reuniendo ejemplos" if not last_n else "sin patrón fiable; reuniendo más"
            progress = _clamp(n / needed)
        rows.append(
            {
                "strategy_id": sid,
                "examples": n,
                "needed": needed,
                "attempted": last_n > 0,
                "state": state,
                "progress": progress,
                "filter": child.rule_id if child is not None else None,
                "last_result": last_lesson.get(sid, ""),
            }
        )
    attempts = store.query("SELECT COUNT(*) n FROM lessons WHERE kind='learning'")[0]["n"]
    return {
        "min_examples": cfg.min_trades,
        "attempts": attempts,
        "filters": len(children),
        "strategies": sorted(rows, key=lambda r: -r["progress"]),
    }


def ai_progress(store: SQLiteStore) -> dict[str, int]:
    HypothesisStore(store)  # creates the table on a lab that never asked the analyst
    rows = store.query("SELECT status, COUNT(*) n FROM hypotheses GROUP BY status")
    by = {r["status"]: r["n"] for r in rows}
    return {
        "proposed": sum(by.values()) - by.get("invalid", 0),
        "pending": by.get("proposed", 0),
        "tested": by.get("promoted", 0) + by.get("rejected", 0),
        "promoted": by.get("promoted", 0),
        "invalid": by.get("invalid", 0),
    }


def activity_feed(store: SQLiteStore, run_id: str, limit: int = 40) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for r in store.query(
        "SELECT id, finished_at, summary FROM research_runs WHERE status='done' "
        "ORDER BY id DESC LIMIT 10"
    ):
        s = json.loads(r["summary"] or "{}")
        cand = int(s.get("n_candidates") or 0)
        items.append({
            "id": f"run:{r['id']}", "ts": r["finished_at"], "kind": "research",
            "tone": "good" if cand else "info",
            "text": f"Ciclo de research #{r['id']}: {int(s.get('n_hypotheses') or 0):,} "
                    f"hipótesis examinadas, {cand} candidatas".replace(",", "."),
        })  # fmt: skip
    for r in store.query(
        "SELECT id, ts, rule_id, to_status, reason FROM rule_events ORDER BY id DESC LIMIT 15"
    ):
        tone = {"champion": "good", "retired": "bad"}.get(r["to_status"], "info")
        items.append({
            "id": f"ev:{r['id']}", "ts": r["ts"], "kind": "rule", "tone": tone,
            "text": f"{r['rule_id']} → {STATUS_ES.get(r['to_status'], r['to_status'])}"
                    + (f": {r['reason']}" if r["reason"] else ""),
        })  # fmt: skip
    for r in store.query(
        "SELECT id, ts, kind, text FROM lessons WHERE kind != 'research' ORDER BY id DESC LIMIT 15"
    ):
        tone = {"promotion": "good", "retirement": "bad", "golden_reject": "bad"}.get(
            r["kind"], "info"
        )
        kind = "ml" if r["kind"] == "learning" else "lesson"
        items.append({"id": f"ls:{r['id']}", "ts": r["ts"], "kind": kind, "tone": tone,
                      "text": r["text"]})  # fmt: skip
    for h in HypothesisStore(store).recent(10):
        tone = {"promoted": "good", "invalid": "bad"}.get(h["status"], "info")
        verb = {"invalid": "descartada", "rejected": "rechazada por el lab",
                "promoted": "aprobada por el lab"}.get(h["status"], "propuesta")  # fmt: skip
        items.append({"id": f"ai:{h['id']}:{h['status']}", "ts": h["created_at"], "kind": "ai",
                      "tone": tone, "text": f"Idea de la IA {verb}: {h['name']}"})  # fmt: skip
    for r in store.query(
        "SELECT id, exit_ts, book, strategy_id, symbol, net_return FROM round_trips "
        "WHERE run_id=? ORDER BY exit_ts DESC, id DESC LIMIT 20",
        (run_id,),
    ):
        book = "Paper" if r["book"] == "paper" else "Sombra"
        items.append({
            "id": f"rt:{r['id']}", "ts": r["exit_ts"], "kind": f"trade_{r['book']}",
            "tone": "good" if r["net_return"] > 0 else "bad",
            "text": f"{book} · {r['strategy_id']} · {r['symbol']} {r['net_return']:+.2%}",
        })  # fmt: skip
    items.sort(key=lambda x: x["ts"] or 0.0, reverse=True)
    return items[:limit]


def learning_progress(
    store: SQLiteStore,
    run_id: str,
    strategy_ids: Iterable[str],
    evidence: Mapping[str, EvidenceRow],
    min_edge: float,
    min_conf: float,
) -> dict[str, Any]:
    registry = RuleRegistry(store)
    return {
        "funnel": funnel(store),
        "rules": rule_progress(store, registry, run_id, evidence, min_edge, min_conf),
        "ml": ml_progress(store, registry, run_id, strategy_ids),
        "ai": ai_progress(store),
        "feed": activity_feed(store, run_id),
    }
