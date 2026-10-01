import json
from pathlib import Path

from aqt.data import generate_ohlcv
from aqt.research import ResearchConfig, render_markdown, run_research, write_report
from typer.testing import CliRunner

from services.research.cli import app


def test_pipeline_is_reproducible(tmp_path: Path) -> None:
    df = generate_ohlcv(1200, seed=5)
    cfg = ResearchConfig(symbol="TEST", timeframe="1d", strategy="breakout", monte_carlo_sims=200)
    a = run_research(df, cfg).to_dict()
    b = run_research(df, cfg).to_dict()
    a["meta"].pop("generated_at")
    b["meta"].pop("generated_at")
    assert a == b
    assert a["verdict"]["decision"] in {"CHALLENGER_CANDIDATE", "REJECTED"}
    assert a["multiple_testing"]["n_hypotheses"] >= 9
    assert a["cost_analysis"]["gross_ev"] > a["cost_analysis"]["net_ev"]


def test_random_walk_is_not_promoted() -> None:
    """On data with no exploitable structure the system must decide NO TRADE."""
    df = generate_ohlcv(1500, seed=99, annual_drift=0.0, regime_switch_prob=0.0)
    for strat in ("momentum", "mean_reversion"):
        rep = run_research(df, ResearchConfig("RW", "1d", strat, monte_carlo_sims=200)).to_dict()
        assert rep["verdict"]["decision"] == "REJECTED"


def test_report_files(tmp_path: Path) -> None:
    df = generate_ohlcv(900, seed=2)
    rep = run_research(df, ResearchConfig("X", "1d", "momentum", monte_carlo_sims=100))
    jp, mp = write_report(rep, tmp_path)
    data = json.loads(jp.read_text())
    assert data["selected_strategy"]["config_hash"] in jp.name
    assert "Verdict" in mp.read_text()
    assert "Edge Score" in render_markdown(rep)


def test_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app, ["run", "--strategy", "trend_following", "--bars", "900", "--out", str(tmp_path)]
    )
    assert res.exit_code == 0, res.output
    assert "Verdict" in res.output
    assert list(tmp_path.glob("*.md"))
    assert "momentum" in runner.invoke(app, ["list"]).output
    assert runner.invoke(app, ["run", "--strategy", "nope"]).exit_code != 0


def test_cli_fetch_and_study(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from aqt.data import SyntheticAdapter

    import services.research.cli as cli

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def persist_study(self, study, universe):  # type: ignore[no-untyped-def]
            self.calls.append(universe)
            return "exp-1"

    rec = Recorder()
    monkeypatch.setattr(cli, "_fetch_adapter", lambda: SyntheticAdapter(n=900))
    monkeypatch.setattr(cli, "_result_store", lambda persist: rec)
    runner = CliRunner()
    data_dir = tmp_path / "pq"
    res = runner.invoke(app, ["fetch", "--universe", "SAN.MC,AAPL", "--data-dir", str(data_dir)])
    assert res.exit_code == 0, res.output
    assert (data_dir / "1d" / "SAN.MC.parquet").exists()
    res = runner.invoke(
        app,
        [
            "study",
            "--universe",
            "SAN.MC,AAPL,MISSING",
            "--strategies",
            "breakout",
            "--data-dir",
            str(data_dir),
            "--mc-sims",
            "50",
            "--persist",
            "--out",
            str(tmp_path),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "Hypotheses" in res.output and "exp-1" in res.output
    assert rec.calls == [["SAN.MC", "AAPL", "MISSING"]]
    assert list(tmp_path.glob("study_*.md"))
    assert runner.invoke(app, ["study", "--strategies", "nope"]).exit_code != 0
