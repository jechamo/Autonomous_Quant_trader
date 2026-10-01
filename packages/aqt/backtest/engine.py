"""Array-based, long-only, single-position backtester.

Timing (no look-ahead):
  * signals are evaluated on the close of bar ``t``;
  * entries / signal exits fill at the open of bar ``t+1``;
  * stops and targets are checked intrabar; if both are touched in the same bar, the stop
    is assumed to fill first (conservative); gaps through a level fill at the open.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from aqt.backtest.costs import CostModel
from aqt.strategies.dsl import StrategySpec


@dataclass(frozen=True)
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_price: float
    gross_return: float
    net_return: float
    bars_held: int
    exit_reason: str
    regime: str | None

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["entry_time"] = self.entry_time.isoformat()
        d["exit_time"] = self.exit_time.isoformat()
        return d


@dataclass
class BacktestResult:
    strategy: str
    trades: list[Trade]
    bar_returns: pd.Series
    exposure: pd.Series
    signals: pd.Series
    cost_model: CostModel = field(default_factory=CostModel)

    @property
    def equity(self) -> pd.Series:
        return (1.0 + self.bar_returns).cumprod()

    @property
    def trade_returns(self) -> np.ndarray:
        return np.array([t.net_return for t in self.trades], dtype=float)

    @property
    def gross_trade_returns(self) -> np.ndarray:
        return np.array([t.gross_return for t in self.trades], dtype=float)

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([t.to_dict() for t in self.trades])


def _num(x: object) -> float | None:
    return None if x is None else float(x)  # type: ignore[arg-type]


def run_backtest(
    features: pd.DataFrame,
    spec: StrategySpec,
    costs: CostModel | None = None,
    notional: float = 100.0,
) -> BacktestResult:
    costs = costs or CostModel()
    spec = spec.render()
    ex = spec.exit
    stop_atr, target_atr = _num(ex.stop_atr_mult), _num(ex.target_atr_mult)
    stop_pct, target_pct = _num(ex.stop_pct), _num(ex.target_pct)
    max_hold_f = _num(ex.max_holding_bars)
    max_hold = int(max_hold_f) if max_hold_f is not None else None

    entry_sig = spec.entry.evaluate(features).to_numpy()
    exit_sig_s = spec.exit_signal(features)
    exit_sig = exit_sig_s.to_numpy() if exit_sig_s is not None else np.zeros(len(features), bool)

    o = features["open"].to_numpy(float)
    h = features["high"].to_numpy(float)
    lo = features["low"].to_numpy(float)
    c = features["close"].to_numpy(float)
    atr_arr = (
        features["atr"].to_numpy(float) if "atr" in features else np.full(len(features), np.nan)
    )
    regimes = features["regime"].to_numpy() if "regime" in features else None
    idx = features.index
    n = len(features)

    side_cost = costs.side_cost_pct(notional)
    bar_ret = np.zeros(n)
    exposure = np.zeros(n)
    trades: list[Trade] = []

    in_pos = False
    entry_i = 0
    entry_raw = entry_eff = stop = target = 0.0
    prev_mark = 0.0

    def close_trade(i: int, raw_px: float, reason: str) -> None:
        nonlocal in_pos
        exit_eff = costs.sell_price(raw_px) * (1.0 - side_cost)
        bar_ret[i] += exit_eff / prev_mark - 1.0
        gross = raw_px / entry_raw - 1.0
        net = exit_eff / entry_eff - 1.0
        reg = regimes[entry_i - 1] if regimes is not None and entry_i > 0 else None
        trades.append(
            Trade(
                entry_time=idx[entry_i],
                exit_time=idx[i],
                entry_price=entry_raw,
                exit_price=raw_px,
                stop_price=stop,
                gross_return=float(gross),
                net_return=float(net),
                bars_held=i - entry_i + 1,
                exit_reason=reason,
                regime=None
                if reg is None or (isinstance(reg, float) and np.isnan(reg))
                else str(reg),
            )
        )
        in_pos = False

    for i in range(1, n):
        if in_pos:
            # Exits decided on the previous close fill at this open.
            held = i - entry_i
            if exit_sig[i - 1] or (max_hold is not None and held >= max_hold):
                close_trade(i, o[i], "signal" if exit_sig[i - 1] else "max_holding")
                exposure[i] = 0.0
                continue

        if not in_pos and entry_sig[i - 1]:
            ref_atr = atr_arr[i - 1]
            stops = []
            if stop_atr is not None and np.isfinite(ref_atr):
                stops.append(o[i] - stop_atr * ref_atr)
            if stop_pct is not None:
                stops.append(o[i] * (1.0 - stop_pct))
            if not stops:  # ATR not yet available -> cannot size the risk -> skip
                continue
            in_pos = True
            entry_i = i
            entry_raw = o[i]
            entry_eff = costs.buy_price(o[i]) * (1.0 + side_cost)
            stop = max(stops)
            targets = []
            if target_atr is not None and np.isfinite(ref_atr):
                targets.append(o[i] + target_atr * ref_atr)
            if target_pct is not None:
                targets.append(o[i] * (1.0 + target_pct))
            target = min(targets) if targets else np.inf
            prev_mark = entry_eff

        if in_pos:
            exposure[i] = 1.0
            if lo[i] <= stop:
                close_trade(i, min(o[i], stop) if i != entry_i else stop, "stop")
                continue
            if h[i] >= target:
                close_trade(i, max(o[i], target) if i != entry_i else target, "target")
                continue
            if i == n - 1:
                close_trade(i, c[i], "end_of_data")
                continue
            bar_ret[i] += c[i] / prev_mark - 1.0
            prev_mark = c[i]

    return BacktestResult(
        strategy=spec.name,
        trades=trades,
        bar_returns=pd.Series(bar_ret, index=idx, name="strategy_return"),
        exposure=pd.Series(exposure, index=idx, name="exposure"),
        signals=pd.Series(entry_sig, index=idx, name="entry_signal"),
        cost_model=costs,
    )
