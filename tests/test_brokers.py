import pytest
from aqt.brokers import BrokerError, OrderRequest, SimulatedBroker, Trading212Broker
from aqt.common.config import TradingMode
from aqt.common.types import OrderSide, OrderStatus, OrderType


def test_simulated_buy_sell_cycle() -> None:
    b = SimulatedBroker(cash=100.0, prices={"SPY": 50.0})
    o = b.place_order(OrderRequest("SPY", OrderSide.BUY, 1.5, "c1"))
    assert o.status is OrderStatus.FILLED
    assert b.get_balance().cash == pytest.approx(25.0)
    assert b.get_positions()[0].quantity == 1.5
    b.set_price("SPY", 60.0)
    assert b.get_balance().equity == pytest.approx(25 + 90)
    b.place_order(OrderRequest("SPY", OrderSide.SELL, 1.5, "c2"))
    assert b.get_positions() == []
    assert b.get_balance().cash == pytest.approx(115.0)


def test_idempotency_and_rejections() -> None:
    b = SimulatedBroker(cash=100.0, prices={"SPY": 50.0})
    o1 = b.place_order(OrderRequest("SPY", OrderSide.BUY, 1, "same"))
    o2 = b.place_order(OrderRequest("SPY", OrderSide.BUY, 1, "same"))
    assert o1 == o2 and len(b.get_orders()) == 1
    assert (
        b.place_order(OrderRequest("SPY", OrderSide.BUY, 10, "big")).status is OrderStatus.REJECTED
    )
    assert (
        b.place_order(OrderRequest("SPY", OrderSide.SELL, 5, "short")).status
        is OrderStatus.REJECTED
    )
    with pytest.raises(BrokerError):
        b.place_order(OrderRequest("XXX", OrderSide.BUY, 1, "x"))
    with pytest.raises(BrokerError):
        b.place_order(OrderRequest("SPY", OrderSide.BUY, 1, "l", OrderType.LIMIT, limit_price=1))
    b.healthy = False
    assert not b.health().ok
    with pytest.raises(BrokerError):
        b.place_order(OrderRequest("SPY", OrderSide.BUY, 1, "down"))
    with pytest.raises(BrokerError):
        b.cancel_order("nope")
    with pytest.raises(BrokerError):
        b.cancel_order(o1.order_id)  # already filled
    assert [i.symbol for i in b.get_instruments()] == ["SPY"]


def test_trading212_guardrails() -> None:
    with pytest.raises(ValueError):
        Trading212Broker(TradingMode.DEV, "k", "s")
    with pytest.raises(ValueError):
        Trading212Broker(TradingMode.PAPER, "", "")
    demo = Trading212Broker(TradingMode.PAPER, "key", "secret")
    assert "demo.trading212.com" in demo.base_url
    assert "secret" not in repr(demo) and "key" not in repr(demo).replace("api", "")
    with pytest.raises(NotImplementedError):
        demo.get_balance()
