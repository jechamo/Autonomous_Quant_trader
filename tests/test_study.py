from typing import Any

import aqt.research.study as study_mod
import numpy as np
import pytest
from aqt.data import generate_ohlcv
from aqt.research import StudyConfig, render_study_markdown, run_study, write_study_report
from aqt.research.pipeline import ResearchReport


def test_study_on_synthetic_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = {
        "SPY": generate_ohlcv(1200, seed=1),
        "SAN.MC": generate_ohlcv(1200, seed=2),
        "SHORT": generate_ohlcv(100, seed=3),
    }
    rep = run_study(data, ["breakout", "momentum"], StudyConfig(monte_carlo_sims=100))
    d = rep.to_dict()
    assert d["meta"]["n_pairs"] == 6 and d["meta"]["n_errors"] == 2
    per_pair = [len(p.report["multiple_testing"]["p_values"]) for p in rep.pairs if p.report]
    assert d["meta"]["n_hypotheses"] == sum(per_pair)
    assert {p.decision for p in rep.pairs} <= {"REJECTED", "ERROR"}
    assert next(p for p in rep.pairs if p.symbol == "SHORT").decision == "ERROR"
    assert "Study report" in render_study_markdown(rep)
    jp, mp = write_study_report(rep, tmp_path)
    assert jp.exists() and mp.exists()


def _fake_report(p_values: list[float], selected: int, verdict: str) -> dict[str, Any]:
    return {
        "meta": {"data_hash": "h"},
        "selected_strategy": {"name": "x"},
        "multiple_testing": {"p_values": p_values, "selected_index": selected},
        "verdict": {"decision": verdict, "failed": []},
        "out_of_sample": {"n_trades": 50, "expected_value": 0.01, "p_value": 0.001},
        "cost_analysis": {"net_ev": 0.01},
        "walk_forward": {"oos_ev": 0.01},
        "edge": {"score": 50.0},
    }


def test_global_fdr_decides_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Locally 'good' pairs are demoted unless they survive the study-wide FDR."""
    reports = {
        ("SAN.MC", "a"): _fake_report([1e-6, 0.5], 0, "CHALLENGER_CANDIDATE"),
        ("SPY", "a"): _fake_report([1e-6, 0.5], 0, "CHALLENGER_CANDIDATE"),
        ("AAPL", "a"): _fake_report([0.04, 0.9], 0, "CHALLENGER_CANDIDATE"),
        ("IBE.MC", "a"): _fake_report([1e-6, 0.5], 0, "REJECTED"),
    }

    class Fake:
        def __init__(self, d: dict[str, Any]) -> None:
            self.d = d

        def to_dict(self) -> dict[str, Any]:
            return self.d

    def fake_run(df: Any, cfg: Any) -> ResearchReport:
        return Fake(reports[(cfg.symbol, cfg.strategy)])  # type: ignore[return-value]

    monkeypatch.setattr(study_mod, "run_research", fake_run)
    data = {s: generate_ohlcv(700, seed=1) for s in ("SAN.MC", "SPY", "AAPL", "IBE.MC")}
    rep = run_study(data, ["a"], StudyConfig())
    by = {p.symbol: p for p in rep.pairs}
    assert rep.n_hypotheses == 8
    assert by["SAN.MC"].decision == "CHALLENGER_CANDIDATE"  # survives, tradable
    assert by["SPY"].decision == "EVIDENCE_ONLY"  # survives but US ETF proxy
    assert by["AAPL"].decision == "REJECTED"  # p=0.04 alone, but not after global FDR
    assert not by["AAPL"].survives_global_fdr
    assert by["IBE.MC"].decision == "REJECTED"  # local checks failed
    assert by["SAN.MC"].global_adjusted_p == pytest.approx(1e-6 * 8 / 3)
    assert [p.symbol for p in rep.candidates] == ["SAN.MC"]
    assert rep.ranking()[0]["symbol"] == "SAN.MC"
    assert np.isfinite(rep.to_dict()["ranking"][0]["edge_score"])
