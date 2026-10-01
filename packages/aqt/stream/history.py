"""Historical simulation: Binance 1-second klines → event stream for the streaming engine.

Binance publishes 1-second klines with the taker-buy volume, which gives price *and* signed
order flow for every second of the last days. Each kline becomes:

* four quotes inside the second — open, then the two extremes (low first on an up-second, high
  first on a down-second, the conservative path for a long book), then close — around the
  price with an assumed spread, because historical top-of-book is not public;
* two aggregated trades — taker buys and taker sells of that second.

The displayed size of each quote is set to the volume traded in that second, so orders larger
than what actually traded pay the exchange's impact; and since both sides get the same size the
book-imbalance feature is neutral (0) in simulations. Everything else — engine, strategies,
shadow evidence, Risk Engine, paper exchange — is exactly the live code.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd

from aqt.stream.binance import REST_URL, FeedStatus, system_ssl_context
from aqt.stream.events import Event, Quote, TradeTick

KLINE_COLUMNS = ("open_time", "open", "high", "low", "close", "volume", "taker_buy_volume")
_DAY_MS = 86_400_000


def _fetch_range(client: httpx.Client, symbol: str, start_ms: int, end_ms: int) -> list[list[str]]:
    rows: list[list[str]] = []
    cursor = start_ms
    while cursor < end_ms:
        r = client.get(
            "/api/v3/klines",
            params={"symbol": symbol, "interval": "1s", "startTime": cursor,
                    "endTime": end_ms - 1, "limit": 1000},
        )  # fmt: skip
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + 1000
    return rows


def klines_frame(rows: Iterable[Sequence[object]]) -> pd.DataFrame:
    """Binance kline rows → typed frame with :data:`KLINE_COLUMNS`."""
    df = pd.DataFrame(
        [(r[0], r[1], r[2], r[3], r[4], r[5], r[9]) for r in rows], columns=list(KLINE_COLUMNS)
    )
    df = df.astype({"open_time": "int64"} | {c: "float64" for c in KLINE_COLUMNS[1:]})
    return df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def load_klines_1s(
    symbol: str,
    start_ms: int,
    end_ms: int,
    cache_dir: str | Path = "data/stream/klines",
    base_url: str = REST_URL,
    workers: int = 6,
) -> pd.DataFrame:  # pragma: no cover - network
    """1-second klines for ``[start_ms, end_ms)``. Complete UTC days are cached as Parquet."""
    cache = Path(cache_dir) / symbol.upper()
    cache.mkdir(parents=True, exist_ok=True)
    now_ms = int(time.time() * 1000)
    day0 = start_ms // _DAY_MS * _DAY_MS
    chunks: list[tuple[int, int, Path | None]] = []
    for day in range(day0, end_ms, _DAY_MS):
        lo, hi = max(day, start_ms), min(day + _DAY_MS, end_ms)
        complete = day + _DAY_MS <= now_ms
        path = cache / f"{pd.Timestamp(day, unit='ms'):%Y-%m-%d}.parquet" if complete else None
        chunks.append((lo, hi, path))

    # Split uncached ranges into ~1h pieces fetched in parallel (each is ≤ 4 requests).
    def fetch_day(day_lo: int, day_hi: int) -> pd.DataFrame:
        pieces = [(a, min(a + 3_600_000, day_hi)) for a in range(day_lo, day_hi, 3_600_000)]
        with (
            httpx.Client(base_url=base_url, timeout=20, verify=system_ssl_context()) as client,
            ThreadPoolExecutor(workers) as pool,
        ):
            parts = list(pool.map(lambda p: _fetch_range(client, symbol, *p), pieces))
        return klines_frame(row for part in parts for row in part)

    frames = []
    for lo, hi, path in chunks:
        if path is not None and path.exists():
            day_df = pd.read_parquet(path)
        else:
            day_start = lo // _DAY_MS * _DAY_MS
            day_df = fetch_day(day_start if path else lo, day_start + _DAY_MS if path else hi)
            if path is not None:
                day_df.to_parquet(path, index=False)
        frames.append(day_df[(day_df.open_time >= lo) & (day_df.open_time < hi)])
    return pd.concat(frames, ignore_index=True) if frames else klines_frame([])


def resample_klines(df: pd.DataFrame, rule: str = "1min") -> pd.DataFrame:
    """1-second klines → OHLCV bars (UTC index) keeping ``taker_buy_volume`` for flow features.

    Bars are labelled by their start; a bar is complete only once the next one begins, which is
    exactly how the backtester consumes them (decide on close, fill at the next open).
    """
    if df.empty:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume", "taker_buy_volume"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
    idx = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    frame = df.set_index(idx)
    out = frame.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
         "taker_buy_volume": "sum"}
    )  # fmt: skip
    out = out.dropna(subset=["open"])
    return out.astype(float)


def kline_events(df: pd.DataFrame, symbol: str, spread_pct: float = 0.0001) -> Iterator[Event]:
    """Turn 1-second klines into quotes + trades (see the module docstring)."""
    half = spread_pct / 2
    for t, o, h, lo, c, v, tb in df[list(KLINE_COLUMNS)].itertuples(index=False, name=None):
        ts = t / 1000.0
        size = max(v, 1e-9)
        path = (o, lo, h, c) if c >= o else (o, h, lo, c)
        for k, mid in enumerate(path):
            yield Quote(symbol, ts + 0.2 * k, mid * (1 - half), size, mid * (1 + half), size)
        if tb > 0:
            yield TradeTick(symbol, ts + 0.85, c, tb, False)
        if v - tb > 1e-12:
            yield TradeTick(symbol, ts + 0.9, c, v - tb, True)


def merge_events(streams: Sequence[Iterable[Event]]) -> Iterator[Event]:
    """Time-ordered merge of per-symbol event streams."""
    import heapq

    return heapq.merge(*streams, key=lambda e: e.ts)


@dataclass
class SimulationInfo:
    start_ts: float
    end_ts: float
    sim_ts: float
    speed: float
    finished: bool
    paused: bool = False

    @property
    def progress(self) -> float:
        span = self.end_ts - self.start_ts
        return 1.0 if span <= 0 else min(1.0, max(0.0, (self.sim_ts - self.start_ts) / span))


class HistoricalFeed:
    """Replays events paced by ``speed`` (× real time; 0 = as fast as possible).

    The simulation clock (:meth:`now`) is the timestamp of the last event, so the engine, the
    Risk Engine's stale-data check and the dashboard all live in simulated time.
    """

    def __init__(
        self, events: Iterable[Event], start_ts: float, end_ts: float, speed: float = 60.0
    ):
        if speed < 0:
            raise ValueError("speed must be >= 0")
        self._events = events
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.speed = speed
        self.sim_ts = start_ts
        self.finished = False
        self.status = FeedStatus()
        self._anchor: tuple[float, float] | None = None  # (wall, sim) pacing reference
        self.paused = False
        self._resume: asyncio.Event | None = None

    def pause(self, paused: bool) -> None:
        """Hold the replay (e.g. while the Research Lab studies the data seen so far)."""
        self.paused = paused
        if self._resume is None:
            self._resume = asyncio.Event()
        if paused:
            self._resume.clear()
        else:
            self._anchor = None
            self._resume.set()

    def now(self) -> float:
        return self.sim_ts

    def set_speed(self, speed: float) -> None:
        if speed < 0:
            raise ValueError("speed must be >= 0")
        self.speed = speed
        self._anchor = None

    def info(self) -> SimulationInfo:
        return SimulationInfo(
            self.start_ts, self.end_ts, self.sim_ts, self.speed, self.finished, self.paused
        )

    async def events(self) -> AsyncIterator[Event]:
        self.status.connected = True
        for n, e in enumerate(self._events, 1):
            if self.paused and self._resume is not None:
                await self._resume.wait()
            if self.speed > 0:
                if self._anchor is None:
                    self._anchor = (time.monotonic(), e.ts)
                wall0, sim0 = self._anchor
                delay = wall0 + (e.ts - sim0) / self.speed - time.monotonic()
                if delay > 0.005:
                    await asyncio.sleep(delay)
            if n % 2000 == 0:
                await asyncio.sleep(0)  # keep the API responsive at full speed
            self.sim_ts = max(self.sim_ts, e.ts)
            self.status.messages += 1
            self.status.last_message_at = self.sim_ts
            yield e
        self.finished = True
