"""Position Sizing Engine.

Flow: edge -> EV -> confidence -> volatility/stop distance -> fractional Kelly -> risk limits.
Size is derived from *capital at risk*, never from a fixed "always invest X %".

    capital 500 €, risk/trade 1 % -> max loss 5 €
    stop 4 %  -> position = 5 / 0.04 = 125 €
    stop 10 % -> position = 5 / 0.10 =  50 €
"""

from __future__ import annotations

from dataclasses import dataclass


def kelly_fraction(p_win: float, avg_win: float, avg_loss: float) -> float:
    """Full Kelly fraction ``p - q / b`` (b = payoff ratio). Never negative."""
    if not 0.0 <= p_win <= 1.0:
        raise ValueError("p_win must be in [0, 1]")
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0
    b = avg_win / avg_loss
    return max(0.0, p_win - (1.0 - p_win) / b)


@dataclass(frozen=True)
class SizingResult:
    notional: float
    risk_based_notional: float
    kelly_notional: float
    full_kelly: float
    stop_distance_pct: float
    max_loss: float
    limiting_factor: str


@dataclass(frozen=True)
class PositionSizingEngine:
    def size(
        self,
        *,
        equity: float,
        entry_price: float,
        stop_price: float,
        p_win: float,
        avg_win: float,
        avg_loss: float,
        risk_per_trade: float,
        kelly_coefficient: float,
    ) -> SizingResult:
        if equity <= 0:
            raise ValueError("equity must be > 0")
        if entry_price <= 0 or stop_price <= 0:
            raise ValueError("prices must be > 0")
        if stop_price >= entry_price:
            raise ValueError("long stop must be below entry")
        if not 0 < risk_per_trade < 1:
            raise ValueError("risk_per_trade must be in (0, 1)")
        if not 0 <= kelly_coefficient <= 1:
            raise ValueError("kelly_coefficient must be in [0, 1]")

        stop_dist = (entry_price - stop_price) / entry_price
        risk_notional = equity * risk_per_trade / stop_dist
        full_kelly = kelly_fraction(p_win, avg_win, avg_loss)
        kelly_notional = equity * full_kelly * kelly_coefficient

        if kelly_notional < risk_notional:
            notional, factor = kelly_notional, "fractional_kelly"
        else:
            notional, factor = risk_notional, "risk_per_trade"
        return SizingResult(
            notional=notional,
            risk_based_notional=risk_notional,
            kelly_notional=kelly_notional,
            full_kelly=full_kelly,
            stop_distance_pct=stop_dist,
            max_loss=notional * stop_dist,
            limiting_factor=factor,
        )
