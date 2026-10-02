"""Forward (out-of-sample by construction) evidence from shadow trades.

Every entry intent of every strategy is traded *virtually* — same latency, same bid/ask fills,
same fees as the paper book — whether or not the Risk Engine lets the real book take it. The
net returns of those shadow round trips are the only evidence the Risk Engine accepts for a
streaming strategy, with Benjamini–Hochberg control across all strategies being tested.

``expected_gross_edge`` adds back only the fees: the spread and slippage the shadow trades
already paid are subtracted again by the Risk Engine with live values (conservative).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from aqt.risk.models import StrategyEvidence
from aqt.statistics.confidence import mean_return_test
from aqt.statistics.edge import compute_edge_score
from aqt.statistics.multiple_testing import benjamini_hochberg


@dataclass(frozen=True)
class EvidenceRow:
    strategy_id: str
    n_trades: int
    win_rate: float
    mean_net_return: float
    p_value: float
    adjusted_p_value: float
    confidence: float
    edge_score: float
    evidence: StrategyEvidence | None

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "n_trades": self.n_trades,
            "win_rate": self.win_rate,
            "mean_net_return": self.mean_net_return,
            "p_value": self.p_value,
            "adjusted_p_value": self.adjusted_p_value,
            "confidence": self.confidence,
            "edge_score": self.edge_score,
        }


class EvidenceTracker:
    """Rolling window of shadow trade returns per strategy."""

    def __init__(
        self,
        strategy_ids: Iterable[str],
        fees_round_trip_pct: float,
        window: int = 500,
        min_trades: int = 30,
    ) -> None:
        self.fees_round_trip_pct = fees_round_trip_pct
        self.min_trades = min_trades
        self.window = window
        self._returns: dict[str, deque[float]] = {sid: deque(maxlen=window) for sid in strategy_ids}
        self._cache: dict[str, EvidenceRow] | None = None

    @property
    def strategy_ids(self) -> list[str]:
        return list(self._returns)

    def add(self, strategy_id: str, returns: Iterable[float] = ()) -> None:
        """Track a new strategy (hot-loaded rule), optionally with its stored forward history."""
        if strategy_id not in self._returns:
            self._returns[strategy_id] = deque(returns, maxlen=self.window)
            self._cache = None

    def remove(self, strategy_id: str) -> None:
        if self._returns.pop(strategy_id, None) is not None:
            self._cache = None

    def record(self, strategy_id: str, net_return: float) -> None:
        if strategy_id not in self._returns:
            raise KeyError(f"unknown strategy {strategy_id}")
        self._returns[strategy_id].append(float(net_return))
        self._cache = None

    def returns(self, strategy_id: str) -> list[float]:
        return list(self._returns[strategy_id])

    def cumulative_return(self, strategy_id: str) -> float:
        """Compounded return of the window if every signal had been traded with all the capital
        — what trading *without* the evidence filter would have done."""
        return float(np.prod(1.0 + np.asarray(self._returns[strategy_id])) - 1.0)

    def table(self) -> dict[str, EvidenceRow]:
        if self._cache is not None:
            return self._cache
        ids = self.strategy_ids
        raw_p = np.array(
            [
                mean_return_test(np.asarray(self._returns[s])).p_value
                if len(self._returns[s]) >= 2
                else 1.0
                for s in ids
            ],
            dtype=float,
        )
        _, adj = benjamini_hochberg(raw_p)
        out: dict[str, EvidenceRow] = {}
        for sid, p, ap in zip(ids, raw_p, adj, strict=True):
            r = np.asarray(self._returns[sid], dtype=float)
            n = int(r.size)
            es = compute_edge_score(r, p_value=float(ap), min_trades=self.min_trades)
            ev: StrategyEvidence | None = None
            if n >= 2:
                wins, losses = r[r > 0], r[r <= 0]
                ev = StrategyEvidence(
                    strategy_id=sid,
                    edge_score=es.score,
                    p_win=es.p_win,
                    avg_win=float(wins.mean()) if wins.size else 0.0,
                    avg_loss=float(-losses.mean()) if losses.size else 0.0,
                    expected_gross_edge=float(r.mean()) + self.fees_round_trip_pct,
                    confidence=es.confidence,
                    n_trades=n,
                    fees_round_trip_pct=self.fees_round_trip_pct,
                )
            out[sid] = EvidenceRow(
                strategy_id=sid,
                n_trades=n,
                win_rate=float((r > 0).mean()) if n else 0.0,
                mean_net_return=float(r.mean()) if n else 0.0,
                p_value=float(p),
                adjusted_p_value=float(ap),
                confidence=es.confidence,
                edge_score=es.score,
                evidence=ev,
            )
        self._cache = out
        return out

    def evidence(self, strategy_id: str) -> StrategyEvidence | None:
        row = self.table().get(strategy_id)
        return row.evidence if row else None
