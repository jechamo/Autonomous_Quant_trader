"""Transaction-cost model. With a 100 € account fixed fees and spreads dominate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    fee_pct: float = 0.0  # proportional commission per side
    fee_fixed: float = 0.0  # fixed commission per side, in account currency
    spread_pct: float = 0.0005  # full bid/ask spread; half is paid per side
    slippage_pct: float = 0.0005  # per side
    fx_pct: float = 0.0015  # FX conversion per side (e.g. EUR account buying USD stocks)

    def __post_init__(self) -> None:
        for name in ("fee_pct", "fee_fixed", "spread_pct", "slippage_pct", "fx_pct"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")

    def buy_price(self, price: float) -> float:
        return price * (1.0 + self.spread_pct / 2.0 + self.slippage_pct)

    def sell_price(self, price: float) -> float:
        return price * (1.0 - self.spread_pct / 2.0 - self.slippage_pct)

    def side_cost_pct(self, notional: float) -> float:
        fixed = self.fee_fixed / notional if notional > 0 else 0.0
        return self.fee_pct + self.fx_pct + fixed

    def round_trip_pct(self, notional: float) -> float:
        """Approximate total round-trip cost as a fraction of notional."""
        return self.spread_pct + 2 * self.slippage_pct + 2 * self.side_cost_pct(notional)

    @classmethod
    def zero(cls) -> CostModel:
        return cls(0.0, 0.0, 0.0, 0.0, 0.0)
