"""Alpaca **paper** broker: real order routing to Alpaca's simulated account.

Orders approved by the Risk Engine are sent to ``paper-api.alpaca.markets`` (any other host is
refused) as market/day orders, fractional quantities allowed. Alpaca fills them against the live
market; the fills it reports — price and quantity — are what the engine books.

* **Non-blocking.** ``place_order`` validates locally and queues; an asyncio task (:meth:`run`)
  submits, polls order status every ``poll_s`` and hands fills back through :meth:`on_quote`,
  the same contract as the local :class:`~aqt.brokers.paper.PaperExchange`.
* **Capital sub-account.** The bot manages ``capital`` (e.g. 10,000 USD) inside the paper
  account; cash never goes negative, so no margin is ever used even if the account allows it.
* **Reconciliation.** Every ``sync_s`` the local book is compared with Alpaca's positions for the
  symbols the bot trades. A mismatch that persists with no order in flight marks the venue
  unhealthy, and the Risk Engine then rejects every order until it is resolved.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

import httpx

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
from aqt.brokers.paper import Fill
from aqt.common.types import OrderSide, OrderStatus, OrderType
from aqt.stream.events import Quote

log = logging.getLogger(__name__)

PAPER_HOST = "paper-api.alpaca.markets"
# Commission-free; ~0.002 % approximates SEC/FINRA fees on sells (booked locally on both sides).
ALPACA_FEE_EST = 0.00002
_TERMINAL = {"canceled", "expired", "rejected", "replaced", "done_for_day"}


@dataclass
class _Inflight:
    request: OrderRequest
    submitted: bool = False
    remote_id: str | None = None
    attempts: int = 0


class AlpacaPaperBroker(BrokerAdapter):
    name = "alpaca-paper"

    def __init__(
        self,
        key: str,
        secret: str,
        capital: float,
        base_url: str = f"https://{PAPER_HOST}",
        fee_pct: float = ALPACA_FEE_EST,
        min_notional: float = 1.0,
        poll_s: float = 1.0,
        sync_s: float = 15.0,
        symbols: Iterable[str] = (),
        clock: Callable[[], float] = time.time,
        transport: httpx.AsyncBaseTransport | None = None,
        sync_transport: httpx.BaseTransport | None = None,
    ) -> None:
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != PAPER_HOST:
            raise ValueError(f"AlpacaPaperBroker only talks to {PAPER_HOST}, not {host!r}")
        if capital <= 0:
            raise ValueError("capital must be > 0")
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self.base_url = f"https://{host}"
        self.cash = capital
        self.fee_pct = fee_pct
        self.min_notional = min_notional
        self.poll_s = poll_s
        self.sync_s = sync_s
        self.symbols = {s.upper() for s in symbols}
        self.clock = clock
        self._transport = transport
        self._sync_transport = sync_transport
        self.now = 0.0
        self.total_fees = 0.0
        self.healthy = True
        self.last_ok = clock()
        self.last_error = ""
        self.mismatch_count = 0
        self.remote_positions: dict[str, float] = {}
        self._books: dict[str, Quote] = {}
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: dict[str, BrokerOrder] = {}
        self._inflight: dict[str, _Inflight] = {}
        self._fills: list[Fill] = []

    def __repr__(self) -> str:  # never leak credentials
        return f"AlpacaPaperBroker(base_url={self.base_url}, capital={self.cash:.2f})"

    # ------------------------------------------------------------------ engine contract
    def set_time(self, ts: float) -> None:
        self.now = max(self.now, ts)

    def on_quote(self, q: Quote) -> list[Fill]:
        if q.valid:
            self.now = max(self.now, q.ts)
            self._books[q.symbol] = q
            pos = self._positions.get(q.symbol)
            if pos is not None:
                self._positions[q.symbol] = replace(pos, market_price=q.bid)
        fills, self._fills = self._fills, []
        return fills

    def get_balance(self) -> AccountBalance:
        equity = self.cash + sum(p.quantity * p.market_price for p in self._positions.values())
        return AccountBalance(cash=self.cash, equity=equity, currency="USD")

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def get_orders(self) -> list[BrokerOrder]:
        return list(self._orders.values())

    def get_order(self, order_id: str) -> BrokerOrder | None:
        return self._orders.get(order_id)

    def get_instruments(self) -> list[Instrument]:
        return [Instrument(s, s, "USD", True, 1e-9) for s in sorted(self._books)]

    def health(self) -> BrokerHealth:
        stale = self.clock() - self.last_ok > max(60.0, 4 * self.sync_s)
        ok = self.healthy and not stale and self.mismatch_count < 2
        detail = self.last_error or (
            "positions do not reconcile" if self.mismatch_count >= 2 else ""
        )
        return BrokerHealth(ok=ok, detail=detail)

    def cancel_order(self, order_id: str) -> BrokerOrder:
        inflight = self._inflight.get(order_id)
        if inflight is None or inflight.submitted:
            raise BrokerError(f"order {order_id} cannot be cancelled locally")
        del self._inflight[order_id]
        cancelled = replace(self._orders[order_id], status=OrderStatus.CANCELLED)
        self._orders[order_id] = cancelled
        return cancelled

    def place_order(self, request: OrderRequest) -> BrokerOrder:
        if not self.healthy:
            raise BrokerError(self.last_error or "Alpaca paper unavailable")
        cid = request.client_order_id
        if cid in self._orders:  # idempotent
            return self._orders[cid]
        if request.order_type is not OrderType.MARKET:
            raise BrokerError("only MARKET orders are routed")
        if request.quantity <= 0:
            raise BrokerError("quantity must be > 0")
        book = self._books.get(request.symbol)
        if book is None:
            raise BrokerError(f"no quote for {request.symbol}")
        order = BrokerOrder(
            cid, cid, request.symbol, request.side, request.quantity, OrderStatus.NEW
        )
        held = self._positions.get(request.symbol)
        ref = book.ask if request.side is OrderSide.BUY else book.bid
        notional = request.quantity * ref
        if notional < self.min_notional:
            order = replace(order, status=OrderStatus.REJECTED)
        elif request.side is OrderSide.SELL and (
            held is None or held.quantity + 1e-9 < request.quantity
        ):
            order = replace(order, status=OrderStatus.REJECTED)  # never short
        elif request.side is OrderSide.BUY and notional * (1 + self.fee_pct) > self.cash:
            order = replace(order, status=OrderStatus.REJECTED)  # never margin
        else:
            self._inflight[cid] = _Inflight(request)
        self._orders[cid] = order
        return order

    def pending_client_ids(self) -> frozenset[str]:
        return frozenset(self._inflight)

    # ------------------------------------------------------------------ booking
    def _book_fill(self, cid: str, qty: float, price: float) -> None:
        order = self._orders[cid]
        notional = qty * price
        fee = notional * self.fee_pct
        held = self._positions.get(order.symbol)
        mark = self._books[order.symbol].bid if order.symbol in self._books else price
        if order.side is OrderSide.BUY:
            self.cash -= notional + fee
            new_qty = qty + (held.quantity if held else 0.0)
            avg = (held.quantity * held.avg_price + notional) / new_qty if held else price
            self._positions[order.symbol] = BrokerPosition(order.symbol, new_qty, avg, mark)
        else:
            self.cash += notional - fee
            left = (held.quantity if held else 0.0) - qty
            if left <= 1e-9:
                self._positions.pop(order.symbol, None)
            elif held is not None:
                self._positions[order.symbol] = replace(held, quantity=left, market_price=mark)
        self.total_fees += fee
        self._orders[cid] = replace(
            order, status=OrderStatus.FILLED, filled_quantity=qty, avg_fill_price=price
        )
        self._fills.append(
            Fill(cid, cid, order.symbol, order.side, qty, price, fee, max(self.now, self.clock()))
        )

    # ------------------------------------------------------------------ network loop
    def _client(self) -> httpx.AsyncClient:
        from aqt.stream.binance import system_ssl_context

        if self._transport is not None:
            return httpx.AsyncClient(
                base_url=self.base_url, headers=self._headers, transport=self._transport
            )
        return httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers, verify=system_ssl_context(), timeout=15
        )

    async def run(self) -> None:
        """Submit queued orders, poll their status and reconcile positions until cancelled."""
        last_sync = -1e18
        async with self._client() as client:
            while True:
                try:
                    await self._submit(client)
                    await self._poll(client)
                    if self.clock() - last_sync >= self.sync_s:
                        await self._sync(client)
                        last_sync = self.clock()
                    self.last_ok = self.clock()
                    self.last_error = ""
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # network trouble: retry; health() degrades if it lasts
                    self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                    log.warning("Alpaca paper: %s", self.last_error)
                await asyncio.sleep(self.poll_s)

    async def step(self, client: httpx.AsyncClient) -> None:
        """One iteration of :meth:`run` (tests)."""
        await self._submit(client)
        await self._poll(client)
        await self._sync(client)
        self.last_ok = self.clock()

    async def _submit(self, client: httpx.AsyncClient) -> None:
        for cid, inf in list(self._inflight.items()):
            if inf.submitted:
                continue
            req = inf.request
            body = {
                "symbol": req.symbol,
                "qty": f"{req.quantity:.9f}".rstrip("0").rstrip("."),
                "side": "buy" if req.side is OrderSide.BUY else "sell",
                "type": "market",
                "time_in_force": "day",
                "client_order_id": cid[:128],
            }
            inf.attempts += 1
            r = await client.post("/v2/orders", json=body)
            if r.status_code in (200, 201):
                inf.submitted, inf.remote_id = True, str(r.json().get("id"))
            elif 400 <= r.status_code < 500 and r.status_code != 429:
                del self._inflight[cid]
                self._orders[cid] = replace(self._orders[cid], status=OrderStatus.REJECTED)
                log.warning("Alpaca rejected %s: %s", cid, r.text[:200])
            elif inf.attempts >= 5:
                del self._inflight[cid]
                self._orders[cid] = replace(self._orders[cid], status=OrderStatus.REJECTED)

    async def _poll(self, client: httpx.AsyncClient) -> None:
        for cid, inf in list(self._inflight.items()):
            if not inf.submitted:
                continue
            r = await client.get(
                "/v2/orders:by_client_order_id", params={"client_order_id": cid[:128]}
            )
            if r.status_code != 200:
                continue
            o = r.json()
            status = str(o.get("status"))
            filled = float(o.get("filled_qty") or 0.0)
            price = float(o.get("filled_avg_price") or 0.0)
            if status == "filled" or (status in _TERMINAL and filled > 0):
                del self._inflight[cid]
                self._book_fill(cid, filled, price)
            elif status in _TERMINAL:
                del self._inflight[cid]
                self._orders[cid] = replace(self._orders[cid], status=OrderStatus.CANCELLED)

    async def _sync(self, client: httpx.AsyncClient) -> None:
        acct = await client.get("/v2/account")
        acct.raise_for_status()
        info = acct.json()
        self.healthy = not (info.get("trading_blocked") or info.get("account_blocked"))
        if not self.healthy:
            self.last_error = "Alpaca account blocked"
        r = await client.get("/v2/positions")
        r.raise_for_status()
        self.remote_positions = {
            p["symbol"]: float(p["qty"])
            for p in r.json()
            if not self.symbols or p["symbol"] in self.symbols
        }
        if self._inflight:
            return  # positions are moving: compare only when nothing is in flight
        local = {s: p.quantity for s, p in self._positions.items()}
        keys = set(local) | set(self.remote_positions)
        same = all(abs(local.get(k, 0.0) - self.remote_positions.get(k, 0.0)) <= 1e-6 for k in keys)
        self.mismatch_count = 0 if same else self.mismatch_count + 1

    # ------------------------------------------------------------------ shutdown
    def liquidate_now(self, symbol: str, client_order_id: str) -> Fill | None:
        """Blocking market sell of the bot's position (orderly shutdown; waits up to ~10 s)."""
        held = self._positions.get(symbol)
        if held is None:
            return None
        for cid, inf in list(self._inflight.items()):
            if inf.request.symbol == symbol and not inf.submitted:
                self.cancel_order(cid)
        self._orders[client_order_id] = BrokerOrder(
            client_order_id, client_order_id, symbol, OrderSide.SELL, held.quantity, OrderStatus.NEW
        )
        from aqt.stream.binance import system_ssl_context

        kw: dict[str, Any] = (
            {"transport": self._sync_transport}
            if self._sync_transport is not None
            else {"verify": system_ssl_context(), "timeout": 15}
        )
        body = {
            "symbol": symbol,
            "qty": f"{held.quantity:.9f}".rstrip("0").rstrip("."),
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_order_id[:128],
        }
        try:
            with httpx.Client(base_url=self.base_url, headers=self._headers, **kw) as c:
                c.post("/v2/orders", json=body).raise_for_status()
                for _ in range(20):
                    o = c.get(
                        "/v2/orders:by_client_order_id",
                        params={"client_order_id": client_order_id[:128]},
                    ).json()
                    if o.get("status") == "filled":
                        self._book_fill(
                            client_order_id, float(o["filled_qty"]), float(o["filled_avg_price"])
                        )
                        return self._fills.pop()
                    time.sleep(0.5)
        except Exception as exc:
            log.error("could not liquidate %s on Alpaca paper: %s", symbol, exc)
        return None

    async def close_all(self) -> None:  # pragma: no cover - convenience for operators
        with contextlib.suppress(Exception):
            async with self._client() as client:
                for symbol in list(self._positions):
                    await client.delete(f"/v2/positions/{symbol}")
