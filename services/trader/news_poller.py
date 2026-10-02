"""Keeps the live :class:`NewsBook` current so news rules see what research saw.

On start it backfills the 22 days the ``news_ratio`` baseline needs, then fetches the latest
headlines every minute (with a 10-minute overlap: late arrivals are de-duplicated by id). Until
the backfill succeeds — or whenever polling falls behind — the book's coverage ends before the
bar close and the news features are NaN, so no news rule can fire on missing data. A failure
never stops trading: it is logged and retried.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from aqt.news.book import BASELINE_DAYS, DAY_S, NewsBook
from aqt.news.items import NewsItem

log = logging.getLogger(__name__)

# fetch(start_s, end_s) -> headlines published in [start, end)
NewsFetcher = Callable[[float, float], list[NewsItem]]
OVERLAP_S = 600.0


@dataclass
class NewsPollerStatus:
    polls: int = 0
    headlines: int = 0
    last_poll: float | None = None
    covered_until: float | None = None
    last_error: str = ""


class NewsPoller:
    def __init__(
        self,
        fetch: NewsFetcher,
        every_s: float = 60.0,
        clock: Callable[[], float] = time.time,
        backfill_days: float = BASELINE_DAYS + 2,
    ) -> None:
        self.fetch = fetch
        self.every_s = every_s
        self.clock = clock
        now = clock()
        self.book = NewsBook(coverage_start=now - backfill_days * DAY_S)
        self.state = NewsPollerStatus()
        self._last_end: float | None = None

    def poll_once(self) -> int:
        now = self.clock()
        start = self.book.coverage_start if self._last_end is None else self._last_end - OVERLAP_S
        items = self.fetch(start, now)
        added = self.book.add(items, covered_until=now)
        self._last_end = now
        self.state.polls += 1
        self.state.headlines += added
        self.state.last_poll = now
        self.state.covered_until = self.book.covered_until
        self.state.last_error = ""
        return added

    async def loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.poll_once)
            except Exception as exc:  # never stop trading over news
                self.state.last_error = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("news poll failed: %s", self.state.last_error)
            await asyncio.sleep(self.every_s)

    def status(self) -> dict[str, Any]:
        return asdict(self.state)
