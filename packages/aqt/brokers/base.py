"""BrokerAdapter: the only door to a broker. Strategies and the AI never touch it directly."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aqt.common.types import OrderSide, OrderStatus, OrderType


class BrokerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountBalance:
    cash: float
    equity: float
    currency: str = "EUR"


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    quantity: float
    avg_price: float
    market_price: float


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    currency: str
    fractional: bool = True
    min_quantity: float = 1e-6


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: float
    client_order_id: str  # idempotency key
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None


@dataclass(frozen=True)
class BrokerOrder:
    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    status: OrderStatus
    filled_quantity: float = 0.0
    avg_fill_price: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class BrokerHealth:
    ok: bool
    latency_ms: float | None = None
    detail: str = ""


class BrokerAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def get_balance(self) -> AccountBalance: ...

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]: ...

    @abstractmethod
    def get_orders(self) -> list[BrokerOrder]: ...

    @abstractmethod
    def place_order(self, request: OrderRequest) -> BrokerOrder: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> BrokerOrder: ...

    @abstractmethod
    def get_instruments(self) -> list[Instrument]: ...

    @abstractmethod
    def health(self) -> BrokerHealth: ...
