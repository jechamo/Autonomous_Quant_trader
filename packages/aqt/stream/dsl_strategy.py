"""Run Research-Lab rules (the declarative DSL) inside the live streaming engine.

The engine produces short bars (e.g. 5 s). A rule was researched on longer bars (e.g. 1 min),
so :class:`ResearchBarBook` rebuilds those bars from the engine bars — same open/high/low/close,
volume and taker-buy volume as ``history.resample_klines`` — and computes the *same*
``FeatureEngine`` columns. A research bar is final when the engine bar ending on its boundary
arrives; the rule is evaluated on that last row exactly as ``run_backtest`` evaluates it on the
bar close, and the order then fills after the latency against later quotes (≈ next open).

Stops/targets in ATR multiples are converted to percentages at decision time; holding limits in
research bars are converted to engine bars. Rules were validated net of costs by the lab, so the
engine's generic cost gate is disabled for them (``min_cost_multiple = 0``).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import pandas as pd

from aqt.features.cross_section import augment
from aqt.features.engine import FeatureEngine
from aqt.news.book import NewsBook
from aqt.strategies.dsl import StrategySpec
from aqt.stream.bars import Bar
from aqt.stream.features import FeatureSnapshot
from aqt.stream.strategies import EntryIntent, StreamStrategy

_COLUMNS = ["open", "high", "low", "close", "volume", "taker_buy_volume"]


@dataclass
class _Series:
    bars: deque[tuple[float, float, float, float, float, float, float]]
    bucket: float | None = None
    agg: list[float] = field(default_factory=list)  # o, h, l, c, v, tb of the open bucket
    features: pd.DataFrame | None = None
    final_seq: int = 0  # increments every time a research bar completes


class ResearchBarBook:
    """Shared research bars + features per (symbol, timeframe); idempotent per engine bar."""

    def __init__(
        self,
        window: int = 1000,
        bvc: bool = False,
        session: str = "24/7",
        news: NewsBook | None = None,
    ) -> None:
        self.window = window
        # Stocks: estimate taker-buy volume with BVC from bar returns, as research does.
        self.bvc = bvc
        self.session = session  # calendar features (minutes to the New York close for stocks)
        self.news = news  # live headlines (a poller keeps it current) -> news_* features
        self._series: dict[tuple[str, float], _Series] = {}
        self._seen: dict[tuple[str, float], float] = {}
        self._fe = FeatureEngine()
        self._pre: dict[tuple[str, float], pd.DataFrame] = {}

    def series(self, symbol: str, timeframe: float) -> _Series:
        key = (symbol, timeframe)
        if key not in self._series:
            self._series[key] = _Series(deque(maxlen=self.window))
        return self._series[key]

    def seed(self, symbol: str, timeframe: float, df: pd.DataFrame) -> None:
        """Pre-load completed research bars (e.g. recent REST klines) so rules need no warm-up."""
        self.seed_many(timeframe, {symbol: df})

    def seed_many(self, timeframe: float, frames: dict[str, pd.DataFrame]) -> None:
        """Pre-load several symbols, then compute features once with the complete panel.

        Seeding is history, not a new bar: it does not advance ``final_seq``, so no rule acts on a
        signal from a bar that closed before the trader started.
        """
        for symbol, df in frames.items():
            s = self.series(symbol, timeframe)
            cols = df.reindex(columns=_COLUMNS).fillna({"taker_buy_volume": 0.0})
            starts = [t.timestamp() for t in pd.DatetimeIndex(df.index)]
            for start, row in zip(starts, cols.to_numpy(dtype=float), strict=True):
                o, h, lo, c, v, tb = (float(x) for x in row)
                s.bars.append((float(start), o, h, lo, c, v, tb))
        for symbol in frames:
            self._refresh(symbol, timeframe, bump=False)

    def preload(self, symbol: str, timeframe: float, features: pd.DataFrame) -> None:
        """Replays only: features already computed causally over the whole history.

        Row ``t`` of a causal feature frame only depends on bars ≤ t, so looking it up when bar
        ``t`` completes is equivalent to recomputing it — and ~1000× cheaper over days of ticks.
        Live trading never uses this path.
        """
        self._pre[(symbol, timeframe)] = features

    def on_bar(self, bar: Bar, timeframe: float) -> None:
        key = (bar.symbol, timeframe)
        if self._seen.get(key, -math.inf) >= bar.start:
            return  # another rule already fed this engine bar
        self._seen[key] = bar.start
        s = self.series(bar.symbol, timeframe)
        bucket = math.floor(bar.start / timeframe + 1e-9) * timeframe
        if s.bucket is not None and bucket != s.bucket:
            # A later bucket started before the boundary bar arrived (sparse data, e.g. a quiet
            # market or an hourly replay): the open research bar is complete — close it first.
            self._finalize(bar.symbol, timeframe, s)
        if s.bucket is None:
            s.bucket = bucket
            s.agg = [bar.open, bar.high, bar.low, bar.close, bar.volume, bar.buy_volume]
        else:
            a = s.agg
            a[1] = max(a[1], bar.high)
            a[2] = min(a[2], bar.low)
            a[3] = bar.close
            a[4] += bar.volume
            a[5] += bar.buy_volume
        if bar.end >= bucket + timeframe - 1e-6:  # research bar complete
            self._finalize(bar.symbol, timeframe, s)

    def _finalize(self, symbol: str, timeframe: float, s: _Series) -> None:
        assert s.bucket is not None
        bucket = s.bucket
        s.bars.append((bucket, *s.agg))  # type: ignore[arg-type]
        s.bucket = None
        pre = self._pre.get((symbol, timeframe))
        if pre is None:
            self._refresh(symbol, timeframe)
        else:
            pos = pre.index.searchsorted(pd.Timestamp(bucket, unit="s", tz="UTC"), side="right")
            s.final_seq += 1
            s.features = pre.iloc[max(pos - 2, 0) : pos] if pos else None

    def _frame(self, s: _Series) -> pd.DataFrame:
        idx = pd.to_datetime([b[0] for b in s.bars], unit="s", utc=True)
        df = pd.DataFrame([b[1:] for b in s.bars], index=idx, columns=_COLUMNS)
        df = df[df["volume"] >= 0]
        if self.bvc:
            from aqt.stream.stocks import bvc_taker_buy

            df["taker_buy_volume"] = bvc_taker_buy(df)
        return df

    def _refresh(self, symbol: str, timeframe: float, bump: bool = True) -> None:
        """Recompute ``symbol``'s features with the cross-sectional panel of every symbol at
        this timeframe (the same :func:`augment` research uses)."""
        s = self.series(symbol, timeframe)
        if bump:
            s.final_seq += 1
        if len(s.bars) < 2:
            s.features = None
            return
        frames = {
            sym: self._frame(other)
            for (sym, tf), other in self._series.items()
            if tf == timeframe and len(other.bars) >= 2
        }
        try:
            s.features = self._fe.compute(
                augment(frames, timeframe, self.session, self.news)[symbol]
            )
        except ValueError:  # degenerate window (e.g. a non-positive price)
            s.features = None


def _row_context(row: pd.Series) -> dict[str, float]:
    """Numeric, finite features of the decision bar (stored with the trade for meta-learning)."""
    out: dict[str, float] = {}
    for k, v in row.items():
        if isinstance(v, bool | int | float) and not isinstance(v, str):
            f = float(v)
            if math.isfinite(f) and k not in ("open", "high", "low", "close", "volume"):
                out[str(k)] = f
    return out


TIMEFRAME_LABELS = {60.0: "1min", 300.0: "5min", 900.0: "15min", 3600.0: "1h",
                    14400.0: "4h", 86400.0: "1d"}  # fmt: skip


def rule_id_for(spec: StrategySpec, symbol: str, timeframe_s: float = 60.0) -> str:
    """Stable id of a rendered rule on a symbol and timeframe (also its live ``strategy_id``)."""
    rendered = spec.render()
    rid = f"{rendered.family}:{symbol}:{rendered.config_hash()[:8]}"
    if timeframe_s != 60.0:
        rid += f"@{TIMEFRAME_LABELS.get(timeframe_s, f'{timeframe_s:g}s')}"
    return rid


@dataclass
class DslStreamStrategy(StreamStrategy):
    spec: StrategySpec
    symbol: str
    strategy_id: str = ""
    timeframe_s: float = 60.0
    engine_bar_s: float = 5.0
    book: ResearchBarBook = field(default_factory=ResearchBarBook)
    min_cost_multiple: float = 0.0
    description: str = ""
    # Swing rules (bars of 1 h or more) may hold positions overnight; intraday ones never do.
    overnight: bool | None = None

    def __post_init__(self) -> None:
        self.spec = self.spec.render()
        if self.overnight is None:
            self.overnight = self.timeframe_s >= 3600
        if not self.strategy_id:
            self.strategy_id = rule_id_for(self.spec, self.symbol, self.timeframe_s)
        if not self.description:
            self.description = self.spec.description or self.spec.name
        self._entry_seq = 0  # a seeded book is at seq 0: wait for the first new bar
        self._needs = self.spec.entry.features_used() | (
            self.spec.exit.exit_signal.features_used() if self.spec.exit.exit_signal else set()
        )
        self._exit_seq = -1
        self._exit_now = False

    @property
    def _ratio(self) -> float:
        return self.timeframe_s / self.engine_bar_s

    def on_bar(self, bar: Bar) -> None:
        # Every symbol feeds the book: cross-sectional features need the whole universe.
        self.book.on_bar(bar, self.timeframe_s)

    def _last_row(self) -> tuple[pd.DataFrame, int] | None:
        s = self.book.series(self.symbol, self.timeframe_s)
        if s.features is None or s.features.empty:
            return None
        if not self._needs <= set(s.features.columns):
            return None  # e.g. a news rule while no news source is connected: never signal
        return s.features, s.final_seq

    def entry(self, f: FeatureSnapshot) -> EntryIntent | None:
        if f.symbol != self.symbol:
            return None
        last = self._last_row()
        if last is None:
            return None
        feats, seq = last
        if seq == self._entry_seq:
            return None  # evaluate each research bar once, on its close
        self._entry_seq = seq
        # The last two rows are enough for every operator (``crosses_*`` looks one bar back).
        if not bool(self.spec.entry.evaluate(feats.tail(2)).iloc[-1]):
            return None
        row = feats.iloc[-1]
        close = float(row["close"])
        atr = float(row["atr"]) if "atr" in row and pd.notna(row["atr"]) else math.nan
        ex = self.spec.exit
        stops, targets = [], []
        if ex.stop_atr_mult is not None and math.isfinite(atr):
            stops.append(float(ex.stop_atr_mult) * atr / close)
        if ex.stop_pct is not None:
            stops.append(float(ex.stop_pct))
        if not stops:
            return None  # same rule as the backtester: no measurable risk, no trade
        if ex.target_atr_mult is not None and math.isfinite(atr):
            targets.append(float(ex.target_atr_mult) * atr / close)
        if ex.target_pct is not None:
            targets.append(float(ex.target_pct))
        hold = ex.max_holding_bars
        max_hold = round(float(hold) * self._ratio) if hold is not None else 10**9
        return EntryIntent(
            self.strategy_id,
            self.symbol,
            f.ts,
            min(stops),  # the tightest stop, as in run_backtest (max of stop prices)
            min(targets) if targets else 10.0,  # no target: effectively exit by rule/time/stop
            max_hold,
            self.spec.name,
            context=_row_context(row),
        )

    def should_exit(self, f: FeatureSnapshot) -> bool:
        if f.symbol != self.symbol or self.spec.exit.exit_signal is None:
            return False
        last = self._last_row()
        if last is None:
            return False
        feats, seq = last
        if seq != self._exit_seq:  # once per research bar; shadow and paper read the same answer
            self._exit_seq = seq
            self._exit_now = bool(self.spec.exit.exit_signal.evaluate(feats.tail(2)).iloc[-1])
        return self._exit_now
