"""Transaction-cost model. With a 100 € account fixed fees and spreads dominate."""

from __future__ import annotations

from dataclasses import dataclass

T212_FX_FEE = 0.0015  # per side, published Trading 212 currency conversion fee


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

    @classmethod
    def trading212(
        cls,
        instrument_currency: str,
        account_currency: str = "EUR",
        spread_pct: float = 0.001,
        slippage_pct: float = 0.0005,
    ) -> CostModel:
        """Trading 212 Invest: no commission, 0.15 % FX per side when currencies differ.

        Spread/slippage defaults are deliberately conservative for small retail orders.
        Fees must be re-verified against the broker's current price list before going live.
        """
        fx = T212_FX_FEE if instrument_currency.upper() != account_currency.upper() else 0.0
        return cls(
            fee_pct=0.0,
            fee_fixed=0.0,
            spread_pct=spread_pct,
            slippage_pct=slippage_pct,
            fx_pct=fx,
        )
