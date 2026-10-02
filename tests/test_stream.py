from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from aqt.brokers.base import BrokerError, OrderRequest
from aqt.brokers.paper import PaperExchange
from aqt.common.types import OrderSide, OrderStatus, OrderType
from aqt.stream.bars import BarAggregator
from aqt.stream.binance import parse_message, parse_symbol_info, quote_currency
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Quote, TradeTick
from aqt.stream.evidence import EvidenceTracker
from aqt.stream.features import FeatureParams, FeatureSnapshot, IncrementalFeatures
from aqt.stream.records import Decision
from aqt.stream.store import SQLiteStore
from aqt.stream.strategies import (
    EntryIntent,
    MicroMomentum,
    MicroReversion,
    StreamStrategy,
    default_stream_strategies,
)
from aqt.stream.synthetic import synthetic_ticks

SYM = "BTCEUR"
SMALL = FeatureParams(
    fast_span=2, slow_span=3, vol_span=3, zscore_window=3, flow_window=2,
    momentum_bars=1, breakout_bars=2, volume_window=10,
)  # fmt: skip


def q(ts: float, mid: float, spread: float = 0.0002, qty: float = 1.0, sym: str = SYM) -> Quote:
    half = mid * spread / 2
    return Quote(sym, ts, mid - half, qty, mid + half, qty)


@dataclass
class Always(StreamStrategy):
    """Test strategy: enters on every ready bar with a fixed stop/target."""

    strategy_id: str = "always"
    stop_pct: float = 0.01
    target_pct: float = 0.002
    hold: int = 1000
    exit_flag: bool = False
    min_cost_multiple: float = 0.0  # tests drive exits by hand; the cost gate has its own test

    def entry(self, f: FeatureSnapshot) -> EntryIntent | None:
        if not f.ready:
            return None
        return EntryIntent(
            self.strategy_id, f.symbol, f.ts, self.stop_pct, self.target_pct, self.hold, "t"
        )

    def should_exit(self, f: FeatureSnapshot) -> bool:
        return self.exit_flag


def make_engine(
    store: SQLiteStore | None = None, strat: StreamStrategy | None = None, **kw: object
) -> StreamingEngine:
    params: dict[str, object] = {
        "symbols": (SYM,), "bar_seconds": 1.0, "feature_params": SMALL, "latency_s": 0.0,
        "entry_cooldown_seconds": 0.0, **kw,
    }  # fmt: skip
    cfg = EngineConfig(**params)  # type: ignore[arg-type]
    eng = StreamingEngine(cfg, strategies=[strat or Always()], store=store)
    eng.set_adv(SYM, 1_000_000.0)
    return eng


def seed_evidence(eng: StreamingEngine, sid: str = "always") -> None:
    for i in range(60):
        eng.evidence.record(sid, 0.01 if i % 10 else -0.002)


def warm(eng: StreamingEngine, start: float = 0.0, n: int = 6) -> float:
    """Feed alternating mids so volatility is non-zero; returns the next timestamp."""
    ts = start
    for i in range(n):
        eng.on_event(q(ts + 0.5, 100.0 + (0.02 if i % 2 else 0.0)))
        ts += 1.0
    return ts


# ---------------------------------------------------------------- bars


def test_bars_emit_only_after_interval_end() -> None:
    agg = BarAggregator(SYM, 5.0)
    assert agg.on_quote(q(100.2, 10.0)) == []
    assert agg.on_trade(TradeTick(SYM, 101.0, 10.0, 2.0, False)) == []
    assert agg.on_trade(TradeTick(SYM, 102.0, 10.0, 0.5, True)) == []
    assert agg.on_quote(q(103.0, 11.0)) == []
    bars = agg.on_quote(q(105.0, 9.0))  # first event of the next bar closes the previous one
    assert len(bars) == 1
    b = bars[0]
    assert (b.start, b.open, b.high, b.close) == (100.0, 10.0, 11.0, 11.0)
    assert b.buy_volume == 2.0 and b.sell_volume == 0.5 and b.signed_volume == 1.5
    assert b.n_trades == 2 and b.end == 105.0


