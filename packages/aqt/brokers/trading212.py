"""Trading 212 adapter — placeholder for iteration 2.

Endpoints: demo ``https://demo.trading212.com/api/v0`` and live ``https://live.trading212.com/api/v0``.
Credentials (API key + secret) come only from the runtime secret manager / environment, never
from code or the frontend. The Public API is beta: re-validate limits before going live.
"""

from __future__ import annotations

from aqt.brokers.base import (
    AccountBalance,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrder,
    BrokerPosition,
    Instrument,
    OrderRequest,
)
from aqt.common.config import TradingMode

DEMO_URL = "https://demo.trading212.com/api/v0"
LIVE_URL = "https://live.trading212.com/api/v0"


class Trading212Broker(BrokerAdapter):
    name = "trading212"

    def __init__(self, mode: TradingMode, api_key: str, api_secret: str) -> None:
        if mode is TradingMode.DEV:
            raise ValueError("Trading212Broker is not used in DEV mode; use SimulatedBroker")
        if not api_key or not api_secret:
            raise ValueError("Trading 212 credentials are required")
        self.mode = mode
        self.base_url = LIVE_URL if mode is TradingMode.LIVE else DEMO_URL
        self._api_key = api_key
        self._api_secret = api_secret

    def __repr__(self) -> str:  # never leak secrets in logs
        return f"Trading212Broker(mode={self.mode}, base_url={self.base_url})"

    def _todo(self) -> NotImplementedError:
        return NotImplementedError("Trading212Broker is implemented in iteration 2 (Paper Trader)")

    def get_balance(self) -> AccountBalance:
        raise self._todo()

    def get_positions(self) -> list[BrokerPosition]:
        raise self._todo()

    def get_orders(self) -> list[BrokerOrder]:
        raise self._todo()

    def place_order(self, request: OrderRequest) -> BrokerOrder:
        raise self._todo()

    def cancel_order(self, order_id: str) -> BrokerOrder:
        raise self._todo()

    def get_instruments(self) -> list[Instrument]:
        raise self._todo()

    def health(self) -> BrokerHealth:
        raise self._todo()
