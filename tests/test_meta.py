from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from aqt.lab.learning import learn_meta_filters
from aqt.lab.live import rule_strategies, sync_engine_rules
from aqt.lab.meta import (
    MetaConfig,
    MetaFilteredStrategy,
    load_model,
    save_model,
    train_meta_filter,
    usable_features,
)
from aqt.lab.registry import RuleRegistry, RuleStatus
from aqt.stream.dsl_strategy import ResearchBarBook
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.records import RoundTrip
from aqt.stream.store import SQLiteStore
from aqt.stream.synthetic import synthetic_ticks

from tests.test_stream import Always, _snap


def planted(
    n: int = 300, seed: int = 0, signal: bool = True
) -> tuple[list[dict[str, float]], list[float]]:
    """Trades win when ``flow`` is high; ``close``/``ts`` are distractors the model must ignore."""
    rng = np.random.default_rng(seed)
    ctx, rets = [], []
    for i in range(n):
        flow = float(rng.uniform(-1, 1))
        noise = float(rng.normal(0, 1))
        win = (flow > 0.3) if signal else bool(rng.random() < 0.35)
        r = (0.006 if win else -0.004) + float(rng.normal(0, 0.001))
        ctx.append({"flow": flow, "noise": noise, "close": 100.0 + i, "ts": 1e9 + i})
        rets.append(r)
    return ctx, rets


def test_meta_filter_learns_a_real_pattern() -> None:
    ctx, rets = planted()
    res = train_meta_filter(ctx, rets)
    assert res.accepted, res.reason
    assert res.ev_all < 0 < res.ev_kept and 0 < res.kept_fraction < 0.6
    assert next(iter(res.importance)) == "flow"
    assert "close" not in res.features and "ts" not in res.features
    assert res.summary()["accepted"] is True


def test_meta_filter_refuses_noise_and_small_samples() -> None:
    ctx, rets = planted(signal=False, seed=3)
    res = train_meta_filter(ctx, rets)
    assert not res.accepted and res.reason
    small = train_meta_filter(ctx[:20], rets[:20])
    assert not small.accepted and "only 20" in small.reason
    same = train_meta_filter(ctx, [0.01] * len(ctx))
    assert not same.accepted and "same outcome" in same.reason
    assert usable_features([{"ema_200": 1.0, "sma_20": 1.0, "rsi": 30.0, "macd_hist": 0.1}]) == [
        "rsi"
    ]
    strict = train_meta_filter(*planted(), MetaConfig(min_kept=10_000))
    assert not strict.accepted and "too few" in strict.reason


def test_model_files_are_integrity_checked(tmp_path: Path) -> None:
    res = train_meta_filter(*planted())
    path, sha = save_model(res.model, tmp_path, "m")
    model = load_model(path, sha)
    assert model.predict_proba(np.zeros((1, len(res.features)))).shape == (1, 2)
    Path(path).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        load_model(path, sha)


def test_meta_filtered_strategy_only_lets_good_contexts_through() -> None:
    ctx, rets = planted()
    res = train_meta_filter(ctx, rets)

    class Ctx(Always):
        flow: float = 0.0

        def entry(self, f):  # type: ignore[no-untyped-def]
            intent = super().entry(f)
            return None if intent is None else intent.__class__(
                *[getattr(intent, k) for k in ("strategy_id", "symbol", "ts", "stop_pct",
                                               "target_pct", "max_hold_bars", "reason")],
                {"flow": self.flow, "noise": 0.0},
            )  # fmt: skip

    inner = Ctx()
    meta = MetaFilteredStrategy(inner, res.model, res.features, res.threshold)
    assert meta.strategy_id == "always~meta" and "filtro" in meta.description
    inner.flow = 0.9
    good = meta.entry(_snap())
    assert good is not None and good.strategy_id == "always~meta" and "meta p=" in good.reason
    inner.flow = -0.9
    assert meta.entry(_snap()) is None and meta.last_probability is not None
    assert meta.should_exit(_snap()) is False


def _log(store: SQLiteStore, sid: str, ctx: list[dict[str, float]], rets: list[float]) -> None:
    for i, (c, r) in enumerate(zip(ctx, rets, strict=True)):
        store.log_round_trip(
            "live-USDC", RoundTrip("shadow", sid, "XUSDC", i, i + 1, 1, 1, 0, 0, 0, r, "t", c)
        )


def test_learning_registers_filtered_versions_of_baseline_strategies(tmp_path: Path) -> None:
    store = SQLiteStore()
    reg = RuleRegistry(store)
    ctx, rets = planted()
    _log(store, "momentum_5m", ctx, rets)
    noise_ctx, noise_rets = planted(signal=False, seed=4)
    _log(store, "reversion_2z_2m", noise_ctx, noise_rets)
    ids = ["momentum_5m", "reversion_2z_2m", "momentum_1m"]
    out = learn_meta_filters(store, "live-USDC", reg, ids, model_dir=tmp_path)
    by = {x["strategy_id"]: x for x in out}
    assert by["momentum_5m"]["accepted"] and not by["reversion_2z_2m"]["accepted"]
    assert "momentum_1m" not in by  # no trades: nothing to learn from
    meta_rule = reg.get(by["momentum_5m"]["rule_id"])
    assert meta_rule is not None and meta_rule.status == RuleStatus.CHALLENGER and meta_rule.is_meta
    assert (
        meta_rule.symbol == "*" and meta_rule.spec is None and meta_rule.parent_id == "momentum_5m"
    )
    assert meta_rule.name == "momentum_5m + filtro ML" and meta_rule.to_dict()["family"] == "meta"
    lessons = [lesson["text"] for lesson in reg.lessons()]
    assert any("aprendió" in t for t in lessons) and any("no hay un patrón" in t for t in lessons)
    # Same data again: no re-mining (needs 50 % more trades) and no second child.
    assert learn_meta_filters(store, "live-USDC", reg, ids, model_dir=tmp_path) == []

    strategies = rule_strategies(reg.active(), ["BTCUSDC"], ResearchBarBook(), 5.0)
    assert len(strategies) == 1 and isinstance(strategies[0], MetaFilteredStrategy)
    assert strategies[0].inner.strategy_id == "momentum_5m"
    eng = StreamingEngine(EngineConfig(symbols=("BTCUSDC",), run_id="live-USDC"), store=store)
    sync_engine_rules(eng, reg, ResearchBarBook())
    assert meta_rule.rule_id in [s.strategy_id for s in eng.strategies]


def test_engine_stores_entry_context_with_shadow_trades() -> None:
    store = SQLiteStore()
    eng = StreamingEngine(EngineConfig(symbols=("BTCEUR",), bar_seconds=2.0), store=store)
    for e in synthetic_ticks(seconds=3 * 3600, seed=5, vol_per_sqrt_s=0.0006):
        eng.on_event(e)
    trades = [
        t for sid in eng.evidence.strategy_ids for t in store.strategy_trades(eng.cfg.run_id, sid)
    ]
    assert trades, "the baseline strategies should have produced shadow trades"
    ret, ctx = trades[0]
    assert isinstance(ret, float) and "sigma" in ctx and "order_flow_imbalance" in ctx
