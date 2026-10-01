"""Rule registry: the Research Lab's memory (SQLite, next to the trader's audit trail).

A rule moves through ``candidate → challenger → champion`` and can be ``retired`` at any point.
Every transition is an auditable ``rule_event`` with its reason, and the significant ones also
leave a human-readable ``lesson``. ``rule_id`` is the live ``strategy_id`` of the rule, so the
shadow/paper trades the engine records can be joined back to the rule that produced them.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aqt.strategies.dsl import StrategySpec
from aqt.stream.store import SQLiteStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    id INTEGER PRIMARY KEY, started_at REAL NOT NULL, finished_at REAL, status TEXT NOT NULL,
    config TEXT, summary TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS rules (
    rule_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe_s REAL NOT NULL, family TEXT,
    name TEXT, spec TEXT NOT NULL, status TEXT NOT NULL, research_run INTEGER,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, metrics TEXT, meta TEXT,
    parent_id TEXT, version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS rules_status ON rules(status);
CREATE TABLE IF NOT EXISTS rule_events (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, rule_id TEXT NOT NULL, from_status TEXT,
    to_status TEXT NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, rule_id TEXT, kind TEXT NOT NULL, text TEXT NOT NULL,
    metrics TEXT
);
"""


class RuleStatus(StrEnum):
    CANDIDATE = "candidate"  # passed research, not (yet) live
    CHALLENGER = "challenger"  # trading in the live shadow book, earning forward evidence
    CHAMPION = "champion"  # forward evidence accepted by the Risk Engine: trades paper
    RETIRED = "retired"


ACTIVE = (RuleStatus.CHALLENGER, RuleStatus.CHAMPION)


@dataclass
class RuleRecord:
    rule_id: str
    symbol: str
    timeframe_s: float
    spec: StrategySpec | None  # None for meta versions of non-DSL (baseline) strategies
    status: RuleStatus = RuleStatus.CANDIDATE
    research_run: int | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    version: int = 1
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def is_meta(self) -> bool:
        return self.meta.get("kind") == "meta"

    @property
    def family(self) -> str:
        return "meta" if self.is_meta else (self.spec.family if self.spec else "")

    @property
    def name(self) -> str:
        if self.is_meta:
            return f"{self.meta.get('base')} + filtro ML"
        return self.spec.name if self.spec else self.rule_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "symbol": self.symbol,
            "timeframe_s": self.timeframe_s,
            "family": self.family,
            "name": self.name,
            "description": self.spec.description if self.spec else self.name,
            "status": str(self.status),
            "research_run": self.research_run,
            "metrics": self.metrics,
            "meta": self.meta,
            "parent_id": self.parent_id,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_rule(r: dict[str, Any]) -> RuleRecord:
    return RuleRecord(
        rule_id=r["rule_id"],
        symbol=r["symbol"],
        timeframe_s=float(r["timeframe_s"]),
        spec=None if r["spec"] in (None, "null") else StrategySpec.model_validate_json(r["spec"]),
        status=RuleStatus(r["status"]),
        research_run=r["research_run"],
        metrics=json.loads(r["metrics"] or "{}"),
        meta=json.loads(r["meta"] or "{}"),
        parent_id=r["parent_id"],
        version=int(r["version"]),
        created_at=float(r["created_at"]),
        updated_at=float(r["updated_at"]),
    )


