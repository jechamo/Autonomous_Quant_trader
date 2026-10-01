from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from aqt.brokers.alpaca_paper import AlpacaPaperBroker
from aqt.brokers.base import BrokerError, OrderRequest
from aqt.common.types import OrderSide, OrderStatus, OrderType
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Quote

from tests.test_stream import SMALL, Always, seed_evidence


class FakeAlpaca:
    """Minimal in-memory Alpaca paper API: market orders fill at a fixed price."""

    def __init__(self, fill_price: float = 100.0) -> None:
        self.fill_price = fill_price
        self.orders: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, float] = {}
        self.reject_next = False
        self.blocked = False
        self.fill = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["APCA-API-KEY-ID"] == "PKTEST"
        path = request.url.path
        if request.method == "POST" and path == "/v2/orders":
            body = json.loads(request.content)
            if self.reject_next:
                self.reject_next = False
                return httpx.Response(422, json={"message": "insufficient qty"})
            qty = float(body["qty"])
            self.orders[body["client_order_id"]] = {
                "id": f"remote-{len(self.orders)}",
                "status": "filled" if self.fill else "accepted",
                "filled_qty": str(qty if self.fill else 0),
                "filled_avg_price": str(self.fill_price),
            }
            if self.fill:
                sign = 1 if body["side"] == "buy" else -1
                left = self.positions.get(body["symbol"], 0) + sign * qty
                if abs(left) < 1e-9:
                    self.positions.pop(body["symbol"], None)
                else:
                    self.positions[body["symbol"]] = left
            return httpx.Response(200, json=self.orders[body["client_order_id"]])
        if path == "/v2/orders:by_client_order_id":
            o = self.orders.get(request.url.params["client_order_id"])
            return httpx.Response(200, json=o) if o else httpx.Response(404)
        if path == "/v2/account":
            return httpx.Response(200, json={"status": "ACTIVE", "trading_blocked": self.blocked})
        if path == "/v2/positions":
            rows = [{"symbol": k, "qty": str(v)} for k, v in self.positions.items()]
            return httpx.Response(200, json=rows)
        return httpx.Response(404)


def make(fake: FakeAlpaca, capital: float = 10_000.0) -> AlpacaPaperBroker:
    transport = httpx.MockTransport(fake.handler)
    return AlpacaPaperBroker(
        "PKTEST",
        "SECRET",
        capital,
        symbols=["AAPL"],
        clock=lambda: 1.0,
        transport=transport,
        sync_transport=transport,
    )


def step(b: AlpacaPaperBroker) -> None:
    async def go() -> None:
        async with b._client() as c:
            await b.step(c)

    asyncio.run(go())


def q(ts: float = 1.0, mid: float = 100.0) -> Quote:
    return Quote("AAPL", ts, mid - 0.01, 10, mid + 0.01, 10)


def test_orders_are_routed_filled_and_reconciled() -> None:
    fake = FakeAlpaca()
    b = make(fake)
    b.on_quote(q())
    o = b.place_order(OrderRequest("AAPL", OrderSide.BUY, 10.0, "c1"))
    assert o.status is OrderStatus.NEW and b.pending_client_ids() == {"c1"}
    assert b.place_order(OrderRequest("AAPL", OrderSide.BUY, 10.0, "c1")) is o  # idempotent
    step(b)
    (fill,) = b.on_quote(q(2.0))
    assert fill.price == 100.0 and fill.quantity == 10.0 and fill.side is OrderSide.BUY
    assert b.get_order("c1").status is OrderStatus.FILLED  # type: ignore[union-attr]
    assert b.cash == pytest.approx(10_000 - 1000 - fill.fee)
    assert b.remote_positions == {"AAPL": 10.0} and b.mismatch_count == 0 and b.health().ok
    b.place_order(OrderRequest("AAPL", OrderSide.SELL, 10.0, "c2"))
    step(b)
    (sell,) = b.on_quote(q(3.0))
    assert sell.side is OrderSide.SELL and b.get_positions() == []
    assert b.get_balance().equity == pytest.approx(10_000 - fill.fee - sell.fee)
    assert [i.symbol for i in b.get_instruments()] == ["AAPL"] and len(b.get_orders()) == 2


