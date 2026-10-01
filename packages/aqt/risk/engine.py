"""Risk Engine — deterministic, no LLM, last gate before any order.

``evaluate`` returns exactly one of APPROVE, REJECT or ADJUST_SIZE. If any hard check
fails the trade is rejected. Every check result is returned for the audit log, including
for rejected trades.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from aqt.common.types import OrderSide
from aqt.risk.models import MarketState, Portfolio, Signal, StrategyEvidence
from aqt.risk.profile import ABSOLUTE_LIMITS, AbsoluteLimits, RiskProfile
from aqt.sizing import PositionSizingEngine, SizingResult


class RiskAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ADJUST_SIZE = "ADJUST_SIZE"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class RiskDecision:
    action: RiskAction
    quantity: float = 0.0
    notional: float = 0.0
    requested_notional: float = 0.0
    checks: tuple[CheckResult, ...] = ()
    sizing: SizingResult | None = None
    adjustments: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.action is not RiskAction.REJECT

    @property
    def reasons(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]


@dataclass
class _Checks:
    items: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append(CheckResult(name, bool(ok), detail))

    @property
    def failed(self) -> bool:
        return any(not c.passed for c in self.items)


@dataclass(frozen=True)
class RiskEngine:
    profile: RiskProfile
    limits: AbsoluteLimits = ABSOLUTE_LIMITS
    sizer: PositionSizingEngine = field(default_factory=PositionSizingEngine)

    def evaluate(
        self,
        portfolio: Portfolio,
        signal: Signal,
        market: MarketState,
        evidence: StrategyEvidence | None,
        *,
        kill_switch: bool = False,
    ) -> RiskDecision:
        p = self.profile
        chk = _Checks()

        # --- System / operational gates (apply to every order) -------------------------
        chk.add("kill_switch", not kill_switch, "global kill switch engaged" if kill_switch else "")
        chk.add(
            "api_health", market.api_healthy, "" if market.api_healthy else "broker API unhealthy"
        )
        chk.add(
            "reconciliation",
            portfolio.reconciled,
            "" if portfolio.reconciled else "local portfolio does not match broker",
        )
        age = market.data_age_seconds
        max_age = min(p.max_data_age_seconds, self.limits.max_data_age_seconds)
        chk.add("stale_data", 0 <= age <= max_age, f"data age {age:.0f}s (max {max_age:.0f}s)")
        chk.add("trading_hours", market.market_open, "" if market.market_open else "market closed")
        dup = signal.idempotency_key in portfolio.pending_order_keys
        chk.add("duplicate_order", not dup, "identical order already pending" if dup else "")
        chk.add("symbol_match", market.symbol == signal.symbol, "market state / signal mismatch")
        quote_ok = market.bid > 0 and market.ask >= market.bid
        chk.add("valid_quote", quote_ok, f"bid={market.bid} ask={market.ask}")

        # --- Exits: risk-reducing sells skip edge/exposure checks; shorts are forbidden ---
        held = portfolio.positions.get(signal.symbol)
        if signal.side is OrderSide.SELL:
            has_pos = held is not None and held.quantity > 0
            chk.add("no_short_selling", has_pos, "" if has_pos else "sell without position (short)")
            if chk.failed or held is None:
                return RiskDecision(RiskAction.REJECT, checks=tuple(chk.items))
            return RiskDecision(
                RiskAction.APPROVE,
                quantity=held.quantity,
                notional=held.quantity * market.bid,
                requested_notional=held.quantity * market.bid,
                checks=tuple(chk.items),
            )

        # --- Portfolio state --------------------------------------------------------------
        daily = portfolio.daily_pnl_pct
        chk.add(
            "max_daily_loss",
            daily > -p.max_daily_loss,
            f"daily P&L {daily:.2%} (limit -{p.max_daily_loss:.2%})",
        )
        dd = portfolio.drawdown
        chk.add(
            "max_drawdown", dd > -p.max_drawdown, f"drawdown {dd:.2%} (limit -{p.max_drawdown:.2%})"
        )
        cl = portfolio.consecutive_losses
        chk.add(
            "consecutive_losses",
            cl < p.max_consecutive_losses,
            f"{cl} consecutive losses (limit {p.max_consecutive_losses})",
        )
        n_pos = sum(1 for x in portfolio.positions.values() if x.quantity > 0)
        new_symbol = held is None or held.quantity <= 0
        pos_ok = not new_symbol or n_pos < p.max_positions
        chk.add("max_positions", pos_ok, f"{n_pos} open positions (limit {p.max_positions})")

        # --- Market quality ---------------------------------------------------------------
        spread = market.spread_pct
        chk.add(
            "max_spread",
            spread <= p.max_spread_pct,
            f"spread {spread:.4%} (max {p.max_spread_pct:.4%})",
        )
        slip = market.expected_slippage_pct
        chk.add(
            "max_slippage",
            slip <= p.max_slippage_pct,
            f"slippage {slip:.4%} (max {p.max_slippage_pct:.4%})",
        )
        chk.add("min_liquidity", market.avg_daily_volume > 0, f"ADV {market.avg_daily_volume:.0f}")

        # --- Statistical evidence -----------------------------------------------------------
        if evidence is None:
            chk.add("evidence", False, "no validated strategy evidence")
        else:
            chk.add(
                "evidence_strategy",
                evidence.strategy_id == signal.strategy_id,
                "evidence belongs to a different strategy",
            )
            chk.add(
                "min_edge_score",
                evidence.edge_score >= p.min_edge_score,
                f"edge score {evidence.edge_score:.1f} (min {p.min_edge_score:.1f})",
            )
            chk.add(
                "min_confidence",
                evidence.confidence >= p.min_confidence,
                f"confidence {evidence.confidence:.3f} (min {p.min_confidence:.3f})",
            )
            net_edge = (
                evidence.expected_gross_edge - spread - 2 * slip - evidence.fees_round_trip_pct
            )
            chk.add(
                "min_expected_net_edge",
                net_edge >= p.min_expected_net_edge,
                f"expected net edge {net_edge:.4%} (min {p.min_expected_net_edge:.4%})",
            )

        # --- Stop sanity --------------------------------------------------------------------
        stop_ok = 0 < signal.stop_price < min(signal.entry_price, market.ask)
        chk.add(
            "valid_stop",
            stop_ok,
            f"entry={signal.entry_price} ask={market.ask} stop={signal.stop_price}",
        )

        if chk.failed or evidence is None or not stop_ok:
            return RiskDecision(RiskAction.REJECT, checks=tuple(chk.items))

        # --- Sizing and caps ---------------------------------------------------------------
        equity = portfolio.equity
        sizing = self.sizer.size(
            equity=equity,
            entry_price=market.ask,
            stop_price=signal.stop_price,
            p_win=evidence.p_win,
            avg_win=evidence.avg_win,
            avg_loss=evidence.avg_loss,
            risk_per_trade=p.risk_per_trade,
            kelly_coefficient=p.kelly_coefficient,
        )
        requested = sizing.notional
        notional = requested
        adjustments: list[str] = []

        existing_value = held.market_value if held is not None else 0.0
        caps = {
            "max_position_pct": equity * p.max_position_pct - existing_value,
            "max_portfolio_exposure": equity * p.max_portfolio_exposure - portfolio.positions_value,
            "cash_reserve": portfolio.cash - equity * p.cash_reserve,
            "liquidity": market.avg_daily_volume * market.ask * p.max_adv_participation,
        }
        for name, cap in caps.items():
            if notional > cap:
                notional = max(cap, 0.0)
                adjustments.append(name)

        step = market.quantity_step
        quantity = math.floor(notional / market.ask / step) * step if market.ask > 0 else 0.0
        notional = quantity * market.ask
        if notional < max(p.min_order_notional, self.limits.min_order_notional):
            chk.add(
                "min_order_notional",
                False,
                f"final size {notional:.2f} below minimum "
                f"(limited by {adjustments or [sizing.limiting_factor]})",
            )
            return RiskDecision(
                RiskAction.REJECT,
                requested_notional=requested,
                checks=tuple(chk.items),
                sizing=sizing,
                adjustments=tuple(adjustments),
            )

        # Defence in depth: the resulting loss at stop can never exceed the absolute cap.
        loss_at_stop = quantity * (market.ask - signal.stop_price)
        hard_cap = equity * min(p.risk_per_trade, self.limits.max_risk_per_trade) * (1 + 1e-9)
        chk.add(
            "max_risk_per_trade",
            loss_at_stop <= hard_cap,
            f"loss at stop {loss_at_stop:.2f} (max {hard_cap:.2f})",
        )
        if chk.failed:
            return RiskDecision(RiskAction.REJECT, checks=tuple(chk.items), sizing=sizing)

        action = RiskAction.ADJUST_SIZE if adjustments else RiskAction.APPROVE
        return RiskDecision(
            action,
            quantity=quantity,
            notional=notional,
            requested_notional=requested,
            checks=tuple(chk.items),
            sizing=sizing,
            adjustments=tuple(adjustments),
        )
