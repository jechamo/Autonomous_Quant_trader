"""Watches the paper account for the go-live gate and tells the operator when it flips.

- Every ``sample_s``: records operational incidents (positions that stop reconciling with the
  broker, broker outages and recoveries) in ``ops_events``.
- Every ``every_s``: evaluates :func:`aqt.stream.golive.evaluate_gate`; when the verdict changes
  (not ready → ready, or back) it notifies once and records ``gate_ready`` / ``gate_lost``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from aqt.stream.engine import StreamingEngine
from aqt.stream.golive import GateConfig, GateReport, evaluate_gate
from aqt.stream.store import SQLiteStore

from services.trader.notify import Notifier

log = logging.getLogger(__name__)


class GoLiveMonitor:
    def __init__(
        self,
        engine: StreamingEngine,
        store: SQLiteStore,
        notify: Notifier,
        external_venue: bool,
        clock: Callable[[], float] = time.time,
        every_s: float = 3600.0,
        sample_s: float = 15.0,
        cfg: GateConfig | None = None,
    ) -> None:
        self.engine = engine
        self.store = store
        self.notify = notify
        self.external_venue = external_venue
        self.clock = clock
        self.every_s = every_s
        self.sample_s = sample_s
        self.cfg = cfg or GateConfig()
        self.run_id = engine.cfg.run_id
        self._key = f"golive:{self.run_id}:ready"
        self._bad_samples = 0
        self._mismatch_open = False
        self._broker_ok = True
        self._last_eval = -float("inf")
        self._stale = False
        self.report: GateReport | None = None

    # ------------------------------------------------------------------ events
    def event(self, kind: str, detail: str = "") -> None:
        self.store.log_ops_event(self.run_id, self.clock(), kind, detail)
        if not kind.startswith("gate_"):
            self._stale = True  # the dashboard re-evaluates on its next read

    def begin(self) -> None:
        """A new trading session: equity and Buy & Hold restart, so returns are split here."""
        self.event("session_start")

    def sample(self) -> None:
        health = self.engine.broker.health()
        if health.ok != self._broker_ok:
            self._broker_ok = health.ok
            self.event("broker_recovered" if health.ok else "broker_down", health.detail)
        bad = not self.engine.reconciled or "reconcile" in health.detail
        self._bad_samples = self._bad_samples + 1 if bad else 0
        if self._bad_samples >= 2 and not self._mismatch_open:  # persists across two samples
            self._mismatch_open = True
            self.event("reconciliation_mismatch", health.detail or "engine book != broker")
        elif not bad and self._mismatch_open:
            self._mismatch_open = False
            self.event("reconciliation_ok")

    # ------------------------------------------------------------------ gate
    def evaluate(self) -> GateReport:
        now = self.clock()
        self._last_eval = now
        self._stale = False
        report = evaluate_gate(
            self.store,
            self.run_id,
            now,
            self.engine.profile.max_drawdown,
            self.external_venue,
            self.cfg,
        )
        self.report = report
        was = self.store.get_setting(self._key) == "true"
        if report.ready != was:
            self.store.set_setting(self._key, str(report.ready).lower())
            self.event("gate_ready" if report.ready else "gate_lost", report.summary())
            if report.ready:
                self.notify(
                    "Autonomous Quant Trader: listo para real",
                    f"La cuenta paper {self.run_id} ha superado la puerta a real "
                    f"({report.passed}/{len(report.criteria)}). Revisa el panel «Puerta a real» "
                    "del dashboard. Nada se activa solo: el paso a real es decisión tuya.",
                )
            else:
                failed = ", ".join(c.label for c in report.criteria if not c.ok)
                self.notify(
                    "Autonomous Quant Trader: ya no está listo para real",
                    f"La cuenta paper {self.run_id} ha dejado de cumplir: {failed}.",
                )
        return report

    def overview(self) -> dict[str, Any]:
        report = self.evaluate() if self.report is None or self._stale else self.report
        out = report.to_dict()
        out["events"] = [
            {**e, "detail": e["detail"] or ""}
            for e in self.store.ops_events(self.run_id)[-20:][::-1]
            if e["kind"] != "session_start"
        ]
        return json.loads(json.dumps(out, default=str))

    async def loop(self) -> None:
        while True:
            try:
                self.sample()
                if self.clock() - self._last_eval >= self.every_s:
                    self.evaluate()
            except Exception:  # the gate is advisory: never take the trader down
                log.exception("go-live monitor failed")
            await asyncio.sleep(self.sample_s)
