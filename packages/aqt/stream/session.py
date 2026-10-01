"""Trading sessions: when orders may be sent and when an intraday book must be flat."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


class Session(Protocol):
    def is_open(self, ts: float) -> bool: ...

    def seconds_to_close(self, ts: float) -> float: ...


@dataclass(frozen=True)
class UsEquitySession:
    open_time: tuple[int, int] = (9, 30)
    close_time: tuple[int, int] = (16, 0)
    holidays: frozenset[date] = field(default_factory=frozenset)

    def _bounds(self, ts: float) -> tuple[datetime, datetime, datetime]:
        now = datetime.fromtimestamp(ts, NY)
        o = now.replace(hour=self.open_time[0], minute=self.open_time[1], second=0, microsecond=0)
        c = now.replace(hour=self.close_time[0], minute=self.close_time[1], second=0, microsecond=0)
        return now, o, c

    def bounds(self, ts: float) -> tuple[float, float]:
        """Epoch seconds of the regular open and close of the New York day containing ``ts``."""
        _, o, c = self._bounds(ts)
        return o.timestamp(), c.timestamp()

    def is_trading_day(self, ts: float) -> bool:
        d = datetime.fromtimestamp(ts, NY).date()
        return d.weekday() < 5 and d not in self.holidays

    def is_open(self, ts: float) -> bool:
        now, o, c = self._bounds(ts)
        return self.is_trading_day(ts) and o <= now < c

    def seconds_to_close(self, ts: float) -> float:
        """Seconds until today's close while open; ``inf`` when the market is closed."""
        if not self.is_open(ts):
            return math.inf
        now, _, c = self._bounds(ts)
        return (c - now).total_seconds()


@dataclass(frozen=True)
class AlwaysOpen:
    """Crypto spot: 24/7."""

    def is_open(self, ts: float) -> bool:
        return True

    def seconds_to_close(self, ts: float) -> float:
        return math.inf


def make_session(name: str) -> Session:
    if name == "24/7":
        return AlwaysOpen()
    if name == "us_equity":
        return UsEquitySession()
    raise ValueError(f"unknown session {name!r}")