def test_bars_fill_quiet_intervals_and_skip_outages() -> None:
    agg = BarAggregator(SYM, 1.0, max_gap_bars=5)
    agg.on_quote(q(0.1, 10.0))
    bars = agg.advance(3.5)
    assert [b.start for b in bars] == [0.0, 1.0, 2.0]
    assert all(b.close == 10.0 for b in bars)
    bars = agg.on_quote(q(100.2, 12.0))  # 96 s outage: one bar, clock restarts
    assert len(bars) == 1 and agg.gaps == 1
    assert agg.on_quote(q(101.1, 12.0))[0].start == 100.0


def test_bars_ignore_other_symbols_and_bad_quotes() -> None:
    agg = BarAggregator(SYM, 1.0)
    assert agg.on_trade(TradeTick(SYM, 0.0, 1.0, 1.0, False)) == []  # before first quote
    assert agg.on_quote(Quote(SYM, 0.0, 2.0, 1.0, 1.0, 1.0)) == []  # crossed book
    assert agg.on_quote(q(0.0, 1.0, sym="ETHEUR")) == []
    with pytest.raises(ValueError):
        BarAggregator(SYM, 0)


# ---------------------------------------------------------------- features


def test_features_are_causal_and_sane() -> None:
    events = synthetic_ticks(seconds=600, seed=3)
    agg = BarAggregator(SYM, 5.0)
    bars = [
        b for e in events for b in (agg.on_quote(e) if isinstance(e, Quote) else agg.on_trade(e))
    ]
    full = IncrementalFeatures(SYM)
    snaps = [full.update(b) for b in bars]
    k = len(bars) // 2
    partial = IncrementalFeatures(SYM)
    for b in bars[: k + 1]:
        last = partial.update(b)
    assert last == snaps[k]  # the future never changes the past
    s = snaps[-1]
    assert s.ready and s.sigma > 0
    assert -1 <= s.order_flow_imbalance <= 1 and -1 <= s.book_imbalance <= 1
    assert s.ts == bars[-1].end


def test_breakout_uses_previous_highs_only() -> None:
    f = IncrementalFeatures(SYM, SMALL)
    agg = BarAggregator(SYM, 1.0)
    snaps = []
    for i, mid in enumerate([100, 101, 100.5, 102, 102, 102]):
        for b in agg.on_quote(q(i + 0.5, mid)):
            snaps.append(f.update(b))
    # 100.5 < max(100, 101); 102 > max(101, 100.5); a flat 102 is not above its own prior high.
    assert [s.breakout for s in snaps] == [False, False, False, True, False]


# ---------------------------------------------------------------- strategies


def _snap(**kw: object) -> FeatureSnapshot:
    base = dict(
        symbol=SYM, ts=1.0, close=100.0, ema_fast=101.0, ema_slow=100.0, sigma=0.002,
        momentum=0.001, zscore=0.0, rolling_mean=100.0, order_flow_imbalance=0.5,
        book_imbalance=0.1, prior_high=99.0, breakout=True, spread_pct=0.0001,
        volume_per_second=1.0, bars_seen=100, ready=True,
    )  # fmt: skip
    base.update(kw)
    return FeatureSnapshot(**base)  # type: ignore[arg-type]


def test_momentum_entry_and_cost_gate() -> None:
    m = MicroMomentum(horizon_bars=16)
    intent = m.entry(_snap())
    assert intent is not None
    assert intent.target_pct == pytest.approx(2.5 * 0.002 * 4)
    assert intent.stop_pct == pytest.approx(1.5 * 0.002 * 4)
    assert m.clears_costs(intent, 0.002)
    assert not m.clears_costs(intent, 0.02)  # target < 2 × round-trip cost
    assert m.entry(_snap(order_flow_imbalance=0.1)) is None
    assert m.entry(_snap(breakout=False)) is None
    assert m.entry(_snap(ready=False)) is None
    assert m.should_exit(_snap(ema_fast=99.0, order_flow_imbalance=-0.1))


