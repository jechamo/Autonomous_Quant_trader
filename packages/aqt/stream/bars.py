"""Time bars built incrementally from quotes (mid price) and trades (order flow).

Prices come from the quote mid, which avoids bid/ask bounce; volume and signed order flow come
from public trades. A bar ``[start, start + interval)`` is emitted only once an event (or a timer
tick) at or after its end proves it is complete, so nothing in a bar comes from the future.
Silent intervals produce flat bars so features keep a regular clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aqt.stream.events import Quote, TradeTick


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    start: float
    interval: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_volume: float
    sell_volume: float
    n_trades: int
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float

    @property
    def end(self) -> float:
        return self.start + self.interval

    @property
    def signed_volume(self) -> float:
        return self.buy_volume - self.sell_volume


class BarAggregator:
    """Builds fixed-interval bars for one symbol."""

    def __init__(self, symbol: str, interval: float, max_gap_bars: int = 120) -> None:
        if interval <= 0:
            raise ValueError("interval must be > 0")
        self.symbol = symbol
        self.interval = float(interval)
        self.max_gap_bars = max_gap_bars
        self._start: float | None = None
        self._open = self._high = self._low = self._close = 0.0
        self._vol = self._buy = self._sell = 0.0
        self._n = 0
        self._fresh = True
        self._quote: Quote | None = None
        self.gaps = 0  # number of times a gap longer than max_gap_bars was skipped

    def _bucket(self, ts: float) -> float:
        return math.floor(ts / self.interval) * self.interval

    def _reset_bar(self, start: float, price: float) -> None:
        self._start = start
        self._open = self._high = self._low = self._close = price
        self._vol = self._buy = self._sell = 0.0
        self._n = 0
        self._fresh = True  # the first quote of the bar sets its open (a silent bar stays flat)

    def _emit(self) -> Bar:
        q = self._quote
        assert self._start is not None and q is not None
        return Bar(
            symbol=self.symbol,
            start=self._start,
            interval=self.interval,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._vol,
            buy_volume=self._buy,
            sell_volume=self._sell,
            n_trades=self._n,
            bid=q.bid,
            ask=q.ask,
            bid_qty=q.bid_qty,
            ask_qty=q.ask_qty,
        )

    def advance(self, ts: float) -> list[Bar]:
        """Close every bar that ended at or before ``ts``."""
        if self._start is None or ts < self._start + self.interval:
            return []
        out = [self._emit()]
        target = self._bucket(ts)
        nxt = self._start + self.interval
        missing = round((target - nxt) / self.interval)
        if missing > self.max_gap_bars:
            # Feed outage: do not invent hours of flat bars; restart the clock.
            self.gaps += 1
            nxt = target
        else:
            while nxt < target:
                self._reset_bar(nxt, self._close)
                out.append(self._emit())
                nxt += self.interval
        self._reset_bar(nxt, self._close)
        return out

    def on_quote(self, q: Quote) -> list[Bar]:
        if q.symbol != self.symbol or not q.valid:
            return []
        if self._start is None:
            self._quote = q
            self._reset_bar(self._bucket(q.ts), q.mid)
            self._fresh = False  # this quote already opened the bar
            return []
        bars = self.advance(q.ts)
        self._quote = q
        mid = q.mid
        if self._fresh:
            self._open = self._high = self._low = mid
            self._fresh = False
        self._high = max(self._high, mid)
        self._low = min(self._low, mid)
        self._close = mid
        return bars

    def on_trade(self, t: TradeTick) -> list[Bar]:
        if t.symbol != self.symbol or self._start is None:
            return []  # bars start with the first quote
        bars = self.advance(t.ts)
        self._vol += t.qty
        if t.buyer_is_maker:
            self._sell += t.qty
        else:
            self._buy += t.qty
        self._n += 1
        return bars
