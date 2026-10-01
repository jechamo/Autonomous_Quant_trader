"""Per-regime performance breakdown."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np

from aqt.backtest.engine import Trade
from aqt.statistics.metrics import compute_metrics


def metrics_by_regime(trades: Sequence[Trade]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        buckets[t.regime or "unknown"].append(t.net_return)
    out: dict[str, dict[str, Any]] = {}
    for regime, rets in sorted(buckets.items()):
        m = compute_metrics(np.array(rets))
        out[regime] = {
            "n_trades": m.n_trades,
            "win_rate": m.win_rate,
            "expected_value": m.expected_value,
            "profit_factor": m.profit_factor if np.isfinite(m.profit_factor) else None,
        }
    return out
