"""Market events for the streaming engine. Timestamps are epoch seconds (float, UTC)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Quote:
    """Top of book (best bid / best ask)."""

    symbol: str
    ts: float
    bid: float
    bid_qty: float
    ask: float
    ask_qty: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        mid = self.mid
        return (self.ask - self.bid) / mid if mid > 0 else float("inf")

    @property
    def valid(self) -> bool:
        return self.bid > 0 and self.ask >= self.bid


@dataclass(frozen=True, slots=True)
class TradeTick:
    """A public trade. ``buyer_is_maker`` means the aggressor was a seller."""

    symbol: str
    ts: float
    price: float
    qty: float
    buyer_is_maker: bool

    @property
    def signed_qty(self) -> float:
        return -self.qty if self.buyer_is_maker else self.qty


Event = Quote | TradeTick
