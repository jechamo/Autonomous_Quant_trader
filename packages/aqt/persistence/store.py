"""Persist research results to Supabase (PostgREST) — metadata only, never bulk market data.

Credentials come from the environment (``SUPABASE_URL``, ``SUPABASE_SERVICE_ROLE_KEY``); the
service-role key bypasses RLS and must only ever live in backend secrets.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from aqt import __version__
from aqt.research.study import PairResult, StudyReport


class PersistenceError(RuntimeError):
    pass


class ResultStore(Protocol):
    def persist_study(self, study: StudyReport, universe: list[str]) -> str | None: ...


class NullStore:
    """Default store: keeps nothing (offline runs, tests)."""

    def persist_study(self, study: StudyReport, universe: list[str]) -> str | None:
        return None


class SupabaseStore:
    def __init__(self, client: httpx.Client) -> None:
        self._http = client

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SupabaseStore:
        env = os.environ if env is None else env
        url = env.get("SUPABASE_URL", "").rstrip("/")
        key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise PersistenceError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        return cls(cls.make_client(url, key))

    @staticmethod
    def make_client(url: str, key: str, **kwargs: Any) -> httpx.Client:
        return httpx.Client(
            base_url=f"{url}/rest/v1",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            timeout=30.0,
            **kwargs,
        )

    def __repr__(self) -> str:  # never leak the key
        return f"SupabaseStore(base_url={self._http.base_url})"

    # ------------------------------------------------------------------ low level
    def _request(self, method: str, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        resp = self._http.request(method, path, **kwargs)
        if resp.status_code >= 400:
            raise PersistenceError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else []

    def _insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/{table}", json=row)[0]

    # ------------------------------------------------------------------ entities
    def start_experiment(self, study: StudyReport, universe: list[str]) -> str:
        row = self._insert(
            "experiments",
            {
                "name": study.config.name,
                "symbol_universe": universe,
                "timeframe": study.config.timeframe,
                "n_hypotheses": study.n_hypotheses,
                "fdr_q": study.config.fdr_q,
                "config": study.config.__dict__,
                "data_hash": study.study_hash,
                "code_version": __version__,
                "status": "running",
            },
        )
        return str(row["id"])

    def finish_experiment(self, experiment_id: str, status: str) -> None:
        self._request(
            "PATCH",
            "/experiments",
            params={"id": f"eq.{experiment_id}"},
            json={"status": status, "finished_at": datetime.now(UTC).isoformat()},
        )

    def upsert_strategy(self, name: str, family: str, description: str) -> str:
        rows = self._request(
            "POST",
            "/strategies",
            params={"on_conflict": "name"},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json={"name": name, "family": family, "description": description},
        )
        return str(rows[0]["id"])

    def upsert_strategy_version(self, strategy_id: str, spec: dict[str, Any]) -> str:
        config_hash = spec["config_hash"]
        found = self._request(
            "GET", "/strategy_versions", params={"config_hash": f"eq.{config_hash}", "select": "id"}
        )
        if found:
            return str(found[0]["id"])
        existing = self._request(
            "GET",
            "/strategy_versions",
            params={"strategy_id": f"eq.{strategy_id}", "select": "version"},
        )
        version = max((int(r["version"]) for r in existing), default=0) + 1
        row = self._insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "version": version,
                "config_hash": config_hash,
                "spec": spec["spec"],
                "params": spec["params"],
            },
        )
        return str(row["id"])

    def record_pair(self, experiment_id: str, pair: PairResult, timeframe: str) -> None:
        r = pair.report
        if r is None:
            return
        sel = r["selected_strategy"]
        strategy_id = self.upsert_strategy(
            name=r["config"]["strategy"],
            family=sel["family"],
            description=sel["spec"].get("description", ""),
        )
        version_id = self.upsert_strategy_version(strategy_id, sel)
        mt = r["multiple_testing"]
        common = {
            "experiment_id": experiment_id,
            "strategy_version_id": version_id,
            "symbol": pair.symbol,
            "timeframe": timeframe,
            "costs": r["config"]["costs"],
        }
        for sample, block, p_value, adjusted, edge in (
            ("in_sample", r["in_sample"], mt["selected_raw_p"], pair.global_adjusted_p, None),
            (
                "out_of_sample",
                r["out_of_sample"],
                r["out_of_sample"]["p_value"],
                None,
                r["edge"]["score"],
            ),
        ):
            self._insert(
                "backtests",
                {
                    **common,
                    "sample": sample,
                    "period_start": block["period"][0],
                    "period_end": block["period"][1],
                    "n_trades": block["n_trades"],
                    "win_rate": block["win_rate"],
                    "avg_win": block["avg_win"],
                    "avg_loss": block["avg_loss"],
                    "expected_value": block["expected_value"],
                    "profit_factor": block["profit_factor"],
                    "max_drawdown": block["max_drawdown"],
                    "sharpe": block["sharpe"],
                    "sortino": block["sortino"],
                    "p_value": p_value,
                    "adjusted_p_value": adjusted,
                    "edge_score": edge,
                    "report": {"decision": pair.decision, **r} if sample == "out_of_sample" else {},
                },
            )
        wf = r["walk_forward"]
        self._insert(
            "walk_forward_runs",
            {
                "experiment_id": experiment_id,
                "strategy_id": strategy_id,
                "n_windows": len(wf["windows"]),
                "anchored": True,
                "oos_trades": wf["oos_trades"],
                "oos_ev": wf["oos_ev"],
                "efficiency": wf["efficiency"],
                "windows": wf["windows"],
            },
        )

    def persist_study(self, study: StudyReport, universe: list[str]) -> str | None:
        experiment_id = self.start_experiment(study, universe)
        try:
            for pair in study.pairs:
                self.record_pair(experiment_id, pair, study.config.timeframe)
        except Exception:
            self.finish_experiment(experiment_id, "failed")
            raise
        self.finish_experiment(experiment_id, "completed")
        return experiment_id
