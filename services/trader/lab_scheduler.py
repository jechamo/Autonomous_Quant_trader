"""Scheduled Research Lab inside the trader: research every N hours, review every hour.

The research cycle is CPU-heavy (thousands of backtests), so it runs as a *separate process*
(``python -m services.trader research``) writing to the same SQLite file; the trading loop never
waits for it. When it finishes — and once an hour — live rules are reviewed against their forward
evidence (as the Risk Engine sees it) and the engine's strategy set is hot-swapped.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aqt.lab.learning import learn_meta_filters
from aqt.lab.live import sync_engine_rules
from aqt.lab.registry import RuleRegistry, RuleStatus
from aqt.lab.review import ReviewConfig, review_rules
from aqt.stream.dsl_strategy import ResearchBarBook
from aqt.stream.engine import StreamingEngine
from aqt.stream.store import SQLiteStore

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")

# research(end_ts) -> "" on success or an error message
ResearchRunner = Callable[[float], Awaitable[str]]


@dataclass
class LabStatus:
    enabled: bool
    every_s: float
    running: bool = False
    last_started: float | None = None
    last_finished: float | None = None
    next_due: float | None = None
    last_error: str = ""
    last_changes: int = 0
    last_review: float | None = None
    briefing: bool = False
    last_briefing: float | None = None
    briefing_error: str = ""


def subprocess_runner(
    db_path: str, symbols: list[str], days: float, extra: list[str]
) -> ResearchRunner:
    """Run ``python -m services.trader research`` as an isolated child process."""

    async def run(end_ts: float) -> str:
        end = datetime.fromtimestamp(end_ts, UTC).strftime("%Y-%m-%dT%H:%M:%S")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "services.trader", "research",
            "--db", db_path, "--symbols", ",".join(symbols), "--days", str(days),
            "--end", end, "--no-review", *extra,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        out, err = await proc.communicate()
        if proc.returncode != 0:
            return (err or out).decode("utf-8", "replace")[-500:] or f"exit {proc.returncode}"
        return ""

    return run


def news_runner(db_path: str, market: str, symbols: list[str]) -> ResearchRunner:
    """Run ``python -m services.trader news`` (the morning briefing) as a child process."""

    async def run(now: float) -> str:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "services.trader", "news", "--db", db_path,
            "--market", market, "--symbols", ",".join(symbols),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        out, err = await proc.communicate()
        if proc.returncode != 0:
            return (err or out).decode("utf-8", "replace")[-500:] or f"exit {proc.returncode}"
        return ""

    return run


class LabScheduler:
    def __init__(
        self,
        engine: StreamingEngine,
        store: SQLiteStore,
        book: ResearchBarBook,
        research: ResearchRunner | None,
        every_s: float = 6 * 3600,
        review_every_s: float = 3600,
        clock: Callable[[], float] = time.time,
        poll_s: float = 5.0,
        baseline: bool = True,
        review_cfg: ReviewConfig | None = None,
        on_pause: Callable[[bool], None] | None = None,
        seeder: Callable[[float], None] | None = None,
        briefing: ResearchRunner | None = None,
        briefing_at: tuple[int, int] = (8, 45),
    ) -> None:
        self.engine = engine
        self.store = store
        self.book = book
        self.research = research
        self.clock = clock
        self.registry = RuleRegistry(store, clock)
        self.review_every_s = review_every_s
        self.poll_s = poll_s
        self.baseline = baseline
        self.review_cfg = review_cfg
        self.on_pause = on_pause  # simulations pause the replay while researching
        # Loads history for a timeframe the first time an active rule needs it (no warm-up).
        self.seeder = seeder
        self._seeded: set[float] = {60.0}
        # Morning news briefing once per New York weekday, from ``briefing_at`` (before the open).
        self.briefing = briefing
        self.briefing_at = briefing_at
        enabled = research is not None and every_s > 0
        self.state = LabStatus(enabled=enabled, every_s=every_s, briefing=briefing is not None)
        done = [r["finished_at"] for r in self.registry.runs(1) if r["finished_at"]]
        self.state.last_finished = done[0] if done else None
        if enabled:
            self.state.next_due = (done[0] + every_s) if done else clock()
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ actions
    def sync(self) -> dict[str, list[str]]:
        if self.seeder is not None:
            for tf in sorted({r.timeframe_s for r in self.registry.active() if r.timeframe_s}):
                if tf not in self._seeded:
                    try:
                        self.seeder(tf)
                    except Exception as exc:  # the rule then warms up live
                        log.warning("could not pre-load %ss bars: %s", tf, exc)
                    self._seeded.add(tf)
        return sync_engine_rules(self.engine, self.registry, self.book, self.baseline)

    def review(self) -> list[dict[str, Any]]:
        changes = review_rules(
            self.store,
            self.engine.cfg.run_id,
            self.engine.profile,
            self.engine.evidence.table(),
            self.review_cfg,
            self.clock,
        )
        self.state.last_review = self.clock()
        self.state.last_changes = len(changes)
        swapped = self.sync()
        if changes or swapped["added"] or swapped["removed"]:
            log.info("lab review: %s changes, strategies %s", len(changes), swapped)
        return changes

    def learn(self) -> list[dict[str, Any]]:
        """Meta-learning from every live strategy's wins and losses (see aqt.lab.learning)."""
        ids = [s.strategy_id for s in self.engine.strategies]
        learned = learn_meta_filters(self.store, self.engine.cfg.run_id, self.registry, ids)
        return [x for x in learned if x["accepted"]]

    async def review_async(self) -> None:
        """Review, then learn off the event loop (model training takes a moment), then swap."""
        changes = review_rules(
            self.store,
            self.engine.cfg.run_id,
            self.engine.profile,
            self.engine.evidence.table(),
            self.review_cfg,
            self.clock,
        )
        changes += await asyncio.to_thread(self.learn)
        self.state.last_review = self.clock()
        self.state.last_changes = len(changes)
        self.sync()

    async def run_now(self) -> None:
        if self.research is None or self.state.running:
            return
        self.state.running = True
        self.state.last_started = self.clock()
        if self.on_pause:
            self.on_pause(True)
        try:
            self.state.last_error = await self.research(self.clock())
        except Exception as exc:  # the lab must never take the trader down
            self.state.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self.state.running = False
            self.state.last_finished = self.clock()
            if self.state.enabled:
                self.state.next_due = self.state.last_finished + self.state.every_s
            if self.on_pause:
                self.on_pause(False)
        if self.state.last_error:
            log.warning("research cycle failed: %s", self.state.last_error)
        await self.review_async()

    def briefing_due(self, now: float) -> bool:
        if self.briefing is None:
            return False
        ny = datetime.fromtimestamp(now, NY)
        if ny.weekday() >= 5 or (ny.hour, ny.minute) < self.briefing_at:
            return False
        return self.store.get_setting("briefing_last_attempt") != ny.date().isoformat()

    async def run_briefing(self, now: float) -> None:
        """One attempt per day (a failure is reported, not retried in a loop)."""
        assert self.briefing is not None
        self.store.set_setting(
            "briefing_last_attempt", datetime.fromtimestamp(now, NY).date().isoformat()
        )
        try:
            self.state.briefing_error = await self.briefing(now)
        except Exception as exc:  # the briefing must never take the trader down
            self.state.briefing_error = f"{type(exc).__name__}: {exc}"
        self.state.last_briefing = self.clock()
        if self.state.briefing_error:
            log.warning("news briefing failed: %s", self.state.briefing_error)

    def trigger(self) -> bool:
        """Start a research cycle now (dashboard button). False if one is already running."""
        if self.research is None or self.state.running:
            return False
        self._task = asyncio.create_task(self.run_now(), name="lab-run")
        return True

    async def loop(self) -> None:
        await self.review_async()
        while True:
            now = self.clock()
            if self.briefing_due(now):
                await self.run_briefing(now)
            due = self.state.next_due
            if self.state.enabled and due is not None and now >= due and not self.state.running:
                await self.run_now()
            elif (
                self.state.last_review is None
                or now - self.state.last_review >= self.review_every_s
            ):
                await self.review_async()
            await asyncio.sleep(self.poll_s)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    # ------------------------------------------------------------------ views
    def status(self) -> dict[str, Any]:
        counts = {str(s): 0 for s in RuleStatus}
        for r in self.store.query("SELECT status, COUNT(*) n FROM rules GROUP BY status"):
            counts[r["status"]] = r["n"]
        return {**asdict(self.state), "rules": counts}

    def progress(self) -> dict[str, Any]:
        """Learning progress for the dashboard (funnel, rules, ML, AI, activity feed)."""
        from aqt.lab.progress import learning_progress

        p = self.engine.profile
        return {
            "status": self.status(),
            **learning_progress(
                self.store,
                self.engine.cfg.run_id,
                [s.strategy_id for s in self.engine.strategies],
                self.engine.evidence.table(),
                p.min_edge_score,
                p.min_confidence,
            ),
        }

    def overview(self) -> dict[str, Any]:
        evidence = self.engine.evidence.table()
        rules = []
        for r in self.registry.rules():
            d = r.to_dict()
            row = evidence.get(r.rule_id)
            d["live"] = row.to_dict() if row is not None else None
            rules.append(d)
        from aqt.analyst.hypotheses import HypothesisStore

        return {
            "status": self.status(),
            "hypotheses": HypothesisStore(self.store, self.clock).recent(30),
            "runs": self.registry.runs(10),
            "rules": rules,
            "events": self.registry.events(50),
            "lessons": self.registry.lessons(50),
        }
