"""Hypothesis generation: context → LLM → strict validation → ``hypotheses`` table → lab.

The analyst sees what the lab has learned (lessons, the last research summary, forward evidence,
its own previous proposals and their verdicts) and proposes new rules in the strategy DSL, each
with the PRD format *Claim / Evidence / Suggested experiment*. Every proposal is validated before
it is stored — known features only, a protective stop, at most ``max_variants`` parameter
combinations, an allowed timeframe — and then examined by the Research Lab like any other
hypothesis (out-of-sample, walk-forward, global FDR, golden check). Nothing here can trade.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from pydantic import ValidationError

from aqt.analyst.client import AnalystConfig, AnalystError, OpenAIClient
from aqt.features.cross_section import augment
from aqt.features.engine import FeatureEngine
from aqt.news.book import NewsBook
from aqt.strategies.dsl import ExitRules, Rule, StrategySpec

if TYPE_CHECKING:  # the analyst never imports the store at runtime (it pulls broker types in)
    from aqt.stream.store import SQLiteStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS hypotheses (
    id INTEGER PRIMARY KEY, created_at REAL NOT NULL, status TEXT NOT NULL, name TEXT NOT NULL,
    timeframe TEXT, claim TEXT, evidence TEXT, experiment TEXT, spec TEXT, grid TEXT,
    config_hash TEXT, model TEXT, usage TEXT, verdict TEXT, research_run INTEGER, reason TEXT
);
CREATE INDEX IF NOT EXISTS hypotheses_status ON hypotheses(status);
"""

_NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
_NON_FEATURES = {"regime"}


