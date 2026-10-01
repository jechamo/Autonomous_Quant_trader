"""Risk profiles and the aggressiveness slider.

The slider (0–100) never maps directly to "% of money invested". It interpolates every risk
parameter at once, and the result is always clamped by :data:`ABSOLUTE_LIMITS`, which no
setting can override.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class AbsoluteLimits:
    max_risk_per_trade: float = 0.02
    max_position_pct: float = 0.40
    max_portfolio_exposure: float = 1.0  # 1.0 == no leverage, ever
    max_drawdown: float = 0.30
    max_daily_loss: float = 0.05
    max_positions: int = 10
    max_kelly_coefficient: float = 0.5
    min_cash_reserve: float = 0.05
    max_consecutive_losses: int = 10
    min_edge_score: float = 10.0
    min_confidence: float = 0.75
    min_expected_net_edge: float = 0.0005
    max_spread_pct: float = 0.01
    max_slippage_pct: float = 0.01
    max_data_age_seconds: float = 3600.0
    max_adv_participation: float = 0.01
    min_order_notional: float = 1.0
    allow_short: bool = False
    allow_margin: bool = False


ABSOLUTE_LIMITS = AbsoluteLimits()


@dataclass(frozen=True)
class RiskProfile:
    aggressiveness: float
    risk_per_trade: float
    max_position_pct: float
    max_portfolio_exposure: float
    min_edge_score: float
    min_confidence: float
    min_expected_net_edge: float
    max_drawdown: float
    max_daily_loss: float
    max_positions: int
    max_consecutive_losses: int
    kelly_coefficient: float
    cash_reserve: float
    max_spread_pct: float
    max_slippage_pct: float
    max_data_age_seconds: float = 900.0
    max_adv_participation: float = 0.005
    min_order_notional: float = 1.0

    def __post_init__(self) -> None:
        violations = _violations(self, ABSOLUTE_LIMITS)
        if violations:
            raise ValueError(f"RiskProfile breaches absolute limits: {violations}")

    @classmethod
    def from_aggressiveness(
        cls, level: float, limits: AbsoluteLimits = ABSOLUTE_LIMITS
    ) -> RiskProfile:
        if not 0 <= level <= 100:
            raise ValueError("aggressiveness must be in [0, 100]")
        t = level / 100.0

        def lerp(a: float, b: float) -> float:
            return a + (b - a) * t

        raw: dict[str, Any] = {
            "aggressiveness": float(level),
            "risk_per_trade": lerp(0.0025, 0.02),
            "max_position_pct": lerp(0.10, 0.35),
            "max_portfolio_exposure": lerp(0.30, 0.90),
            "min_edge_score": lerp(60.0, 20.0),
            "min_confidence": lerp(0.95, 0.80),
            "min_expected_net_edge": lerp(0.004, 0.001),
            "max_drawdown": lerp(0.08, 0.25),
            "max_daily_loss": lerp(0.01, 0.04),
            "max_positions": round(lerp(2, 8)),
            "max_consecutive_losses": round(lerp(3, 8)),
            "kelly_coefficient": lerp(0.10, 0.50),
            "cash_reserve": lerp(0.50, 0.10),
            "max_spread_pct": lerp(0.002, 0.006),
            "max_slippage_pct": lerp(0.002, 0.005),
        }
        return cls(**_clamp(raw, limits))

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


# (profile field, limit field, kind) — "max": profile <= limit; "min": profile >= limit.
_BOUNDS: tuple[tuple[str, str, str], ...] = (
    ("risk_per_trade", "max_risk_per_trade", "max"),
    ("max_position_pct", "max_position_pct", "max"),
    ("max_portfolio_exposure", "max_portfolio_exposure", "max"),
    ("max_drawdown", "max_drawdown", "max"),
    ("max_daily_loss", "max_daily_loss", "max"),
    ("max_positions", "max_positions", "max"),
    ("kelly_coefficient", "max_kelly_coefficient", "max"),
    ("cash_reserve", "min_cash_reserve", "min"),
    ("max_consecutive_losses", "max_consecutive_losses", "max"),
    ("min_edge_score", "min_edge_score", "min"),
    ("min_confidence", "min_confidence", "min"),
    ("min_expected_net_edge", "min_expected_net_edge", "min"),
    ("max_spread_pct", "max_spread_pct", "max"),
    ("max_slippage_pct", "max_slippage_pct", "max"),
    ("max_data_age_seconds", "max_data_age_seconds", "max"),
    ("max_adv_participation", "max_adv_participation", "max"),
    ("min_order_notional", "min_order_notional", "min"),
)


def _clamp(raw: dict[str, Any], limits: AbsoluteLimits) -> dict[str, Any]:
    out = dict(raw)
    for pf, lf, kind in _BOUNDS:
        if pf not in out:
            continue
        lim = getattr(limits, lf)
        out[pf] = min(out[pf], lim) if kind == "max" else max(out[pf], lim)
    return out


def _violations(profile: RiskProfile, limits: AbsoluteLimits) -> list[str]:
    errs = []
    names = {f.name for f in fields(profile)}
    for pf, lf, kind in _BOUNDS:
        if pf not in names:
            continue
        v, lim = getattr(profile, pf), getattr(limits, lf)
        if (kind == "max" and v > lim + 1e-12) or (kind == "min" and v < lim - 1e-12):
            errs.append(f"{pf}={v} vs {kind} {lim}")
    if not profile.risk_per_trade > 0:
        errs.append("risk_per_trade must be > 0")
    if not 0 <= profile.cash_reserve < 1:
        errs.append("cash_reserve must be in [0, 1)")
    if profile.max_positions < 1:
        errs.append("max_positions must be >= 1")
    return errs