def test_reversion_targets_the_mean() -> None:
    r = MicroReversion(z_entry=2.0)
    s = _snap(zscore=-2.5, close=99.0, rolling_mean=100.0, order_flow_imbalance=0.0)
    intent = r.entry(s)
    assert intent is not None and intent.target_pct == pytest.approx(1 / 99)
    assert r.entry(replace(s, zscore=-1.0)) is None
    assert r.entry(replace(s, book_imbalance=-0.2)) is None
    small = r.entry(replace(s, rolling_mean=99.1))
    assert small is not None and not r.clears_costs(small, 0.002)  # move too small for costs
    assert r.should_exit(replace(s, zscore=0.1))
    catalog = default_stream_strategies(bar_seconds=5.0)
    assert len({x.strategy_id for x in catalog}) == 5
    assert [getattr(x, "horizon_bars", 0) for x in catalog] == [12, 60, 240, 24, 120]


# ---------------------------------------------------------------- paper exchange


def test_paper_fills_after_latency_at_the_far_side_with_fees() -> None:
    ex = PaperExchange(cash=1000, fee_pct=0.001, latency_s=0.5, min_notional=5)
    ex.on_quote(q(0.0, 100.0))
    o = ex.place_order(OrderRequest(SYM, OrderSide.BUY, 2.0, "c1"))
    assert o.status is OrderStatus.NEW
    assert ex.on_quote(q(0.3, 100.0)) == []  # latency not elapsed
    fills = ex.on_quote(q(0.6, 101.0, qty=5.0))  # order fits in the top of book
    assert len(fills) == 1
    f = fills[0]
    assert f.price == pytest.approx(101.0 * 1.0001) and f.fee == pytest.approx(f.notional * 0.001)
    assert ex.cash == pytest.approx(1000 - f.notional - f.fee)
    assert ex.get_order(o.order_id).status is OrderStatus.FILLED  # type: ignore[union-attr]
    assert ex.place_order(OrderRequest(SYM, OrderSide.BUY, 2.0, "c1")).order_id == o.order_id
    s = ex.place_order(OrderRequest(SYM, OrderSide.SELL, 2.0, "c2"))
    (sf,) = ex.on_quote(q(1.5, 102.0, qty=5.0))
    assert sf.price == pytest.approx(102.0 * 0.9999) and ex.get_positions() == []
    assert ex.total_fees == pytest.approx(f.fee + sf.fee)
    assert s.status is OrderStatus.NEW


def test_paper_impact_beyond_top_of_book() -> None:
    ex = PaperExchange(cash=10_000, fee_pct=0.0, latency_s=0.0, impact_pct=0.01, min_notional=0)
    ex.on_quote(q(0.0, 100.0, spread=0.0, qty=1.0))
    ex.place_order(OrderRequest(SYM, OrderSide.BUY, 2.0, "c"))
    (f,) = ex.on_quote(q(1.0, 100.0, spread=0.0, qty=1.0))
    assert f.price == pytest.approx(100.5)


def test_paper_rejections_and_guards() -> None:
    ex = PaperExchange(cash=50, latency_s=0.0, min_notional=5)
    with pytest.raises(BrokerError):
        ex.place_order(OrderRequest(SYM, OrderSide.BUY, 1.0, "x"))  # no book yet
    ex.on_quote(q(0.0, 100.0))
    assert (
        ex.place_order(OrderRequest(SYM, OrderSide.SELL, 1.0, "s")).status is OrderStatus.REJECTED
    )
    assert (
        ex.place_order(OrderRequest(SYM, OrderSide.BUY, 0.01, "tiny")).status
        is OrderStatus.REJECTED
    )
    big = ex.place_order(OrderRequest(SYM, OrderSide.BUY, 1.0, "big"))  # 100 > 50 cash
    assert ex.on_quote(q(1.0, 100.0)) == []
    assert ex.get_order(big.order_id).status is OrderStatus.REJECTED  # type: ignore[union-attr]
    with pytest.raises(BrokerError):
        ex.place_order(OrderRequest(SYM, OrderSide.BUY, 1.0, "l", OrderType.LIMIT, 1.0))
    with pytest.raises(BrokerError):
        ex.place_order(OrderRequest(SYM, OrderSide.BUY, 0.0, "z"))
    pending = PaperExchange(cash=500, latency_s=10.0)
    pending.on_quote(q(0.0, 100.0))
    o = pending.place_order(OrderRequest(SYM, OrderSide.BUY, 1.0, "p"))
    assert pending.pending_client_ids() == {"p"}
    assert pending.cancel_order(o.order_id).status is OrderStatus.CANCELLED
    with pytest.raises(BrokerError):
        pending.cancel_order(o.order_id)
    pending.healthy = False
    with pytest.raises(BrokerError):
        pending.place_order(OrderRequest(SYM, OrderSide.BUY, 1.0, "h"))
    assert not pending.health().ok
    with pytest.raises(ValueError):
        PaperExchange(cash=-1)