def test_local_guards_and_exchange_rejections() -> None:
    fake = FakeAlpaca()
    b = make(fake, capital=500.0)
    with pytest.raises(BrokerError):
        b.place_order(OrderRequest("AAPL", OrderSide.BUY, 1, "x"))  # no quote yet
    b.on_quote(q())
    assert (
        b.place_order(OrderRequest("AAPL", OrderSide.BUY, 10, "big")).status is OrderStatus.REJECTED
    )
    sell = b.place_order(OrderRequest("AAPL", OrderSide.SELL, 1, "short"))
    assert sell.status is OrderStatus.REJECTED  # never short
    tiny = b.place_order(OrderRequest("AAPL", OrderSide.BUY, 0.001, "tiny"))
    assert tiny.status is OrderStatus.REJECTED
    with pytest.raises(BrokerError):
        b.place_order(OrderRequest("AAPL", OrderSide.BUY, 1, "l", OrderType.LIMIT, 1.0))
    with pytest.raises(BrokerError):
        b.place_order(OrderRequest("AAPL", OrderSide.BUY, 0, "z"))
    fake.reject_next = True
    b.place_order(OrderRequest("AAPL", OrderSide.BUY, 1, "r"))
    step(b)
    assert b.get_order("r").status is OrderStatus.REJECTED  # type: ignore[union-attr]
    fake.fill = False
    b.place_order(OrderRequest("AAPL", OrderSide.BUY, 1, "slow"))
    assert b.cancel_order("slow").status is OrderStatus.CANCELLED
    with pytest.raises(BrokerError):
        b.cancel_order("slow")
    with pytest.raises(ValueError):
        AlpacaPaperBroker("k", "s", 100, base_url="https://api.alpaca.markets")  # live: refused
    with pytest.raises(ValueError):
        AlpacaPaperBroker("k", "s", 0)
    assert "SECRET" not in repr(b)


def test_persistent_mismatch_or_blocked_account_makes_venue_unhealthy() -> None:
    fake = FakeAlpaca()
    b = make(fake)
    b.on_quote(q())
    fake.positions["AAPL"] = 5.0  # something outside the bot moved the position
    step(b)
    assert b.health().ok  # a single mismatch may be timing
    step(b)
    assert not b.health().ok and "reconcile" in b.health().detail
    fake.positions.clear()
    step(b)
    assert b.health().ok
    fake.blocked = True
    step(b)
    assert not b.health().ok
    with pytest.raises(BrokerError):
        b.place_order(OrderRequest("AAPL", OrderSide.BUY, 1, "blocked"))


def test_liquidate_now_closes_the_bot_position() -> None:
    fake = FakeAlpaca()
    b = make(fake)
    b.on_quote(q())
    b.place_order(OrderRequest("AAPL", OrderSide.BUY, 3, "b"))
    step(b)
    b.on_quote(q(2.0))
    fill = b.liquidate_now("AAPL", "shutdown-1")
    assert fill is not None and fill.quantity == 3 and b.get_positions() == []
    assert fake.positions == {} and b.liquidate_now("AAPL", "again") is None


def test_engine_trades_through_alpaca_paper() -> None:
    fake = FakeAlpaca(fill_price=100.02)
    venue = make(fake)
    cfg = EngineConfig(
        symbols=("AAPL",),
        bar_seconds=1.0,
        feature_params=SMALL,
        latency_s=0.0,
        entry_cooldown_seconds=0.0,
        currency="USD",
        initial_cash=10_000,
        min_order_notional=1.0,
    )
    eng = StreamingEngine(cfg, strategies=[Always()], broker=venue)
    eng.set_adv("AAPL", 1e7)
    seed_evidence(eng)
    for i in range(6):
        eng.on_event(q(i + 0.5, 100.0 + (0.02 if i % 2 else 0.0)))
    assert venue.pending_client_ids()  # the approved order is on its way to Alpaca
    step(venue)
    eng.on_event(q(6.5))
    pos = eng._positions["AAPL"]
    assert pos.entry_price == 100.02 and eng.reconciled
    assert fake.positions["AAPL"] == pytest.approx(pos.quantity)
    assert eng.snapshot()["venue"] == "alpaca-paper"
