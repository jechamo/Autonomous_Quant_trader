"""Go-live gate: an executable checklist that says when paper trading has earned real money.

Read-only: it inspects what the paper account has done (closed trades, equity against Buy & Hold,
operational events) and never changes configuration or sends orders. Passing it does not switch
anything to LIVE; that still needs a live broker adapter plus ``TRADING_MODE=LIVE`` and
``LIVE_TRADING_ENABLED=true``.

Equity and Buy & Hold are compared as chained returns *within* each trading session
(``session_start`` events, or gaps longer than ``session_gap_s``): the engine restarts its
benchmark at every session, so returns across a restart are not comparable and are skipped on
both sides.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from scipy import stats

from aqt.stream.store import SQLiteStore

DAY = 86_400.0

# No live broker adapter exists yet: passing the gate means "ready to build/enable live".
LIVE_BROKER_AVAILABLE = False


@dataclass(frozen=True)
class GateConfig:
    min_days: float = 28.0
    min_trades: int = 50
    max_p_value: float = 0.05
    weeks: int = 4
    min_positive_weeks: int = 3
    session_gap_s: float = 3600.0


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    ok: bool
    value: str
    target: str
    detail: str = ""


@dataclass
class GateReport:
    run_id: str
    evaluated_at: float
    criteria: list[Criterion] = field(default_factory=list)
    live_broker_available: bool = LIVE_BROKER_AVAILABLE

    @property
    def ready(self) -> bool:
        return bool(self.criteria) and all(c.ok for c in self.criteria)

    @property
    def passed(self) -> int:
        return sum(c.ok for c in self.criteria)

    def summary(self) -> str:
        if self.ready:
            return f"READY for live ({self.passed}/{len(self.criteria)})"
        missing = ", ".join(c.label for c in self.criteria if not c.ok)
        return f"not ready ({self.passed}/{len(self.criteria)}): {missing}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "evaluated_at": self.evaluated_at,
            "ready": self.ready,
            "passed": self.passed,
            "total": len(self.criteria),
            "live_broker_available": self.live_broker_available,
            "criteria": [asdict(c) for c in self.criteria],
        }


def session_returns(
    equity: list[dict[str, Any]], session_starts: list[float], gap_s: float
) -> tuple[list[float], list[float]]:
    """Per-step growth factors of equity and Buy & Hold, skipping session boundaries."""
    starts = sorted(session_starts)
    eq_f: list[float] = []
    bh_f: list[float] = []
    prev: dict[str, Any] | None = None
    k = 0
    for row in equity:
        new_session = False
        while k < len(starts) and starts[k] <= row["ts"]:
            new_session = new_session or (prev is not None and prev["ts"] < starts[k])
            k += 1
        if (
            prev is not None
            and not new_session
            and row["ts"] - prev["ts"] <= gap_s
            and prev["buy_hold"]
            and row["buy_hold"]
            and prev["equity"] > 0
        ):
            eq_f.append(row["equity"] / prev["equity"])
            bh_f.append(row["buy_hold"] / prev["buy_hold"])
        prev = row
    return eq_f, bh_f


def max_drawdown(factors: list[float]) -> float:
    level = peak = 1.0
    worst = 0.0
    for f in factors:
        level *= f
        peak = max(peak, level)
        worst = max(worst, 1.0 - level / peak)
    return worst


def evaluate_gate(
    store: SQLiteStore,
    run_id: str,
    now: float,
    max_dd: float,
    external_venue: bool,
    cfg: GateConfig | None = None,
) -> GateReport:
    cfg = cfg or GateConfig()
    report = GateReport(run_id=run_id, evaluated_at=now)
    add = report.criteria.append
    equity = store.equity_curve(run_id)
    trades = sorted(store.round_trips(run_id, "paper", limit=1_000_000), key=lambda t: t["exit_ts"])
    events = store.ops_events(run_id)
    start = equity[0]["ts"] if equity else now

    days = (now - start) / DAY
    add(Criterion("days", "Tiempo en paper", days >= cfg.min_days, f"{days:.1f} días",
                  f"≥ {cfg.min_days:g} días"))  # fmt: skip

    n = len(trades)
    add(Criterion("trades", "Operaciones cerradas", n >= cfg.min_trades, str(n),
                  f"≥ {cfg.min_trades}"))  # fmt: skip

    net = sum(t["pnl"] for t in trades)
    add(Criterion("net", "Resultado neto tras costes", n > 0 and net > 0, f"{net:+.2f}", "> 0",
                  "comisiones y spread incluidos"))  # fmt: skip

    rets = [t["net_return"] for t in trades]
    p = 1.0
    if len(rets) >= 3 and len(set(rets)) > 1:
        p = float(stats.ttest_1samp(rets, 0.0, alternative="greater").pvalue)
        p = 1.0 if math.isnan(p) else p
    add(Criterion("edge", "Ventaja estadística", p < cfg.max_p_value, f"p = {p:.3f}",
                  f"p < {cfg.max_p_value:g}", "t-test: media de retornos netos > 0"))  # fmt: skip

    weekly: list[float] = []
    for i in range(cfg.weeks):
        hi, lo = now - i * 7 * DAY, now - (i + 1) * 7 * DAY
        weekly.append(sum(t["pnl"] for t in trades if lo <= t["exit_ts"] < hi))
    covered = days >= cfg.weeks * 7
    positive = sum(w > 0 for w in weekly)
    add(Criterion("consistency", "Semanas positivas",
                  covered and positive >= cfg.min_positive_weeks,
                  f"{positive} de {cfg.weeks}" if covered else "aún sin 4 semanas",
                  f"≥ {cfg.min_positive_weeks} de {cfg.weeks}",
                  "P&L semanal: " + ", ".join(f"{w:+.0f}" for w in reversed(weekly))))  # fmt: skip

    starts = [e["ts"] for e in events if e["kind"] == "session_start"]
    eq_f, bh_f = session_returns(equity, starts, cfg.session_gap_s)
    strat = math.prod(eq_f) - 1.0
    bench = math.prod(bh_f) - 1.0
    add(Criterion("buy_hold", "Mejor que Buy & Hold", bool(eq_f) and strat > bench,
                  f"{strat:+.2%} vs {bench:+.2%}", "bot > Buy & Hold",
                  "mismo periodo y mismos símbolos"))  # fmt: skip

    dd = max_drawdown(eq_f)
    add(Criterion("drawdown", "Caída máxima", bool(eq_f) and dd <= max_dd, f"{dd:.1%}",
                  f"≤ {max_dd:.0%}", "límite del perfil de riesgo actual"))  # fmt: skip

    add(Criterion("venue", "Órdenes reales a un broker paper", external_venue,
                  "Alpaca paper" if external_venue else "fills simulados", "broker externo",
                  "las órdenes deben haber pasado por un broker de verdad"))  # fmt: skip

    mism = [e for e in events if e["kind"] == "reconciliation_mismatch"]
    add(Criterion("reconciliation", "Cuadre con el broker", external_venue and not mism,
                  f"{len(mism)} descuadres", "0 descuadres",
                  "posiciones del bot = posiciones del broker"))  # fmt: skip

    armed = tested = False  # events come in order: switched on, then back off
    for e in events:
        armed = armed or e["kind"] == "kill_switch_on"
        tested = tested or (armed and e["kind"] == "kill_switch_off")
    add(Criterion("kill_switch", "Kill switch probado", tested,
                  "probado" if tested else "sin probar", "activar y desactivar una vez",
                  "en el dashboard: activarlo, comprobar que bloquea, desactivarlo"))  # fmt: skip
    return report