def test_liquidate_now_sells_everything_at_bid() -> None:
    ex = PaperExchange(cash=1000, fee_pct=0.0, latency_s=0.0)
    ex.on_quote(q(0.0, 100.0))
    ex.place_order(OrderRequest(SYM, OrderSide.BUY, 1.0, "b"))
    ex.on_quote(q(1.0, 100.0))
    assert ex.liquidate_now("ETHEUR", "x") is None
    f = ex.liquidate_now(SYM, "liq")
    assert f is not None and f.quantity == 1.0 and ex.get_positions() == []
    assert [i.symbol for i in ex.get_instruments()] == [SYM]


# ---------------------------------------------------------------- evidence


def test_evidence_requires_trades_and_controls_fdr() -> None:
    ev = EvidenceTracker(["good", "noise"], fees_round_trip_pct=0.002, min_trades=30)
    assert ev.evidence("good") is None
    for i in range(60):
        ev.record("good", 0.01 if i % 10 else -0.002)
        ev.record("noise", 0.004 if i % 2 else -0.004)
    t = ev.table()
    assert t["good"].confidence > 0.99 and t["good"].edge_score > 50
    assert t["noise"].edge_score == 0.0
    assert t["good"].adjusted_p_value >= t["good"].p_value
    e = ev.evidence("good")
    assert e is not None and e.expected_gross_edge == pytest.approx(
        t["good"].mean_net_return + 0.002
    )
    with pytest.raises(KeyError):
        ev.record("unknown", 0.0)


# ---------------------------------------------------------------- engine


def test_engine_without_evidence_trades_only_in_shadow() -> None:
    store = SQLiteStore()
    eng = make_engine(store)
    ts = warm(eng)
    eng.on_event(q(ts + 0.5, 100.5))  # target hit for the shadow trade
    eng.on_event(q(ts + 0.6, 100.5))
    assert eng.paper_trades() == []
    rejects = [d for d in eng.decisions if d.action == "REJECT"]
    assert rejects and any("evidence" in r for r in rejects[0].reasons)
    shadow = store.round_trips(eng.cfg.run_id, "shadow")
    assert shadow and shadow[0]["exit_reason"] == "target"
    assert eng.evidence.table()["always"].n_trades >= 1
    assert store.decisions(eng.cfg.run_id)[0]["action"] in {"REJECT", "THROTTLED"}


def test_cost_gate_blocks_moves_that_cannot_pay_fees() -> None:
    # 0.1 % target vs ~0.3 % round trip
    eng = make_engine(strat=Always(target_pct=0.001, min_cost_multiple=2.0))
    seed_evidence(eng)
    warm(eng, 0.0, 10)
    stats = eng.strategy_stats["always"]
    assert stats["cost_blocked"] == 1  # one continuous episode, counted once
    assert stats["signals"] == 0 and eng._shadow == {} and eng._positions == {}
    assert stats["last_target_pct"] == 0.001
    assert stats["last_min_target_pct"] == pytest.approx(2 * (0.002 + 0.0002 + 0.001), rel=0.01)
    snap = eng.snapshot()
    assert snap["counters"]["cost_blocked"] == 1 and snap["strategies"][0]["cost_blocked"] == 1


def test_engine_paper_round_trip_through_risk_engine() -> None:
    store = SQLiteStore()
    eng = make_engine(store)
    seed_evidence(eng)
    ts = warm(eng)
    pos = eng._positions.get(SYM)
    assert pos is not None, [d.to_dict() for d in eng.decisions]
    assert eng.reconciled
    approved = [d for d in eng.decisions if d.action in ("APPROVE", "ADJUST_SIZE")]
    assert approved and approved[0].notional <= 100 * eng.profile.max_position_pct + 1e-9
    assert pos.stop == pytest.approx(pos.entry_price * 0.99)
    eng.on_event(q(ts + 0.5, 101.0))  # target → exit order
    eng.on_event(q(ts + 0.7, 101.0))  # fill
    (rt,) = eng.paper_trades()
    assert rt.exit_reason == "target" and rt.pnl > 0
    assert eng.realized_pnl == pytest.approx(rt.pnl)
    assert eng.equity == pytest.approx(100 + rt.pnl)
    assert store.round_trips(eng.cfg.run_id, "paper")[0]["pnl"] == pytest.approx(rt.pnl)
    snap = eng.snapshot()
    assert snap["account"]["realized_pnl"] == pytest.approx(rt.pnl)
    assert snap["strategies"][0]["eligible"]
    store.flush()
    assert store.equity_curve(eng.cfg.run_id)


