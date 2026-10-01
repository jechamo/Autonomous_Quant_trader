"""Event-driven streaming trader: quotes/trades → bars → features → strategies → Risk → broker.

The same deterministic engine runs live (Binance WebSocket) and in replay (ticks recorded in
SQLite), so what is validated is exactly what trades. Time is the event clock, never the wall
clock, which keeps replays reproducible and makes look-ahead impossible: a bar is decided on only
once an event after its end has arrived, and orders fill after a latency against later quotes.

Two books run side by side:

* **shadow** — every entry intent of every strategy, traded virtually with the same fill model.
  Its net returns are the forward evidence (Edge Score, BH-FDR) the Risk Engine requires.
* **paper** — real orders on the :class:`PaperExchange`, one position per symbol, each one
  approved (and sized) by :class:`aqt.risk.RiskEngine`. Stops and targets are watched on every
  quote; time stops and strategy exits are evaluated on bar close.

Engine-level guards (pause, order-rate limit, per-symbol cooldown) only ever make the system
*more* restrictive; they never bypass the Risk Engine.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from aqt.brokers.base import BrokerError, OrderRequest
from aqt.brokers.paper import Fill, PaperExchange
from aqt.brokers.venue import ExecutionVenue
from aqt.common.types import OrderSide, OrderStatus
from aqt.risk.engine import RiskDecision, RiskEngine
from aqt.risk.models import MarketState, Portfolio, Position, Signal
from aqt.risk.profile import RiskProfile
from aqt.stream.bars import Bar, BarAggregator
from aqt.stream.events import Event, Quote, TradeTick
from aqt.stream.evidence import EvidenceTracker
from aqt.stream.features import FeatureParams, FeatureSnapshot, IncrementalFeatures
from aqt.stream.records import Decision, RoundTrip
from aqt.stream.session import make_session
from aqt.stream.store import SQLiteStore
from aqt.stream.strategies import EntryIntent, StreamStrategy, default_stream_strategies


def _numeric(d: Mapping[str, Any]) -> dict[str, float]:
    """Finite numeric fields only (booleans as 0/1): a JSON-safe feature context."""
    out = {}
    for k, v in d.items():
        if isinstance(v, bool) or (isinstance(v, int | float) and math.isfinite(v)):
            out[k] = float(v)
    return out


def _finite(x: float) -> float | None:
    return x if math.isfinite(x) else None


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


@dataclass(frozen=True)
class EngineConfig:
    symbols: tuple[str, ...]
    bar_seconds: float = 5.0
    feature_params: FeatureParams = field(default_factory=FeatureParams)
    fee_pct: float = 0.001
    expected_slippage_pct: float = 0.0005
    latency_s: float = 0.25
    initial_cash: float = 100.0
    aggressiveness: float = 50.0
    max_data_age_seconds: float = 10.0
    max_orders_per_minute: int = 6
    entry_cooldown_seconds: float = 30.0
    min_order_notional: float = 5.0
    evidence_window: int = 500
    min_trades: int = 30
    run_id: str = "live"
    currency: str = "EUR"  # quote asset of every symbol (the paper account currency)
    session: str = "24/7"  # "24/7" (crypto) or "us_equity" (09:30-16:00 New York, intraday only)
    no_entry_before_close_s: float = 900.0  # no new positions in the last 15 minutes
    flatten_before_close_s: float = 300.0  # close everything 5 minutes before the bell
    history_bars: int = 720
    equity_every_seconds: float = 5.0

    @property
    def fees_round_trip_pct(self) -> float:
        return 2 * self.fee_pct


@dataclass
class _SymbolState:
    agg: BarAggregator
    features: IncrementalFeatures
    bars: deque[Bar]
    quote: Quote | None = None
    adv: float | None = None  # base-asset volume per day, if known from the exchange
    quantity_step: float = 1e-8
    last_entry_ts: float = -1e18
    scaled: dict[FeatureParams, IncrementalFeatures] = field(default_factory=dict)

    @property
    def warmup_needed(self) -> int:
        return max([self.features.p.warmup, *(p.warmup for p in self.scaled)])


@dataclass
class _VirtualTrade:
    """A position in the shadow book (unit size, returns only)."""

    intent: EntryIntent
    submitted_at: float
    entry_price: float = 0.0
    entry_ts: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    bars_held: int = 0
    exit_submitted_at: float | None = None
    exit_reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.entry_price > 0


@dataclass
class _PaperPosition:
    strategy_id: str
    intent: EntryIntent
    quantity: float
    entry_price: float
    entry_ts: float
    entry_fee: float
    stop: float
    target: float
    bars_held: int = 0
    exit_client_id: str | None = None
    exit_reason: str = ""
    last_exit_attempt: float = -1e18


@dataclass
class _PendingOrder:
    order_id: str
    symbol: str
    side: OrderSide
    strategy_id: str
    intent: EntryIntent | None
    reason: str = ""


class StreamingEngine:
    def __init__(
        self,
        config: EngineConfig,
        strategies: list[StreamStrategy] | None = None,
        broker: ExecutionVenue | None = None,
        store: SQLiteStore | None = None,
    ) -> None:
        if not config.symbols:
            raise ValueError("at least one symbol is required")
        self.cfg = config
        self.strategies = strategies or default_stream_strategies(config.bar_seconds)
        ids = [s.strategy_id for s in self.strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("strategy ids must be unique")
        self.broker: ExecutionVenue = broker or PaperExchange(
            cash=config.initial_cash,
            fee_pct=config.fee_pct,
            latency_s=config.latency_s,
            min_notional=config.min_order_notional,
            currency=config.currency,
        )
        self.store = store
        self.evidence = EvidenceTracker(
            ids, config.fees_round_trip_pct, config.evidence_window, config.min_trades
        )
        if store is not None:
            for sid, r in store.shadow_returns(config.run_id, config.evidence_window * len(ids)):
                if sid in ids:
                    self.evidence.record(sid, r)
        self.symbols: dict[str, _SymbolState] = {
            s: _SymbolState(
                BarAggregator(s, config.bar_seconds),
                IncrementalFeatures(s, config.feature_params),
                deque(maxlen=config.history_bars),
            )
            for s in config.symbols
        }
        for strat in self.strategies:
            self._attach_features(strat)
        self.first_ts: float | None = None
        self.session = make_session(config.session)
        self.kill_switch = False
        self.paused = False
        self.feed_healthy = True
        self.set_aggressiveness(config.aggressiveness)

        self.now = 0.0
        self.events = 0
        self._shadow: dict[tuple[str, str], _VirtualTrade] = {}
        self._positions: dict[str, _PaperPosition] = {}
        self._pending: dict[str, _PendingOrder] = {}  # client_order_id -> order meta
        self._order_times: deque[float] = deque()
        self._signal_seq = 0
        self.equity_peak = config.initial_cash
        self.day_start_equity = config.initial_cash
        self._day: int | None = None
        self._bh_first: dict[str, float] = {}  # first mid per symbol (Buy & Hold benchmark)
        self.consecutive_losses = 0
        self.realized_pnl = 0.0
        self._last_equity_log = -1e18
        self.decisions: deque[Decision] = deque(maxlen=300)
        self.paper_log: deque[RoundTrip] = deque(maxlen=300)
        self.shadow_log: deque[RoundTrip] = deque(maxlen=300)
        self.equity_history: deque[tuple[float, float, float]] = deque(maxlen=5000)
        self.counters = {
            "signals": 0,
            "approved": 0,
            "rejected": 0,
            "throttled": 0,
            "fills": 0,
            "paper_trades": 0,
            "cost_blocked": 0,
        }
        self._cost_blocked: set[tuple[str, str]] = set()
        self._retiring: set[str] = set()
        self.strategy_stats: dict[str, dict[str, Any]] = {
            s.strategy_id: self._new_stats() for s in self.strategies
        }

    @staticmethod
    def _new_stats() -> dict[str, Any]:
        return {
            "signals": 0,
            "cost_blocked": 0,
            "last_target_pct": None,
            "last_min_target_pct": None,
        }

    def _attach_features(self, strat: StreamStrategy) -> None:
        for st in self.symbols.values():
            if strat.features is not None and strat.features not in st.scaled:
                st.scaled[strat.features] = IncrementalFeatures(st.agg.symbol, strat.features)

    def _has_open(self, strategy_id: str) -> bool:
        return (
            any(k[0] == strategy_id for k in self._shadow)
            or any(p.strategy_id == strategy_id for p in self._positions.values())
            or any(m.strategy_id == strategy_id for m in self._pending.values())
        )

    def set_strategies(self, strategies: list[StreamStrategy]) -> dict[str, list[str]]:
        """Hot-swap the strategy set (Research Lab promotions / retirements).

        Kept strategies keep their state and evidence; new ones start from their stored forward
        history (if any). A removed strategy with open shadow/paper trades stops taking entries
        and is dropped once those trades are closed.
        """
        ids = [s.strategy_id for s in strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("strategy ids must be unique")
        current = {s.strategy_id: s for s in self.strategies}
        wanted = set(ids)
        added = [s for s in strategies if s.strategy_id not in current]
        removed = [sid for sid in current if sid not in wanted]
        kept_retiring = [current[sid] for sid in removed if self._has_open(sid)]
        self.strategies = [current.get(s.strategy_id, s) for s in strategies] + kept_retiring
        self._retiring = {s.strategy_id for s in kept_retiring}
        for strat in added:
            history: list[float] = []
            if self.store is not None:
                history = self.store.strategy_returns(self.cfg.run_id, strat.strategy_id)
            self.evidence.add(strat.strategy_id, history[-self.evidence.window :])
            self.strategy_stats[strat.strategy_id] = self._new_stats()
            self._attach_features(strat)
        for sid in removed:
            if sid not in self._retiring:
                self._drop_strategy(sid)
        return {"added": [s.strategy_id for s in added], "removed": removed}

    def _drop_strategy(self, strategy_id: str) -> None:
        self.strategies = [s for s in self.strategies if s.strategy_id != strategy_id]
        self.evidence.remove(strategy_id)
        self.strategy_stats.pop(strategy_id, None)
        self._retiring.discard(strategy_id)
        self._cost_blocked = {k for k in self._cost_blocked if k[0] != strategy_id}

    # ------------------------------------------------------------------ controls
    def set_aggressiveness(self, level: float) -> None:
        base = RiskProfile.from_aggressiveness(level)
        self.profile = replace(
            base,
            max_data_age_seconds=min(base.max_data_age_seconds, self.cfg.max_data_age_seconds),
            min_order_notional=max(base.min_order_notional, self.cfg.min_order_notional),
        )
        self.risk = RiskEngine(self.profile)

    def set_adv(self, symbol: str, base_volume_per_day: float) -> None:
        self.symbols[symbol].adv = base_volume_per_day

    def set_quantity_step(self, symbol: str, step: float) -> None:
        if step <= 0:
            raise ValueError("step must be > 0")
        self.symbols[symbol].quantity_step = step

    def flatten(self, reason: str = "manual_flatten") -> None:
        """Pause new entries and request an exit for every paper position."""
        self.paused = True
        for symbol in list(self._positions):
            self._request_exit(symbol, reason, force=True)

    def shutdown(self) -> None:
        """Orderly stop: close paper positions at the current bid so the book is never orphaned.

        This is the paper equivalent of flattening before switching the bot off; it does not
        go through the Risk Engine because it can only reduce exposure.
        """
        for symbol, pos in list(self._positions.items()):
            self._signal_seq += 1
            cid = f"{pos.strategy_id}:{symbol}:SELL:shutdown-{self._signal_seq}"
            for c, meta in list(self._pending.items()):
                if meta.symbol == symbol:
                    del self._pending[c]
            fill = self.broker.liquidate_now(symbol, cid)
            if fill is not None:
                pos.exit_reason = "shutdown"
                self._pending[cid] = _PendingOrder(
                    fill.order_id, symbol, OrderSide.SELL, pos.strategy_id, None, "shutdown"
                )
                self._on_fill(fill)
        self._last_equity_log = -1e18
        self._maybe_log_equity()

    # ------------------------------------------------------------------ event loop
    def on_event(self, event: Event) -> None:
        st = self.symbols.get(event.symbol)
        if st is None:
            return
        self.events += 1
        if self.first_ts is None:
            self.first_ts = event.ts
        self._tick_clock(event.ts)
        if isinstance(event, Quote):
            if not event.valid:
                return
            st.quote = event
            if event.symbol not in self._bh_first:
                self._bh_first[event.symbol] = event.mid
            for bar in st.agg.on_quote(event):
                self._on_bar(bar)
            for fill in self.broker.on_quote(event):
                self._on_fill(fill)
            self._sweep_pending()
            self._watch_quote(event)
        elif isinstance(event, TradeTick):
            for bar in st.agg.on_trade(event):
                self._on_bar(bar)
        self._maybe_log_equity()

    def on_time(self, ts: float) -> None:
        """Wall-clock tick from the live runner: closes bars when the market is quiet."""
        self._tick_clock(ts)
        for st in self.symbols.values():
            for bar in st.agg.advance(ts):
                self._on_bar(bar)
        self._maybe_log_equity()

    def _tick_clock(self, ts: float) -> None:
        self.now = max(self.now, ts)
        self.broker.set_time(self.now)
        day = int(self.now // 86_400)  # UTC day number (cheap: runs on every event)
        if day != self._day:
            self._day = day
            self.day_start_equity = self.equity

    # ------------------------------------------------------------------ bars & signals
    def _on_bar(self, bar: Bar) -> None:
        st = self.symbols[bar.symbol]
        st.bars.append(bar)
        for strat in self.strategies:
            strat.on_bar(bar)
        f = st.features.update(bar)
        # One snapshot per feature time scale; each strategy reads the one it declared.
        snaps: dict[FeatureParams | None, FeatureSnapshot] = {None: f}
        for params, feats in st.scaled.items():
            snaps[params] = feats.update(bar)
        for vt in self._shadow.values():
            if vt.intent.symbol == bar.symbol and vt.is_open:
                vt.bars_held += 1
        pos = self._positions.get(bar.symbol)
        if pos is not None:
            pos.bars_held += 1
        cost = self.cfg.fees_round_trip_pct + f.spread_pct + 2 * self.cfg.expected_slippage_pct
        by_id = {s.strategy_id: s for s in self.strategies}

        def swing(sid: str) -> bool:
            s = by_id.get(sid)
            return bool(s is not None and s.overnight)

        to_close = self.session.seconds_to_close(self.now)
        if to_close <= self.cfg.flatten_before_close_s:  # intraday rules never hold overnight
            for (sid, sym), vt in self._shadow.items():
                open_intraday = vt.is_open and vt.exit_submitted_at is None and not swing(sid)
                if sym == bar.symbol and open_intraday:
                    self._shadow_exit(vt, "session_end")
            if pos is not None and not swing(pos.strategy_id):
                self._request_exit(bar.symbol, "session_end")
        session_open = self.session.is_open(self.now)
        late = to_close <= self.cfg.no_entry_before_close_s

        def wants_exit(sid: str) -> bool:
            s = by_id[sid]
            fs = snaps[s.features]
            return fs.ready and s.should_exit(fs)

        # Bar-close exits: time stop and strategy exit signal.
        for (sid, sym), vt in self._shadow.items():
            if sym == bar.symbol and vt.is_open and vt.exit_submitted_at is None:
                if vt.bars_held >= vt.intent.max_hold_bars:
                    self._shadow_exit(vt, "time")
                elif wants_exit(sid):
                    self._shadow_exit(vt, "signal")
        if pos is not None:
            if pos.bars_held >= pos.intent.max_hold_bars:
                self._request_exit(bar.symbol, "time")
            elif wants_exit(pos.strategy_id):
                self._request_exit(bar.symbol, "signal")

        for sid in [s for s in self._retiring if not self._has_open(s)]:
            self._drop_strategy(sid)
        for strat in self.strategies:
            if not session_open:
                break
            if late and not strat.overnight:
                continue  # intraday: no new positions in the last minutes of the session
            if strat.strategy_id in self._retiring:
                continue  # removed by the lab: manage open trades, take no new ones
            key = (strat.strategy_id, bar.symbol)
            intent = strat.entry(snaps[strat.features])
            if intent is None:
                self._cost_blocked.discard(key)
                continue
            stats = self.strategy_stats[strat.strategy_id]
            stats["last_target_pct"] = intent.target_pct
            stats["last_min_target_pct"] = strat.min_cost_multiple * cost
            if not strat.clears_costs(intent, cost):
                if key not in self._cost_blocked:  # count episodes, not bars
                    self._cost_blocked.add(key)
                    stats["cost_blocked"] += 1
                    self.counters["cost_blocked"] += 1
                continue
            self._cost_blocked.discard(key)
            if key in self._shadow:
                continue  # signal episode already running
            stats["signals"] += 1
            if intent.context is None:
                intent = replace(intent, context=_numeric(snaps[strat.features].to_dict()))
            self._shadow[key] = _VirtualTrade(intent, self.now)
            self._try_paper_entry(intent, f)

    def _try_paper_entry(self, intent: EntryIntent, f: FeatureSnapshot) -> None:
        st = self.symbols[intent.symbol]
        q = st.quote
        assert q is not None
        self.counters["signals"] += 1
        if intent.symbol in self._positions or any(
            p.symbol == intent.symbol for p in self._pending.values()
        ):
            return  # one paper position per symbol; the shadow book still records the signal
        base = Decision(
            self.now, intent.symbol, intent.strategy_id, "BUY", "entry", "", detail=intent.reason
        )
        if self.paused:
            self._log(replace(base, action="PAUSED", reasons=("engine paused",)))
            return
        throttle = self._throttle_reason(intent.symbol)
        if throttle:
            self.counters["throttled"] += 1
            self._log(replace(base, action="THROTTLED", reasons=(throttle,)))
            return

        self._signal_seq += 1
        signal = Signal(
            signal_id=f"{int(self.now * 1000)}-{self._signal_seq}",
            strategy_id=intent.strategy_id,
            symbol=intent.symbol,
            side=OrderSide.BUY,
            entry_price=q.ask,
            stop_price=q.ask * (1 - intent.stop_pct),
            created_at=_dt(self.now),
            target_price=q.ask * (1 + intent.target_pct),
        )
        decision = self.risk.evaluate(
            self._portfolio(),
            signal,
            self._market_state(intent.symbol, f),
            self.evidence.evidence(intent.strategy_id),
            kill_switch=self.kill_switch,
        )
        self._log_risk(base, decision)
        if not decision.approved:
            self.counters["rejected"] += 1
            return
        self.counters["approved"] += 1
        self._submit(
            OrderRequest(intent.symbol, OrderSide.BUY, decision.quantity, signal.idempotency_key),
            intent.strategy_id,
            intent,
        )
        st.last_entry_ts = self.now

    def _throttle_reason(self, symbol: str) -> str:
        while self._order_times and self._order_times[0] <= self.now - 60.0:
            self._order_times.popleft()
        if len(self._order_times) >= self.cfg.max_orders_per_minute:
            return f"order rate limit {self.cfg.max_orders_per_minute}/min"
        since = self.now - self.symbols[symbol].last_entry_ts
        if since < self.cfg.entry_cooldown_seconds:
            return f"cooldown {since:.0f}s < {self.cfg.entry_cooldown_seconds:.0f}s"
        return ""

    # ------------------------------------------------------------------ risk inputs
    def _portfolio(self) -> Portfolio:
        positions = {
            p.symbol: Position(p.symbol, p.quantity, p.avg_price, p.market_price)
            for p in self.broker.get_positions()
        }
        bal = self.broker.get_balance()
        return Portfolio(
            cash=bal.cash,
            positions=positions,
            equity_peak=self.equity_peak,
            day_start_equity=self.day_start_equity,
            consecutive_losses=self.consecutive_losses,
            pending_order_keys=frozenset(self._pending),
            reconciled=self.reconciled,
        )

    @property
    def reconciled(self) -> bool:
        """The engine's position book must match the exchange, symbol by symbol."""
        broker = {p.symbol: p.quantity for p in self.broker.get_positions()}
        local = {s: p.quantity for s, p in self._positions.items()}
        if broker.keys() != local.keys():
            return False
        return all(abs(broker[s] - local[s]) <= 1e-9 * max(1.0, local[s]) for s in local)

    def _market_state(self, symbol: str, f: FeatureSnapshot | None) -> MarketState:
        st = self.symbols[symbol]
        q = st.quote
        assert q is not None
        adv = st.adv
        if adv is None:
            adv = (f.volume_per_second if f else 0.0) * 86_400.0
        return MarketState(
            symbol=symbol,
            last_data_at=_dt(q.ts),
            now=_dt(self.now),
            bid=q.bid,
            ask=q.ask,
            avg_daily_volume=adv,
            expected_slippage_pct=self.cfg.expected_slippage_pct,
            market_open=self.session.is_open(self.now),
            api_healthy=self.feed_healthy and self.broker.health().ok,
            quantity_step=st.quantity_step,
        )

    # ------------------------------------------------------------------ orders & fills
    def _submit(
        self, req: OrderRequest, strategy_id: str, intent: EntryIntent | None, reason: str = ""
    ) -> bool:
        try:
            order = self.broker.place_order(req)
        except BrokerError as exc:
            self._log(
                Decision(
                    self.now,
                    req.symbol,
                    strategy_id,
                    str(req.side),
                    "order",
                    "BROKER_ERROR",
                    reasons=(str(exc),),
                )
            )
            return False
        self._order_times.append(self.now)
        if self.store is not None:
            self.store.log_order(self.cfg.run_id, order, self.now)
        if order.status is OrderStatus.REJECTED:
            self._log(
                Decision(
                    self.now,
                    req.symbol,
                    strategy_id,
                    str(req.side),
                    "order",
                    "BROKER_REJECT",
                    req.quantity,
                    reasons=("rejected by exchange",),
                )
            )
            return False
        self._pending[req.client_order_id] = _PendingOrder(
            order.order_id, req.symbol, req.side, strategy_id, intent, reason
        )
        return True

    def _sweep_pending(self) -> None:
        """Drop pending orders the exchange rejected or cancelled at execution time."""
        for cid, meta in list(self._pending.items()):
            order = self.broker.get_order(meta.order_id)
            if order is not None and order.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
                del self._pending[cid]
                if meta.side is OrderSide.SELL and meta.symbol in self._positions:
                    self._positions[meta.symbol].exit_client_id = None
                self._log(
                    Decision(
                        self.now,
                        meta.symbol,
                        meta.strategy_id,
                        str(meta.side),
                        "order",
                        "BROKER_REJECT",
                        reasons=(str(order.status),),
                    )
                )

    def _on_fill(self, fill: Fill) -> None:
        meta = self._pending.pop(fill.client_order_id, None)
        self.counters["fills"] += 1
        if self.store is not None:
            self.store.log_fill(self.cfg.run_id, fill)
        if meta is None:
            return
        if fill.side is OrderSide.BUY:
            assert meta.intent is not None
            self._positions[fill.symbol] = _PaperPosition(
                strategy_id=meta.strategy_id,
                intent=meta.intent,
                quantity=fill.quantity,
                entry_price=fill.price,
                entry_ts=fill.ts,
                entry_fee=fill.fee,
                stop=fill.price * (1 - meta.intent.stop_pct),
                target=fill.price * (1 + meta.intent.target_pct),
            )
            return
        pos = self._positions.pop(fill.symbol, None)
        if pos is None:
            return
        fees = pos.entry_fee + fill.fee
        pnl = fill.quantity * (fill.price - pos.entry_price) - fees
        rt = RoundTrip(
            book="paper",
            strategy_id=pos.strategy_id,
            symbol=fill.symbol,
            entry_ts=pos.entry_ts,
            exit_ts=fill.ts,
            entry_price=pos.entry_price,
            exit_price=fill.price,
            quantity=fill.quantity,
            pnl=pnl,
            fees=fees,
            net_return=pnl / (pos.quantity * pos.entry_price),
            exit_reason=pos.exit_reason or meta.reason,
        )
        self.consecutive_losses = self.consecutive_losses + 1 if pnl <= 0 else 0
        self.counters["paper_trades"] += 1
        self.realized_pnl += pnl
        self._record_trip(rt)

    def _request_exit(self, symbol: str, reason: str, force: bool = False) -> None:
        pos = self._positions.get(symbol)
        if pos is None or pos.exit_client_id is not None:
            return
        if not force and self.now - pos.last_exit_attempt < self.cfg.bar_seconds:
            return  # a rejected exit is retried at most once per bar
        pos.last_exit_attempt = self.now
        q = self.symbols[symbol].quote
        assert q is not None
        self._signal_seq += 1
        signal = Signal(
            signal_id=f"{int(self.now * 1000)}-{self._signal_seq}",
            strategy_id=pos.strategy_id,
            symbol=symbol,
            side=OrderSide.SELL,
            entry_price=q.bid,
            stop_price=q.bid,
            created_at=_dt(self.now),
        )
        decision = self.risk.evaluate(
            self._portfolio(),
            signal,
            self._market_state(symbol, self.symbols[symbol].features.last),
            None,
            kill_switch=self.kill_switch,
        )
        base = Decision(self.now, symbol, pos.strategy_id, "SELL", "exit", "", detail=reason)
        self._log_risk(base, decision)
        if not decision.approved:
            return
        req = OrderRequest(symbol, OrderSide.SELL, pos.quantity, signal.idempotency_key)
        if self._submit(req, pos.strategy_id, None, reason):
            pos.exit_client_id = req.client_order_id
            pos.exit_reason = reason

    # ------------------------------------------------------------------ quote watchers
    def _watch_quote(self, q: Quote) -> None:
        for vt in self._shadow.values():
            if vt.intent.symbol != q.symbol:
                continue
            if not vt.is_open and q.ts >= vt.submitted_at + self.cfg.latency_s:
                vt.entry_price, vt.entry_ts = q.ask, q.ts
                vt.stop = q.ask * (1 - vt.intent.stop_pct)
                vt.target = q.ask * (1 + vt.intent.target_pct)
            elif vt.is_open and vt.exit_submitted_at is None:
                if q.bid <= vt.stop:
                    self._shadow_exit(vt, "stop")
                elif q.bid >= vt.target:
                    self._shadow_exit(vt, "target")
        for key, vt in list(self._shadow.items()):
            if (
                vt.intent.symbol == q.symbol
                and vt.exit_submitted_at is not None
                and q.ts >= vt.exit_submitted_at + self.cfg.latency_s
            ):
                del self._shadow[key]
                self._close_shadow(vt, q)

        pos = self._positions.get(q.symbol)
        if pos is not None and pos.exit_client_id is None:
            if q.bid <= pos.stop:
                self._request_exit(q.symbol, "stop")
            elif q.bid >= pos.target:
                self._request_exit(q.symbol, "target")

    def _shadow_exit(self, vt: _VirtualTrade, reason: str) -> None:
        vt.exit_submitted_at = self.now
        vt.exit_reason = reason

    def _close_shadow(self, vt: _VirtualTrade, q: Quote) -> None:
        fee = self.cfg.fee_pct
        net = (q.bid * (1 - fee)) / (vt.entry_price * (1 + fee)) - 1.0
        rt = RoundTrip(
            book="shadow",
            strategy_id=vt.intent.strategy_id,
            symbol=vt.intent.symbol,
            entry_ts=vt.entry_ts,
            exit_ts=q.ts,
            entry_price=vt.entry_price,
            exit_price=q.bid,
            quantity=0.0,
            pnl=0.0,
            fees=2 * fee,
            net_return=net,
            exit_reason=vt.exit_reason,
            context=dict(vt.intent.context) if vt.intent.context else None,
        )
        self.evidence.record(rt.strategy_id, net)
        self._record_trip(rt)

    # ------------------------------------------------------------------ bookkeeping
    @property
    def equity(self) -> float:
        return self.broker.get_balance().equity

    @property
    def buy_hold_equity(self) -> float:
        """Benchmark: the initial cash split equally across the symbols at their first price."""
        ratios = [
            q.mid / self._bh_first[s]
            for s, st in self.symbols.items()
            if (q := st.quote) is not None and s in self._bh_first
        ]
        return self.cfg.initial_cash * (sum(ratios) / len(ratios) if ratios else 1.0)

    def _maybe_log_equity(self) -> None:
        eq = self.equity
        self.equity_peak = max(self.equity_peak, eq)
        if self.now - self._last_equity_log < self.cfg.equity_every_seconds:
            return
        self._last_equity_log = self.now
        self.equity_history.append((self.now, eq, self.buy_hold_equity))
        if self.store is not None:
            bal = self.broker.get_balance()
            self.store.log_equity(
                self.cfg.run_id, self.now, eq, bal.cash, eq - bal.cash, self.buy_hold_equity
            )

    def _record_trip(self, rt: RoundTrip) -> None:
        (self.paper_log if rt.book == "paper" else self.shadow_log).appendleft(rt)
        if self.store is not None:
            self.store.log_round_trip(self.cfg.run_id, rt)

    def _log_risk(self, base: Decision, d: RiskDecision) -> None:
        self._log(
            replace(
                base,
                action=str(d.action),
                quantity=d.quantity,
                notional=d.notional,
                reasons=tuple(d.reasons),
                checks=tuple((c.name, c.passed, c.detail) for c in d.checks),
            )
        )

    def _log(self, d: Decision) -> None:
        self.decisions.appendleft(d)
        if self.store is not None:
            self.store.log_decision(self.cfg.run_id, d)

    # ------------------------------------------------------------------ views
    def paper_trades(self) -> list[RoundTrip]:
        return list(self.paper_log)

    def snapshot(self, bars: int = 240) -> dict[str, Any]:
        bal = self.broker.get_balance()
        symbols: dict[str, Any] = {}
        for sym, st in self.symbols.items():
            q = st.quote
            f = st.features.last
            pos = self._positions.get(sym)
            symbols[sym] = {
                "bid": q.bid if q else None,
                "ask": q.ask if q else None,
                "spread_pct": q.spread_pct if q else None,
                "quote_age_s": self.now - q.ts if q else None,
                "features": f.to_dict() if f else None,
                "warmup": {"seen": st.features.bars_seen, "needed": st.warmup_needed},
                "bars": [
                    {
                        "t": b.start,
                        "o": b.open,
                        "h": b.high,
                        "l": b.low,
                        "c": b.close,
                        "v": b.volume,
                        "sv": b.signed_volume,
                    }
                    for b in list(st.bars)[-bars:]
                ],
                "position": None
                if pos is None
                else {
                    "strategy_id": pos.strategy_id,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "entry_ts": pos.entry_ts,
                    "stop": pos.stop,
                    "target": pos.target,
                    "unrealized": pos.quantity
                    * ((q.bid if q else pos.entry_price) - pos.entry_price)
                    - pos.entry_fee,
                    "exiting": pos.exit_client_id is not None,
                },
            }
        return {
            "now": self.now,
            "run_id": self.cfg.run_id,
            "mode": "PAPER",
            "venue": self.broker.name,
            "currency": self.cfg.currency,
            "session": self.cfg.session,
            "market_open": self.session.is_open(self.now) if self.now else None,
            "seconds_to_close": _finite(self.session.seconds_to_close(self.now)),
            "bar_seconds": self.cfg.bar_seconds,
            "paper_trades": self.counters["paper_trades"],
            "events": self.events,
            "feed_healthy": self.feed_healthy,
            "kill_switch": self.kill_switch,
            "paused": self.paused,
            "aggressiveness": self.profile.aggressiveness,
            "profile": self.profile.to_dict(),
            "account": {
                "cash": bal.cash,
                "equity": bal.equity,
                "initial": self.cfg.initial_cash,
                "day_start_equity": self.day_start_equity,
                "equity_peak": self.equity_peak,
                "buy_hold_equity": self.buy_hold_equity,
                "fees_paid": self.broker.total_fees,
                "realized_pnl": self.realized_pnl,
                "consecutive_losses": self.consecutive_losses,
                "reconciled": self.reconciled,
            },
            "costs": {
                "fee_pct": self.cfg.fee_pct,
                "round_trip_fees_pct": self.cfg.fees_round_trip_pct,
                "slippage_pct": self.cfg.expected_slippage_pct,
                "latency_s": self.cfg.latency_s,
            },
            "counters": dict(self.counters),
            "symbols": symbols,
            "strategies": [
                {
                    **row.to_dict(),
                    **self.strategy_stats[s.strategy_id],
                    "shadow_cum_return": self.evidence.cumulative_return(s.strategy_id),
                    "description": s.description,
                    "open_shadow": sum(1 for k in self._shadow if k[0] == s.strategy_id),
                    "eligible": row.edge_score >= self.profile.min_edge_score
                    and row.confidence >= self.profile.min_confidence,
                }
                for s in self.strategies
                for row in [self.evidence.table()[s.strategy_id]]
            ],
            "decisions": [d.to_dict() for d in list(self.decisions)[:50]],
            "trades": [
                t.to_dict() for t in [*list(self.paper_log)[:100], *list(self.shadow_log)[:50]]
            ],
            "equity": [
                {"t": t, "v": v, "bh": bh} for t, v, bh in list(self.equity_history)[-2000:]
            ],
        }
