"""Inputs to the Risk Engine. Pure data, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from aqt.common.types import OrderSide


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float
    avg_price: float
    market_price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price


@dataclass(frozen=True)
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    equity_peak: float = 0.0
    day_start_equity: float = 0.0
    consecutive_losses: int = 0
    pending_order_keys: frozenset[str] = frozenset()
    reconciled: bool = True  # local book matches broker

    @property
    def positions_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def equity(self) -> float:
        return self.cash + self.positions_value

    @property
    def exposure_pct(self) -> float:
        eq = self.equity
        return self.positions_value / eq if eq > 0 else 0.0

    @property
    def drawdown(self) -> float:
        """Current drawdown from peak as a negative fraction."""
        peak = max(self.equity_peak, self.equity)
        return self.equity / peak - 1.0 if peak > 0 else 0.0

    @property
    def daily_pnl_pct(self) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return self.equity / self.day_start_equity - 1.0


@dataclass(frozen=True)
class Signal:
    signal_id: str
    strategy_id: str
    symbol: str
    side: OrderSide
    entry_price: float
    stop_price: float
    created_at: datetime
    target_price: float | None = None

    @property
    def idempotency_key(self) -> str:
        return f"{self.strategy_id}:{self.symbol}:{self.side}:{self.signal_id}"


@dataclass(frozen=True)
class MarketState:
    symbol: str
    last_data_at: datetime
    now: datetime
    bid: float
    ask: float
    avg_daily_volume: float  # shares
    expected_slippage_pct: float = 0.0005
    market_open: bool = True
    api_healthy: bool = True
    quantity_step: float = 1e-6  # fractional shares

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        return (self.ask - self.bid) / self.mid if self.mid > 0 else float("inf")

    @property
    def data_age_seconds(self) -> float:
        return (self.now - self.last_data_at).total_seconds()


@dataclass(frozen=True)
class StrategyEvidence:
    strategy_id: str
    edge_score: float
    p_win: float
    avg_win: float
    avg_loss: float
    expected_gross_edge: float  # per trade, before costs
    confidence: float  # 1 - adjusted p-value
    n_trades: int
    regime_compatibility: float = 1.0
    fees_round_trip_pct: float = 0.003  # broker fees + FX, both sides
