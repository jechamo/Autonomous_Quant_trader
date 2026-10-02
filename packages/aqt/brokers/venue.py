"""What the streaming engine needs from wherever its orders go (local paper or Alpaca paper)."""

from __future__ import annotations

from typing import Protocol

from aqt.brokers.base import AccountBalance, BrokerHealth, BrokerOrder, BrokerPosition, OrderRequest
from aqt.brokers.paper import Fill
from aqt.stream.events import Quote


class ExecutionVenue(Protocol):
    name: str
    total_fees: float
    min_notional: float

    def place_order(self, request: OrderRequest) -> BrokerOrder: ...

    def on_quote(self, q: Quote) -> list[Fill]: ...

    def set_time(self, ts: float) -> None: ...

    def get_balance(self) -> AccountBalance: ...

    def get_positions(self) -> list[BrokerPosition]: ...

    def get_order(self, order_id: str) -> BrokerOrder | None: ...

    def health(self) -> BrokerHealth: ...

    def liquidate_now(self, symbol: str, client_order_id: str) -> Fill | None: ...