def available_features(session: str = "24/7", news: bool = False) -> list[str]:
    """Every numeric column a rule can reference (computed on a small synthetic panel); the
    ``news_*`` columns only when the lab has a news source."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2026-01-05 14:00", periods=260, freq="1h", tz="UTC")
    frames = {}
    for sym in ("A", "B"):
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
        open_ = np.concatenate([[100.0], close[:-1]])
        vol = rng.exponential(100, len(idx)) + 1
        frames[sym] = pd.DataFrame(
            {"open": open_, "high": np.maximum(open_, close) * 1.001,
             "low": np.minimum(open_, close) * 0.999, "close": close, "volume": vol,
             "taker_buy_volume": vol / 2},
            index=idx,
        )  # fmt: skip
    book = NewsBook(coverage_start=0.0, covered_until=float("inf")) if news else None
    feats = FeatureEngine().compute(augment(frames, 3600, session, book)["A"])
    numeric = feats.select_dtypes(include="number").columns
    return sorted(c for c in numeric if c not in _NON_FEATURES)


@dataclass
class Proposal:
    name: str
    timeframe: str
    claim: str
    evidence: str
    experiment: str
    spec: StrategySpec
    grid: dict[str, list[float | int]]


def rule_key(p: Proposal) -> str:
    """Identity of the experiment regardless of the name the model gave it."""
    body = {
        "timeframe": p.timeframe,
        "entry": p.spec.entry.model_dump(mode="json"),
        "exit": p.spec.exit.model_dump(mode="json"),
        "params": p.spec.params,
        "grid": p.grid,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class AnalystResult:
    created: list[Proposal] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    skipped: str = ""


def validate_proposal(
    raw: dict[str, Any],
    features: Iterable[str],
    timeframes: Sequence[str],
    max_variants: int = 8,
) -> Proposal:
    """Turn one LLM proposal into a checked DSL rule, or raise ``ValueError`` with the reason."""
    name = str(raw.get("name", "")).strip().lower()
    if not _NAME.match(name):
        raise ValueError(f"invalid name {name!r} (snake_case, 3-40 chars)")
    timeframe = str(raw.get("timeframe", ""))
    if timeframe not in timeframes:
        raise ValueError(f"timeframe {timeframe!r} not in {list(timeframes)}")
    params = raw.get("params") or {}
    grid = raw.get("grid") or {}
    if not isinstance(params, dict) or not isinstance(grid, dict):
        raise ValueError("params and grid must be objects")
    for k, v in [*params.items(), *((k, x) for k, vs in grid.items() for x in (vs or []))]:
        if not isinstance(v, int | float) or isinstance(v, bool):
            raise ValueError(f"parameter {k!r} must be numeric")
    if not set(grid) <= set(params):
        raise ValueError(f"grid keys {sorted(set(grid) - set(params))} have no default in params")
    variants = 1
    for values in grid.values():
        if not isinstance(values, list) or not 1 <= len(values) <= 4:
            raise ValueError("each grid entry needs 1-4 values")
        variants *= len(values)
    if variants > max_variants:
        raise ValueError(f"{variants} parameter combinations (max {max_variants})")
    try:
        spec = StrategySpec(
            name=f"ai_{name}",
            family="ai",
            description=str(raw.get("claim", ""))[:240],
            entry=Rule.model_validate(raw.get("entry")),
            exit=ExitRules.model_validate(raw.get("exit")),
            params=params,
        )
        rendered = spec.render()
        for combo in itertools.product(*(grid[k] for k in grid)):
            spec.render(dict(zip(grid, combo, strict=True)))
    except (ValidationError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid rule: {str(exc)[:200]}") from exc
    if rendered.exit.max_holding_bars is None:
        raise ValueError("max_holding_bars is required")
    used = rendered.entry.features_used()
    if rendered.exit.exit_signal is not None:
        used |= rendered.exit.exit_signal.features_used()
    unknown = sorted(used - set(features))
    if unknown:
        raise ValueError(f"unknown features {unknown}")
    return Proposal(
        name=spec.name,
        timeframe=timeframe,
        claim=str(raw.get("claim", ""))[:1000],
        evidence=str(raw.get("evidence", ""))[:1000],
        experiment=str(raw.get("suggested_experiment", ""))[:1000],
        spec=spec,
        grid={k: list(v) for k, v in grid.items()},
    )


class HypothesisStore:
    def __init__(self, store: SQLiteStore, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock
        store.executescript(SCHEMA)

    def add(self, p: Proposal, model: str, usage: dict[str, Any]) -> int:
        return self.store.execute(
            "INSERT INTO hypotheses (created_at, status, name, timeframe, claim, evidence, "
            "experiment, spec, grid, config_hash, model, usage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.clock(), "proposed", p.name, p.timeframe, p.claim, p.evidence, p.experiment,
             p.spec.model_dump_json(), json.dumps(p.grid), rule_key(p), model,
             json.dumps(usage)),
        )  # fmt: skip

    def add_invalid(self, name: str, reason: str, model: str) -> None:
        self.store.execute(
            "INSERT INTO hypotheses (created_at, status, name, model, reason) VALUES (?,?,?,?,?)",
            (self.clock(), "invalid", name or "?", model, reason),
        )

    def known_hashes(self) -> set[str]:
        rows = self.store.query("SELECT config_hash FROM hypotheses WHERE config_hash IS NOT NULL")
        return {r["config_hash"] for r in rows}

    def pending(self, timeframe: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM hypotheses WHERE status='proposed'"
        args: list[Any] = []
        if timeframe is not None:
            sql += " AND timeframe=?"
            args.append(timeframe)
        rows = self.store.query(sql + " ORDER BY id", args)
        for r in rows:
            r["spec_obj"] = StrategySpec.model_validate_json(r["spec"])
            r["grid_obj"] = json.loads(r["grid"] or "{}")
        return rows

    def mark(
        self, hid: int, status: str, verdict: dict[str, Any], research_run: int | None
    ) -> None:
        self.store.execute(
            "UPDATE hypotheses SET status=?, verdict=?, research_run=? WHERE id=?",
            (status, json.dumps(verdict, default=str), research_run, hid),
        )

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT id, created_at, status, name, timeframe, claim, evidence, experiment, grid, "
            "model, verdict, reason, research_run FROM hypotheses ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        for r in rows:
            r["verdict"] = json.loads(r["verdict"] or "{}")
            r["grid"] = json.loads(r["grid"] or "{}")
        return rows

    def calls_today(self) -> int:
        key = f"analyst_calls:{datetime.fromtimestamp(self.clock(), UTC):%Y-%m-%d}"
        return int(self.store.get_setting(key) or 0)

    def count_call(self) -> None:
        key = f"analyst_calls:{datetime.fromtimestamp(self.clock(), UTC):%Y-%m-%d}"
        self.store.set_setting(key, str(self.calls_today() + 1))


def build_context(
    store: SQLiteStore,
    market: str,
    timeframes: Sequence[str],
    families: dict[str, str],
    features: Sequence[str],
    hyps: HypothesisStore,
) -> dict[str, Any]:
    """What the analyst may read: the lab's own results. No credentials, no account data."""

    def rows(sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        try:
            return store.query(sql, args)
        except Exception:  # table not created yet (lab never ran)
            return []

    lessons = [r["text"] for r in rows("SELECT text FROM lessons ORDER BY id DESC LIMIT 15")]
    last = rows("SELECT summary FROM research_runs WHERE status='done' ORDER BY id DESC LIMIT 1")
    summary = json.loads(last[0]["summary"]) if last else {}
    research = {
        "n_hypotheses": summary.get("n_hypotheses"),
        "failed_checks": summary.get("failed_checks"),
        "top_pairs": [
            {k: p.get(k) for k in ("symbol", "timeframe", "strategy", "oos_ev", "oos_trades",
                                    "oos_p_value", "decision")}
            for p in (summary.get("top_pairs") or [])[:8]
        ],
    }  # fmt: skip
    forward = rows(
        "SELECT strategy_id, COUNT(*) AS n, AVG(net_return) AS mean_net_return, "
        "AVG(CASE WHEN net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate FROM round_trips "
        "WHERE book='shadow' AND run_id LIKE 'live-%' GROUP BY strategy_id ORDER BY n DESC LIMIT 20"
    )
    previous = [
        {"name": h["name"], "timeframe": h["timeframe"], "status": h["status"],
         "claim": (h["claim"] or "")[:160], "verdict": h["verdict"], "reason": h["reason"]}
        for h in hyps.recent(20)
    ]  # fmt: skip
    return {
        "market": market,
        "allowed_timeframes": list(timeframes),
        "existing_families": families,
        "available_features": list(features),
        "last_research": research,
        "forward_evidence": forward,
        "lessons": lessons,
        "your_previous_hypotheses": previous,
    }


# One hypothesis in the lab's JSON DSL (shared by the analyst and the morning news briefing).
HYPOTHESIS_SCHEMA = """{
  "name": "snake_case_name",
  "timeframe": "<one of allowed_timeframes>",
  "claim": "what effect you expect and why",
  "evidence": "what in the context supports it",
  "suggested_experiment": "what result would confirm or refute it",
  "entry": {"all_of": [{"left": "<feature>", "op": "<|<=|>|>=|crosses_above|crosses_below", \
"right": <number | "<feature>" | "$param">}], "any_of": []},
  "exit": {"stop_atr_mult": <number | "$param">, "target_atr_mult": <number | "$param" | null>, \
"max_holding_bars": <integer | "$param">, "exit_signal": null | {"all_of": [...]}},
  "params": {"param": <default number>},
  "grid": {"param": [<2-4 numbers>]}
}"""
HYPOTHESIS_RULES = """Rules: use only features from available_features; every rule needs \
stop_atr_mult and max_holding_bars; at most 8 parameter combinations per hypothesis; at most \
{max_hypotheses} hypotheses."""

SYSTEM_PROMPT = (
    """You are the research analyst of a long-only systematic trading lab. You never \
trade: you propose testable hypotheses that the lab examines out-of-sample, with walk-forward, \
Monte Carlo and a global false-discovery-rate correction across every hypothesis tested. Costs \
are already included in every result you see.

Propose NEW ideas that the context suggests are worth testing — not variations of rules that \
already failed for the same reason. Prefer economically motivated effects (momentum, reversal, \
volatility, liquidity, calendar, cross-sectional ranking) at the allowed timeframes. Each \
hypothesis is one long-only rule in this JSON DSL:

{"hypotheses": ["""
    + HYPOTHESIS_SCHEMA
    + """]}

"""
    + HYPOTHESIS_RULES
    + " Answer with the JSON object only."
)


def run_analyst(
    store: SQLiteStore,
    client: OpenAIClient,
    cfg: AnalystConfig,
    market: str,
    timeframes: Sequence[str],
    families: dict[str, str],
    session: str = "24/7",
    clock: Callable[[], float] = time.time,
    news: bool = False,
) -> AnalystResult:
    hyps = HypothesisStore(store, clock)
    if hyps.calls_today() >= cfg.max_calls_per_day:
        return AnalystResult(skipped=f"daily budget reached ({cfg.max_calls_per_day} calls)")
    features = available_features(session, news)
    context = build_context(store, market, timeframes, families, features, hyps)
    system = SYSTEM_PROMPT.replace("{max_hypotheses}", str(cfg.max_hypotheses))
    hyps.count_call()
    try:
        completion = client.complete_json(system, json.dumps(context, default=str))
    except AnalystError as exc:
        return AnalystResult(skipped=str(exc))
    result = AnalystResult(usage=completion.usage)
    result.created, result.rejected = ingest_proposals(
        hyps, completion.content.get("hypotheses"), features, timeframes,
        completion.model, completion.usage, cfg.max_hypotheses,
    )  # fmt: skip
    return result


def ingest_proposals(
    hyps: HypothesisStore,
    raw_list: Any,
    features: Sequence[str],
    timeframes: Sequence[str],
    model: str,
    usage: dict[str, Any],
    limit: int,
) -> tuple[list[Proposal], list[tuple[str, str]]]:
    """Validate the model's proposals; valid, new ones wait for the lab, the rest are kept with
    the reason they were refused."""
    created: list[Proposal] = []
    rejected: list[tuple[str, str]] = []
    known = hyps.known_hashes()
    for raw in raw_list[:limit] if isinstance(raw_list, list) else []:
        name = str(raw.get("name", "")) if isinstance(raw, dict) else ""
        try:
            if not isinstance(raw, dict):
                raise ValueError("not an object")
            proposal = validate_proposal(raw, features, timeframes)
            if rule_key(proposal) in known:
                raise ValueError("duplicate of an earlier hypothesis")
        except ValueError as exc:
            rejected.append((name, str(exc)))
            hyps.add_invalid(name, str(exc), model)
            continue
        hyps.add(proposal, model, usage)
        known.add(rule_key(proposal))
        created.append(proposal)
    return created, rejected
