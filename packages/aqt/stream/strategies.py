"""High-turnover intraday strategies for the streaming engine (long-only, spot).

A strategy only proposes an *entry intent* with a volatility-scaled stop and target. It never
sizes or sends orders: the engine turns intents into ``Signal`` objects that the Risk Engine
approves or rejects.

Cost awareness is enforced by the engine through :meth:`StreamStrategy.clears_costs`: an intent
whose target is below ``min_cost_multiple`` × the live round-trip cost (fees + spread +
slippage) is counted as *blocked by costs* and never traded, not even in the shadow book.

The catalog tests the same ideas over several holding horizons, because the horizon decides
whether a move is large enough to pay the fees: with 0.10 % per side, one-minute scalps on a
calm BTC rarely do, twenty-minute moves often can. FDR is controlled across all of them.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aqt.stream.bars import Bar
from aqt.stream.features import FeatureParams, FeatureSnapshot


@dataclass(frozen=True)
class EntryIntent:
    strategy_id: str
    symbol: str
    ts: float
    stop_pct: float
    target_pct: float
    max_hold_bars: int
    reason: str
    # What the market looked like at the decision (features). Stored with the trade so the lab
    # can learn which contexts end in wins and which in losses (meta-labeling).
    context: Mapping[str, float] | None = None


class StreamStrategy(ABC):
    strategy_id: str
    description: str = ""
    min_cost_multiple: float = 2.0
    # Feature time scale for this strategy; None = the engine default. A 20-minute idea must not
    # be judged (or exited) on a 1-minute trend.
    features: FeatureParams | None = None

    @abstractmethod
    def entry(self, f: FeatureSnapshot) -> EntryIntent | None: ...

    def should_exit(self, f: FeatureSnapshot) -> bool:  # pragma: no cover - default
        return False

    def on_bar(self, bar: Bar) -> None:  # noqa: B027 - optional hook
        """Called with every closed engine bar before any decision (e.g. to build longer bars)."""

    def clears_costs(self, intent: EntryIntent, round_trip_cost: float) -> bool:
        return intent.target_pct >= self.min_cost_multiple * round_trip_cost


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


@dataclass
class MicroMomentum(StreamStrategy):
    """Order-flow momentum: trend up + aggressive buying + (optional) local breakout."""

    strategy_id: str = "micro_momentum"
    horizon_bars: int = 24
    ofi_min: float = 0.25
    stop_mult: float = 1.5
    target_mult: float = 2.5
    require_breakout: bool = True
    min_cost_multiple: float = 2.0
    min_stop: float = 0.0015
    max_stop: float = 0.02
    features: FeatureParams | None = None
    description: str = "EMA trend + order-flow imbalance + breakout, vol-scaled stop/target"

    def entry(self, f: FeatureSnapshot) -> EntryIntent | None:
        if not f.ready:
            return None
        if not (f.ema_fast > f.ema_slow and f.momentum > 0):
            return None
        if f.order_flow_imbalance < self.ofi_min or f.book_imbalance < -0.5:
            return None
        if self.require_breakout and not f.breakout:
            return None
        scale = f.sigma * math.sqrt(self.horizon_bars)
        return EntryIntent(
            self.strategy_id,
            f.symbol,
            f.ts,
            _clamp(self.stop_mult * scale, self.min_stop, self.max_stop),
            self.target_mult * scale,
            self.horizon_bars * 2,
            f"ofi={f.order_flow_imbalance:.2f} mom={f.momentum:.4%} breakout={f.breakout}",
        )

    def should_exit(self, f: FeatureSnapshot) -> bool:
        return f.ema_fast < f.ema_slow and f.order_flow_imbalance < 0


@dataclass
class MicroReversion(StreamStrategy):
    """Buy a stretched dip once selling pressure is exhausted; target the rolling mean."""

    strategy_id: str = "micro_reversion"
    z_entry: float = 2.0
    horizon_bars: int = 24
    stop_mult: float = 2.0
    ofi_floor: float = -0.2
    min_cost_multiple: float = 2.0
    min_stop: float = 0.0015
    max_stop: float = 0.02
    features: FeatureParams | None = None
    description: str = "z-score dip + exhausted selling + bid-side book, target = rolling mean"

    def entry(self, f: FeatureSnapshot) -> EntryIntent | None:
        if not f.ready or f.zscore > -self.z_entry:
            return None
        if f.order_flow_imbalance < self.ofi_floor or f.book_imbalance < 0:
            return None  # sellers still aggressive, or the book leans to the ask side
        scale = f.sigma * math.sqrt(self.horizon_bars)
        return EntryIntent(
            self.strategy_id,
            f.symbol,
            f.ts,
            _clamp(self.stop_mult * scale, self.min_stop, self.max_stop),
            (f.rolling_mean - f.close) / f.close,
            self.horizon_bars * 2,
            f"z={f.zscore:.2f} ofi={f.order_flow_imbalance:.2f} book={f.book_imbalance:.2f}",
        )

    def should_exit(self, f: FeatureSnapshot) -> bool:
        return f.zscore >= 0


def default_stream_strategies(bar_seconds: float = 5.0) -> list[StreamStrategy]:
    """The hypotheses tested in parallel (FDR is controlled across all of them).

    Horizons are expressed in minutes and converted to bars, so the catalog means the same thing
    whatever the bar size.
    """

    def bars(minutes: float) -> int:
        return max(2, round(minutes * 60 / bar_seconds))

    def momentum(sid: str, minutes: float, **kw: Any) -> MicroMomentum:
        h = bars(minutes)
        return MicroMomentum(sid, horizon_bars=h, features=scaled_features(h), **kw)

    def reversion(sid: str, minutes: float, **kw: Any) -> MicroReversion:
        h = bars(minutes)
        return MicroReversion(sid, horizon_bars=h, features=scaled_features(h), **kw)

    return [
        momentum("momentum_1m", 1),
        momentum("momentum_5m", 5),
        momentum("momentum_20m", 20, require_breakout=False),
        reversion("reversion_2z_2m", 2, z_entry=2.0),
        reversion("reversion_3z_10m", 10, z_entry=3.0),
    ]


def scaled_features(horizon_bars: int) -> FeatureParams:
    """Indicator windows proportional to the holding horizon (trend ≈ horizon, fast ≈ ¼)."""
    h = horizon_bars
    return FeatureParams(
        fast_span=max(3, h // 4),
        slow_span=max(6, h),
        vol_span=max(60, h),
        zscore_window=max(20, h),
        flow_window=max(6, h // 4),
        momentum_bars=max(2, h // 4),
        breakout_bars=max(4, h // 2),
    )
