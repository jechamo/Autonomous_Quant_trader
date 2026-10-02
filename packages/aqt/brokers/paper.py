"""Paper exchange driven by a live (or replayed) order book.

Market orders are not filled at the price the strategy saw. They wait ``latency_s`` and then
fill against the first quote at or after that moment: buys at the ask, sells at the bid. Any
quantity beyond the displayed top-of-book size pays an extra ``impact_pct``. A proportional fee
(Binance spot taker: 0.10 %) is charged on every fill. No shorting and no margin: a sell larger
than the position or a buy larger than the cash is rejected.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass, replace

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
from aqt.stream.events import Quote

BINANCE_TAKER_FEE = 0.001


@dataclass(frozen=True)
class Fill:
    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    fee: float
    ts: float

    @property
    def notional(self) -> float:
        return self.quantity * self.price


@dataclass
class _Pending:
    order: BrokerOrder
    submitted_at: float


class PaperExchange(BrokerAdapter):
    name = "paper"

    def __init__(
        self,
        cash: float = 100.0,
        fee_pct: float = BINANCE_TAKER_FEE,
        latency_s: float = 0.25,
        impact_pct: float = 0.0005,
        min_notional: float = 5.0,
        quantity_steps: Mapping[str, float] | None = None,
        currency: str = "EUR",
    ) -> None:
        if cash < 0 or fee_pct < 0 or latency_s < 0 or impact_pct < 0:
            raise ValueError("cash, fee, latency and impact must be >= 0")
        self.cash = cash
        self.fee_pct = fee_pct
        self.latency_s = latency_s
        self.impact_pct = impact_pct
        self.min_notional = min_notional
        self.quantity_steps = dict(quantity_steps or {})
        self.currency = currency
        self.now = 0.0
        self.total_fees = 0.0
        self.healthy = True
        self._books: dict[str, Quote] = {}
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: dict[str, BrokerOrder] = {}
        self._pending: dict[str, _Pending] = {}
        self._by_client_id: dict[str, str] = {}
        self._ids = itertools.count(1)

    # ------------------------------------------------------------------ market data
    def book(self, symbol: str) -> Quote | None:
        return self._books.get(symbol)

    def on_quote(self, q: Quote) -> list[Fill]:
        if not q.valid:
            return []
        self.now = max(self.now, q.ts)
        self._books[q.symbol] = q
        pos = self._positions.get(q.symbol)
        if pos is not None:
            self._positions[q.symbol] = replace(pos, market_price=q.bid)
        fills = []
        for oid, pending in list(self._pending.items()):
            if pending.order.symbol == q.symbol and q.ts >= pending.submitted_at + self.latency_s:
                del self._pending[oid]
                fill = self._execute(pending.order, q)
                if fill is not None:
                    fills.append(fill)
        return fills

    def set_time(self, ts: float) -> None:
        self.now = max(self.now, ts)

    # ------------------------------------------------------------------ BrokerAdapter
    def get_balance(self) -> AccountBalance:
        equity = self.cash + sum(p.quantity * p.market_price for p in self._positions.values())
        return AccountBalance(cash=self.cash, equity=equity, currency=self.currency)

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def get_orders(self) -> list[BrokerOrder]:
        return list(self._orders.values())

    def get_order(self, order_id: str) -> BrokerOrder | None:
        return self._orders.get(order_id)

    def get_instruments(self) -> list[Instrument]:
        return [
            Instrument(s, s, self.currency, True, self.quantity_steps.get(s, 1e-8))
            for s in sorted(self._books)
        ]

    def health(self) -> BrokerHealth:
        return BrokerHealth(ok=self.healthy, latency_ms=self.latency_s * 1000.0)

    def pending_client_ids(self) -> frozenset[str]:
        return frozenset(p.order.client_order_id for p in self._pending.values())

    def cancel_order(self, order_id: str) -> BrokerOrder:
        pending = self._pending.pop(order_id, None)
        if pending is None:
            raise BrokerError(f"order {order_id} is not pending, cannot cancel")
        cancelled = replace(pending.order, status=OrderStatus.CANCELLED)
        self._orders[order_id] = cancelled
        return cancelled

    def place_order(self, request: OrderRequest) -> BrokerOrder:
        if not self.healthy:
            raise BrokerError("paper exchange unavailable")
        if request.client_order_id in self._by_client_id:  # idempotent
            return self._orders[self._by_client_id[request.client_order_id]]
        if request.order_type is not OrderType.MARKET:
            raise BrokerError("PaperExchange only supports MARKET orders")
        if request.quantity <= 0:
            raise BrokerError("quantity must be > 0")
        book = self._books.get(request.symbol)
        if book is None:
            raise BrokerError(f"no order book for {request.symbol}")

        order = BrokerOrder(
            order_id=f"PAPER-{next(self._ids)}",
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            status=OrderStatus.NEW,
        )
        ref = book.ask if request.side is OrderSide.BUY else book.bid
        held = self._positions.get(request.symbol)
        if request.quantity * ref < self.min_notional:
            order = replace(order, status=OrderStatus.REJECTED)
        elif request.side is OrderSide.SELL and (
            held is None or held.quantity + 1e-12 < request.quantity
        ):
            order = replace(order, status=OrderStatus.REJECTED)  # never short
        else:
            self._pending[order.order_id] = _Pending(order, self.now)
        self._orders[order.order_id] = order
        self._by_client_id[request.client_order_id] = order.order_id
        return order

    def liquidate_now(self, symbol: str, client_order_id: str) -> Fill | None:
        """Sell the whole position at the current bid without latency (orderly shutdown)."""
        held, book = self._positions.get(symbol), self._books.get(symbol)
        if held is None or book is None:
            return None
        order = BrokerOrder(
            order_id=f"PAPER-{next(self._ids)}",
            client_order_id=client_order_id,
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=held.quantity,
            status=OrderStatus.NEW,
        )
        self._orders[order.order_id] = order
        self._by_client_id[client_order_id] = order.order_id
        for oid, pending in list(self._pending.items()):
            if pending.order.symbol == symbol:
                self.cancel_order(oid)
        return self._execute(order, book)

    # ------------------------------------------------------------------ execution
    def _price(self, side: OrderSide, qty: float, q: Quote) -> float:
        top, shown = (q.ask, q.ask_qty) if side is OrderSide.BUY else (q.bid, q.bid_qty)
        sign = 1.0 if side is OrderSide.BUY else -1.0
        if shown <= 0 or qty <= shown:
            return top
        beyond = top * (1.0 + sign * self.impact_pct)
        return (shown * top + (qty - shown) * beyond) / qty

    def _execute(self, order: BrokerOrder, q: Quote) -> Fill | None:
        qty = order.quantity
        price = self._price(order.side, qty, q)
        notional = qty * price
        fee = notional * self.fee_pct
        held = self._positions.get(order.symbol)
        if order.side is OrderSide.BUY:
            if notional + fee > self.cash + 1e-9:
                self._orders[order.order_id] = replace(order, status=OrderStatus.REJECTED)
                return None
            self.cash -= notional + fee
            new_qty = qty + (held.quantity if held else 0.0)
            avg = (held.quantity * held.avg_price + notional) / new_qty if held else price
            self._positions[order.symbol] = BrokerPosition(order.symbol, new_qty, avg, q.bid)
        else:
            if held is None or held.quantity + 1e-12 < qty:
                self._orders[order.order_id] = replace(order, status=OrderStatus.REJECTED)
                return None
            self.cash += notional - fee
            left = held.quantity - qty
            if left <= 1e-12:
                del self._positions[order.symbol]
            else:
                self._positions[order.symbol] = replace(held, quantity=left, market_price=q.bid)
        self.total_fees += fee
        self._orders[order.order_id] = replace(
            order, status=OrderStatus.FILLED, filled_quantity=qty, avg_fill_price=price
        )
        return Fill(
            order.order_id, order.client_order_id, order.symbol, order.side, qty, price, fee, q.ts
        )