def test_engine_stop_loss_counts_consecutive_losses() -> None:
    eng = make_engine()
    seed_evidence(eng)
    ts = warm(eng)
    eng.on_event(q(ts + 0.5, 98.0))
    eng.on_event(q(ts + 0.6, 98.0))
    (rt,) = eng.paper_trades()
    assert rt.exit_reason == "stop" and rt.pnl < 0 and eng.consecutive_losses == 1


def test_kill_switch_pause_and_throttle_block_entries() -> None:
    eng = make_engine()
    seed_evidence(eng)
    eng.kill_switch = True
    warm(eng)
    assert eng._positions == {}
    assert any("kill_switch" in r for d in eng.decisions for r in d.reasons)

    eng2 = make_engine()
    seed_evidence(eng2)
    eng2.paused = True
    warm(eng2)
    assert eng2._positions == {} and eng2.decisions[0].action == "PAUSED"

    eng3 = make_engine(entry_cooldown_seconds=1000.0)
    seed_evidence(eng3)
    ts = warm(eng3)
    eng3.on_event(q(ts + 0.5, 101.0))
    eng3.on_event(q(ts + 0.6, 101.0))
    ts = warm(eng3, ts + 1, 4)
    assert len(eng3.paper_trades()) == 1
    assert any(d.action == "THROTTLED" for d in eng3.decisions)


def test_time_and_signal_exits_and_flatten() -> None:
    eng = make_engine(strat=Always(hold=2))
    seed_evidence(eng)
    ts = warm(eng)
    ts = warm(eng, ts, 4)
    assert any(t.exit_reason == "time" for t in eng.paper_trades())

    eng2 = make_engine(strat=Always(exit_flag=True))
    seed_evidence(eng2)
    ts = warm(eng2, 0.0, 8)
    assert any(t.exit_reason == "signal" for t in eng2.paper_trades())

    eng3 = make_engine()
    seed_evidence(eng3)
    ts = warm(eng3)
    assert SYM in eng3._positions
    eng3.flatten()
    eng3.on_event(q(ts + 0.5, 100.0))
    assert eng3.paused and eng3.paper_trades()[0].exit_reason == "manual_flatten"


