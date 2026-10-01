from __future__ import annotations

import json
from itertools import pairwise

from aqt.analyst.hypotheses import HypothesisStore
from aqt.lab.meta import MetaConfig
from aqt.lab.progress import activity_feed, ai_progress, funnel, learning_progress, ml_progress
from aqt.lab.registry import RuleRecord, RuleRegistry, RuleStatus
from aqt.strategies.intraday import INTRADAY_CATALOG
from aqt.stream.dsl_strategy import rule_id_for
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.records import RoundTrip
from aqt.stream.store import SQLiteStore
from fastapi.testclient import TestClient

from services.trader.app import create_app
from services.trader.lab_scheduler import LabScheduler
from services.trader.runtime import TraderRuntime

RUN = "live-USDC"


def shadow(store: SQLiteStore, sid: str, n: int, ret: float = 0.002, ts0: float = 1e9) -> None:
    for i in range(n):
        store.log_round_trip(
            RUN,
            RoundTrip("shadow", sid, "AAA", ts0 + i, ts0 + i + 1, 100, 100, 1, ret, 0.0, ret,
                      "target", {"rsi": float(i)}),
        )  # fmt: skip


def lab_with_history() -> tuple[SQLiteStore, RuleRegistry, str]:
    store = SQLiteStore()
    reg = RuleRegistry(store, clock=lambda: 1e9)
    for n_hyp, disc, cand, golden in ((1000, 3, 2, [True, False]), (500, 0, 0, [])):
        run = reg.start_run({})
        summary = {"n_hypotheses": n_hyp, "n_global_discoveries": disc, "n_candidates": cand,
                   "golden": [{"passed": g} for g in golden]}  # fmt: skip
        reg.finish_run(run, summary)
    spec = INTRADAY_CATALOG["flow_momentum"][0].render()
    rid = rule_id_for(spec, "AAA")
    reg.upsert(RuleRecord(rid, "AAA", 60.0, spec))
    reg.set_status(rid, RuleStatus.CHALLENGER, "test")
    return store, reg, rid


def test_funnel_accumulates_every_cycle_and_rule_transitions() -> None:
    store, reg, rid = lab_with_history()
    f = funnel(store)
    assert f["cycles"] == 2
    assert [s["n"] for s in f["stages"]] == [1500, 3, 2, 1, 1, 0]
    reg.set_status(rid, RuleStatus.CHAMPION, "evidence")
    assert funnel(store)["stages"][-1]["n"] == 1


def test_ml_progress_counts_examples_against_what_the_trainer_needs() -> None:
    store, reg, _ = lab_with_history()
    cfg = MetaConfig(min_trades=60)
    shadow(store, "flow_a", 30)
    shadow(store, "flow_b", 70)
    shadow(store, "flow_c", 80)
    store.set_setting(f"meta_last_n:{RUN}:flow_c", "70")  # tried at 70, retries at 105
    spec = INTRADAY_CATALOG["flow_momentum"][0].render()
    reg.upsert(
        RuleRecord("flow_d~meta-abc123", "AAA", 60.0, spec, meta={"kind": "meta", "base": "flow_d"})
    )
    reg.set_status("flow_d~meta-abc123", RuleStatus.CHALLENGER, "learned")
    ml = ml_progress(store, reg, RUN, ["flow_a", "flow_b", "flow_c", "flow_d", "x~meta-1"], cfg)
    rows = {r["strategy_id"]: r for r in ml["strategies"]}
    assert set(rows) == {"flow_a", "flow_b", "flow_c", "flow_d"}
    assert rows["flow_a"]["progress"] == 0.5 and rows["flow_a"]["state"] == "reuniendo ejemplos"
    assert rows["flow_b"]["progress"] == 1.0 and rows["flow_b"]["state"] == "listo para entrenar"
    assert rows["flow_c"]["needed"] == 105 and rows["flow_c"]["attempted"]
    assert rows["flow_d"]["filter"] == "flow_d~meta-abc123" and ml["filters"] == 1


def test_ai_progress_and_activity_feed_newest_first() -> None:
    store, reg, rid = lab_with_history()
    assert ai_progress(store)["proposed"] == 0  # table created on demand
    hyps = HypothesisStore(store, clock=lambda: 1e9 + 50)
    hyps.add_invalid("bad", "unknown features", "m")
    shadow(store, rid, 2, ts0=1e9 + 100)
    reg.add_lesson("learning", "no reliable filter", rid, {})
    feed = activity_feed(store, RUN)
    kinds = {i["kind"] for i in feed}
    assert {"research", "rule", "ai", "trade_shadow", "ml"} <= kinds
    assert feed[0]["kind"] == "trade_shadow" and feed[0]["tone"] == "good"
    assert all(a["ts"] >= b["ts"] for a, b in pairwise(feed))
    assert len({i["id"] for i in feed}) == len(feed)  # stable ids drive the sparks
    assert ai_progress(store) == {"proposed": 0, "pending": 0, "tested": 0, "promoted": 0,
                                  "invalid": 1}  # fmt: skip


def test_rule_progress_and_learning_api() -> None:
    store, _, rid = lab_with_history()
    shadow(store, rid, 40, ret=0.004)
    eng = StreamingEngine(EngineConfig(symbols=("AAA",), run_id=RUN), store=store)
    out = learning_progress(store, RUN, [s.strategy_id for s in eng.strategies], {}, 10.0, 0.75)
    (rule,) = out["rules"]
    assert rule["rule_id"] == rid and rule["n_trades"] == 40 and 0 < rule["progress"] <= 1
    lab = LabScheduler(eng, store, None, None, every_s=0)  # type: ignore[arg-type]
    rt = TraderRuntime(eng, store, feed=None, clock=lambda: 1e9, lab=lab)
    with TestClient(create_app(rt)) as client:
        body = client.get("/api/learning").json()
    assert body["enabled"] and body["funnel"]["stages"][0]["n"] == 1500
    assert {"rules", "ml", "ai", "feed", "status"} <= set(body)
    json.dumps(body)
    plain = TraderRuntime(eng, store, feed=None, clock=lambda: 1e9)
    with TestClient(create_app(plain)) as client:
        assert client.get("/api/learning").json() == {"enabled": False}
