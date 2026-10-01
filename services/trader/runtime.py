"""Live runtime: feeds Binance events into the engine, ticks the clock, persists to SQLite."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict
from typing import Protocol

from aqt.stream.binance import FeedStatus
from aqt.stream.engine import StreamingEngine
from aqt.stream.events import Event
from aqt.stream.store import SQLiteStore

from services.trader.lab_scheduler import LabScheduler

log = logging.getLogger(__name__)

SETTING_KEYS = ("kill_switch", "paused", "aggressiveness")


class Feed(Protocol):
    status: FeedStatus

    def events(self) -> AsyncIterator[Event]: ...


class TraderRuntime:
    def __init__(
        self,
        engine: StreamingEngine,
        store: SQLiteStore,
        feed: Feed | None = None,
        record: bool = True,
        clock: Callable[[], float] = time.time,
        tick_seconds: float = 0.5,
        persist_controls: bool = True,
        lab: LabScheduler | None = None,
    ) -> None:
        self.engine = engine
        self.store = store
        self.feed = feed
        self.record = record
        self.clock = clock
        self.tick_seconds = tick_seconds
        self.started_at = clock()
        self._tasks: list[asyncio.Task[None]] = []
        self.persist_controls = persist_controls
        self.lab = lab
        if persist_controls:
            self._restore_settings()

    # ------------------------------------------------------------------ controls
    def _restore_settings(self) -> None:
        s = self.store
        if s.get_setting("kill_switch") == "true":
            self.engine.kill_switch = True
        if s.get_setting("paused") == "true":
            self.engine.paused = True
        agg = s.get_setting("aggressiveness")
        if agg is not None:
            self.engine.set_aggressiveness(float(agg))

    def control(
        self,
        *,
        kill_switch: bool | None = None,
        paused: bool | None = None,
        aggressiveness: float | None = None,
        flatten: bool = False,
        speed: float | None = None,
    ) -> None:
        """Operator controls from the dashboard. Every change is persisted (audit + restart)."""
        e = self.engine
        if kill_switch is not None:
            e.kill_switch = kill_switch
            self._persist("kill_switch", str(kill_switch).lower())
        if aggressiveness is not None:
            e.set_aggressiveness(aggressiveness)
            self._persist("aggressiveness", str(float(aggressiveness)))
        if flatten:
            e.flatten()
        if paused is not None:
            e.paused = paused
        if paused is not None or flatten:
            self._persist("paused", str(e.paused).lower())
        set_speed = getattr(self.feed, "set_speed", None)
        if speed is not None and set_speed is not None:
            set_speed(speed)  # simulations only
        log.info(
            "control: kill_switch=%s paused=%s aggressiveness=%s flatten=%s",
            e.kill_switch, e.paused, e.profile.aggressiveness, flatten,
        )  # fmt: skip

    def _persist(self, key: str, value: str) -> None:
        if self.persist_controls:
            self.store.set_setting(key, value)

    # ------------------------------------------------------------------ loop
    def snapshot(self) -> dict[str, object]:
        snap = self.engine.snapshot()
        st = self.feed.status if self.feed is not None else None
        snap["feed"] = {
            "connected": st.connected if st else False,
            "messages": st.messages if st else 0,
            "reconnects": st.reconnects if st else 0,
            "last_message_age_s": self.clock() - st.last_message_at if st and st.messages else None,
            "last_error": st.last_error if st else "no feed",
        }
        snap["uptime_s"] = self.clock() - self.started_at
        if self.lab is not None:
            snap["lab"] = self.lab.status()
        info = getattr(self.feed, "info", None)
        if info is not None:
            sim = info()
            snap["mode"] = "SIMULATION"
            snap["simulation"] = {**asdict(sim), "progress": sim.progress}
        return snap

    async def _consume(self) -> None:
        assert self.feed is not None
        async for event in self.feed.events():
            if self.record:
                self.store.record(event)
            self.engine.on_event(event)

    async def _tick(self) -> None:
        last_flush = 0.0
        while True:
            now = self.clock()
            if self.feed is not None:
                self.engine.feed_healthy = self.feed.status.healthy(now)
            self.engine.on_time(now)
            if now - last_flush >= 1.0:
                self.store.flush()
                last_flush = now
            await asyncio.sleep(self.tick_seconds)

    def start(self) -> None:
        if self.feed is not None:
            self._tasks.append(asyncio.create_task(self._consume(), name="feed"))
        self._tasks.append(asyncio.create_task(self._tick(), name="clock"))
        if self.lab is not None:
            self._tasks.append(asyncio.create_task(self.lab.loop(), name="lab"))
        venue_loop = getattr(self.engine.broker, "run", None)
        if venue_loop is not None:  # remote venue (Alpaca paper): order routing + reconciliation
            self._tasks.append(asyncio.create_task(venue_loop(), name="venue"))
        for t in self._tasks:
            t.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled() or task.exception() is None:
            return
        # A crashed loop must never leave the engine trading blind.
        self.engine.feed_healthy = False
        self.engine.paused = True
        log.error("task %s crashed; engine paused", task.get_name(), exc_info=task.exception())

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks.clear()
        if self.lab is not None:
            await self.lab.stop()
        self.engine.shutdown()
        self.store.flush()
