"""In-memory broker for tests, shadow portfolios and offline paper simulations."""

from __future__ import annotations

import itertools
from collections.abc import Mapping

from aqt.brokers.base import (
    AccountBalance,
    BrokerAdapter,
    BrokerError,
    BrokerHealth,
    BrokerOrder,
    BrokerPosition,
    Instrument,
    OrderRequest,
)
from aqt.common.types import OrderSide, OrderStatus, OrderType


class SimulatedBroker(BrokerAdapter):
    name = "simulated"

    def __init__(
        self,
        cash: float = 100.0,
        prices: Mapping[str, float] | None = None,
        fee_pct: float = 0.0,
        slippage_pct: float = 0.0,
    ) -> None:
        self.cash = cash
        self.prices: dict[str, float] = dict(prices or {})
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.healthy = True
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: dict[str, BrokerOrder] = {}
        self._by_client_id: dict[str, str] = {}
        self._ids = itertools.count(1)

    def set_price(self, symbol: str, price: float) -> None:
        if price <= 0:
            raise ValueError("price must be > 0")
        self.prices[symbol] = price
        if symbol in self._positions:
            p = self._positions[symbol]
            self._positions[symbol] = BrokerPosition(symbol, p.quantity, p.avg_price, price)

    def get_balance(self) -> AccountBalance:
        equity = self.cash + sum(p.quantity * p.market_price for p in self._positions.values())
        return AccountBalance(cash=self.cash, equity=equity)

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def get_orders(self) -> list[BrokerOrder]:
        return list(self._orders.values())

    def get_instruments(self) -> list[Instrument]:
        return [Instrument(s, s, "EUR") for s in sorted(self.prices)]

    def health(self) -> BrokerHealth:
        return BrokerHealth(ok=self.healthy, latency_ms=0.0)

    def cancel_order(self, order_id: str) -> BrokerOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise BrokerError(f"unknown order {order_id}")
        if order.status is not OrderStatus.NEW:
            raise BrokerError(f"order {order_id} is {order.status}, cannot cancel")
        cancelled = BrokerOrder(**{**order.__dict__, "status": OrderStatus.CANCELLED})
        self._orders[order_id] = cancelled
        return cancelled

    def place_order(self, request: OrderRequest) -> BrokerOrder:
        if not self.healthy:
            raise BrokerError("broker unavailable")
        # Idempotency: a repeated client_order_id returns the original order.
        if request.client_order_id in self._by_client_id:
            return self._orders[self._by_client_id[request.client_order_id]]
        if request.order_type is not OrderType.MARKET:
            raise BrokerError("SimulatedBroker only supports MARKET orders")
        if request.quantity <= 0:
            raise BrokerError("quantity must be > 0")
        price = self.prices.get(request.symbol)
        if price is None:
            raise BrokerError(f"no price for {request.symbol}")

        order_id = f"SIM-{next(self._ids)}"
        status, fill_px = OrderStatus.FILLED, price
        if request.side is OrderSide.BUY:
            fill_px = price * (1 + self.slippage_pct)
            cost = request.quantity * fill_px * (1 + self.fee_pct)
            if cost > self.cash + 1e-9:
                status = OrderStatus.REJECTED
            else:
                self.cash -= cost
                prev = self._positions.get(request.symbol)
                qty = request.quantity + (prev.quantity if prev else 0.0)
                avg = (
                    (prev.quantity * prev.avg_price + request.quantity * fill_px) / qty
                    if prev
                    else fill_px
                )
                self._positions[request.symbol] = BrokerPosition(request.symbol, qty, avg, price)
        else:
            prev = self._positions.get(request.symbol)
            if prev is None or prev.quantity + 1e-12 < request.quantity:
                status = OrderStatus.REJECTED  # no shorting
            else:
                fill_px = price * (1 - self.slippage_pct)
                self.cash += request.quantity * fill_px * (1 - self.fee_pct)
                left = prev.quantity - request.quantity
                if left <= 1e-12:
                    del self._positions[request.symbol]
                else:
                    self._positions[request.symbol] = BrokerPosition(
                        request.symbol, left, prev.avg_price, price
                    )

        filled = status is OrderStatus.FILLED
        order = BrokerOrder(
            order_id=order_id,
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            status=status,
            filled_quantity=request.quantity if filled else 0.0,
            avg_fill_price=fill_px if filled else None,
        )
        self._orders[order_id] = order
        self._by_client_id[request.client_order_id] = order_id
        return order