class RuleRegistry:
    def __init__(self, store: SQLiteStore, clock: Any = time.time) -> None:
        self.store = store
        self.clock = clock
        store.executescript(SCHEMA)

    # ------------------------------------------------------------------ research runs
    def start_run(self, config: dict[str, Any]) -> int:
        return self.store.execute(
            "INSERT INTO research_runs (started_at, status, config) VALUES (?, 'running', ?)",
            (self.clock(), json.dumps(config, default=str)),
        )

    def finish_run(
        self, run_id: int, summary: dict[str, Any], status: str = "done", error: str = ""
    ) -> None:
        self.store.execute(
            "UPDATE research_runs SET finished_at=?, status=?, summary=?, error=? WHERE id=?",
            (self.clock(), status, json.dumps(summary, default=str), error, run_id),
        )

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.store.query("SELECT * FROM research_runs ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["config"] = json.loads(r["config"] or "{}")
            r["summary"] = json.loads(r["summary"] or "{}")
        return rows

    # ------------------------------------------------------------------ rules
    def get(self, rule_id: str) -> RuleRecord | None:
        rows = self.store.query("SELECT * FROM rules WHERE rule_id=?", (rule_id,))
        return _row_to_rule(rows[0]) if rows else None

    def rules(self, statuses: Iterable[RuleStatus] | None = None) -> list[RuleRecord]:
        if statuses is None:
            rows = self.store.query("SELECT * FROM rules ORDER BY updated_at DESC")
        else:
            st = [str(s) for s in statuses]
            rows = self.store.query(
                f"SELECT * FROM rules WHERE status IN ({','.join('?' * len(st))}) "
                "ORDER BY updated_at DESC",
                st,
            )
        return [_row_to_rule(r) for r in rows]

    def active(self) -> list[RuleRecord]:
        return self.rules(ACTIVE)

    def upsert(self, rule: RuleRecord, reason: str = "") -> RuleRecord:
        """Insert a new rule or refresh an existing one's metrics (status kept unless retired)."""
        now = self.clock()
        existing = self.get(rule.rule_id)
        if existing is None:
            rule.created_at = rule.updated_at = now
            self.store.execute(
                "INSERT INTO rules (rule_id, symbol, timeframe_s, family, name, spec, status, "
                "research_run, created_at, updated_at, metrics, meta, parent_id, version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rule.rule_id, rule.symbol, rule.timeframe_s, rule.family, rule.name,
                 rule.spec.model_dump_json() if rule.spec else "null", str(rule.status),
                 rule.research_run, now, now,
                 json.dumps(rule.metrics, default=str), json.dumps(rule.meta, default=str),
                 rule.parent_id, rule.version),
            )  # fmt: skip
            self._event(rule.rule_id, None, rule.status, reason or "discovered by research")
            return rule
        self.store.execute(
            "UPDATE rules SET metrics=?, meta=?, research_run=?, updated_at=? WHERE rule_id=?",
            (json.dumps(rule.metrics, default=str), json.dumps(rule.meta, default=str),
             rule.research_run, now, rule.rule_id),
        )  # fmt: skip
        existing.metrics, existing.meta = rule.metrics, rule.meta
        return existing

    def set_status(
        self, rule_id: str, status: RuleStatus, reason: str, metrics: dict[str, Any] | None = None
    ) -> None:
        rule = self.get(rule_id)
        if rule is None:
            raise KeyError(rule_id)
        if rule.status == status:
            return
        merged = {**rule.metrics, **(metrics or {})}
        self.store.execute(
            "UPDATE rules SET status=?, updated_at=?, metrics=? WHERE rule_id=?",
            (str(status), self.clock(), json.dumps(merged, default=str), rule_id),
        )
        self._event(rule_id, rule.status, status, reason)

    def _event(self, rule_id: str, frm: RuleStatus | None, to: RuleStatus, reason: str) -> None:
        self.store.execute(
            "INSERT INTO rule_events (ts, rule_id, from_status, to_status, reason) "
            "VALUES (?,?,?,?,?)",
            (self.clock(), rule_id, str(frm) if frm else None, str(to), reason),
        )

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.query("SELECT * FROM rule_events ORDER BY id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------ lessons
    def add_lesson(
        self,
        kind: str,
        text: str,
        rule_id: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self.store.execute(
            "INSERT INTO lessons (ts, rule_id, kind, text, metrics) VALUES (?,?,?,?,?)",
            (self.clock(), rule_id, kind, text, json.dumps(metrics or {}, default=str)),
        )

    def lessons(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.query("SELECT * FROM lessons ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["metrics"] = json.loads(r["metrics"] or "{}")
        return rows
