"""Audit records produced by the streaming engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RoundTrip:
    book: str  # "paper" (risk-approved orders) or "shadow" (every intent, virtual)
    strategy_id: str
    symbol: str
    entry_ts: float
    exit_ts: float
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    fees: float
    net_return: float
    exit_reason: str
    context: dict[str, float] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("context")
        return d


@dataclass(frozen=True)
class Decision:
    ts: float
    symbol: str
    strategy_id: str
    side: str
    kind: str  # entry | exit
    action: str  # APPROVE | ADJUST_SIZE | REJECT | THROTTLED | PAUSED
    quantity: float = 0.0
    notional: float = 0.0
    reasons: tuple[str, ...] = ()
    detail: str = ""
    checks: tuple[tuple[str, bool, str], ...] = field(default=(), repr=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("checks")
        d["reasons"] = list(self.reasons)
        return d