def test_shutdown_closes_positions_and_evidence_persists(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.sqlite")
    eng = make_engine(store)
    seed_evidence(eng)
    ts = warm(eng)
    eng.on_event(q(ts + 0.5, 100.5))
    eng.on_event(q(ts + 0.6, 100.5))
    assert eng._positions or eng.paper_trades()
    eng.shutdown()
    assert eng._positions == {} and eng.reconciled
    store.flush()
    n_shadow = len(store.shadow_returns(eng.cfg.run_id))
    assert n_shadow >= 1
    again = make_engine(store)  # restart: forward evidence is not lost
    assert again.evidence.table()["always"].n_trades == n_shadow
    assert store.realized_pnl(eng.cfg.run_id) == pytest.approx(eng.realized_pnl)


def test_engine_on_synthetic_stream_is_deterministic() -> None:
    events = synthetic_ticks(seconds=1800, seed=5, vol_per_sqrt_s=0.0004)

    def run() -> dict[str, object]:
        cfg = EngineConfig(symbols=(SYM,), bar_seconds=2.0, run_id="replay")
        eng = StreamingEngine(cfg)
        for e in events:
            eng.on_event(e)
        eng.on_time(events[-1].ts + 10)
        eng.shutdown()
        snap = eng.snapshot()
        return {"counters": snap["counters"], "equity": snap["account"]["equity"],
                "strategies": snap["strategies"]}  # fmt: skip

    a, b = run(), run()
    assert a == b
    assert sum(s["n_trades"] for s in a["strategies"]) >= 0  # type: ignore[union-attr]


def test_engine_config_validation() -> None:
    with pytest.raises(ValueError):
        StreamingEngine(EngineConfig(symbols=()))
    with pytest.raises(ValueError):
        StreamingEngine(EngineConfig(symbols=(SYM,)), strategies=[Always(), Always()])
    eng = make_engine()
    with pytest.raises(ValueError):
        eng.set_quantity_step(SYM, 0)
    eng.on_event(q(0.0, 1.0, sym="DOGEEUR"))  # unknown symbols are ignored
    assert eng.events == 0


# ---------------------------------------------------------------- store & binance


def test_store_ticks_roundtrip_and_settings(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "t.sqlite")
    events = synthetic_ticks(seconds=20, seed=1)
    for e in events:
        store.record(e)
    back = list(store.iter_ticks([SYM]))
    assert back == events
    assert list(store.iter_ticks(start=events[-1].ts + 1)) == []
    assert {r["kind"] for r in store.tick_summary()} == {"Q", "T"}
    assert store.get_setting("k") is None
    store.set_setting("k", "1")
    store.set_setting("k", "2")
    assert store.get_setting("k") == "2"
    store.log_decision("r", Decision(1.0, SYM, "s", "BUY", "entry", "REJECT", reasons=("a",)))
    assert store.decisions("r")[0]["reasons"] == ["a"]
    store.close()


def test_parse_binance_messages() -> None:
    qmsg = {"stream": "btceur@bookTicker", "data": {"u": 1, "s": "BTCEUR", "b": "100.0",
            "B": "0.5", "a": "100.1", "A": "0.7"}}  # fmt: skip
    quote = parse_message(qmsg, 5.0)
    assert quote == Quote("BTCEUR", 5.0, 100.0, 0.5, 100.1, 0.7)
    tmsg = {"stream": "btceur@aggTrade", "data": {"e": "aggTrade", "s": "BTCEUR", "p": "100.05",
            "q": "0.01", "m": True}}  # fmt: skip
    trade = parse_message(tmsg, 6.0)
    assert trade == TradeTick("BTCEUR", 6.0, 100.05, 0.01, True) and trade.signed_qty == -0.01
    assert parse_message({"stream": "x@bookTicker", "data": {"s": "X"}}, 1.0) is None
    assert parse_message({"data": {"e": "kline"}}, 1.0) is None


def test_symbol_info_and_quote_currency() -> None:
    info = {"symbols": [{"symbol": "BTCEUR", "baseAsset": "BTC", "quoteAsset": "EUR", "filters": [
        {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
        {"filterType": "NOTIONAL", "minNotional": "5.0"}]}]}  # fmt: skip
    out = parse_symbol_info(info, [{"symbol": "BTCEUR", "volume": "104.6"}])
    assert out["BTCEUR"].step_size == 1e-5 and out["BTCEUR"].min_notional == 5.0
    assert out["BTCEUR"].volume_24h == 104.6
    assert quote_currency(["BTCEUR", "ETHEUR"]) == "EUR"
    assert quote_currency(["BTCUSDC"]) == "USDC"
    with pytest.raises(ValueError):
        quote_currency(["BTCEUR", "ETHUSDC"])
    with pytest.raises(ValueError):
        quote_currency(["WHAT"])


def test_rank_symbols_picks_liquid_non_stable_pairs() -> None:
    from aqt.stream.binance import rank_symbols, resolve_universe

    tickers = [
        {"symbol": "BTCUSDC", "quoteVolume": "900"},
        {"symbol": "USDTUSDC", "quoteVolume": "5000"},  # stable vs stable: excluded
        {"symbol": "ETHUSDC", "quoteVolume": "800"},
        {"symbol": "ETHBTC", "quoteVolume": "9999"},  # other quote asset
        {"symbol": "DOGEUSDC", "quoteVolume": "0"},
        {"symbol": "USDC", "quoteVolume": "1"},
    ]
    assert rank_symbols(tickers, "USDC", 5) == ["BTCUSDC", "ETHUSDC"]
    assert rank_symbols(tickers, "usdc", 1) == ["BTCUSDC"]
    assert resolve_universe("btcusdc, ethusdc,") == ["BTCUSDC", "ETHUSDC"]
