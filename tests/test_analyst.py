from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
from aqt.analyst.client import (
    DEFAULT_MODEL,
    AnalystConfig,
    AnalystError,
    OpenAIClient,
    analyst_config_from_env,
)
from aqt.analyst.hypotheses import (
    HypothesisStore,
    available_features,
    run_analyst,
    validate_proposal,
)
from aqt.lab.cycle import KlineData, LabConfig, run_research_cycle
from aqt.stream.store import SQLiteStore
from typer.testing import CliRunner

import services.trader.cli as cli_module
from tests.test_swing import T0, H, hourly

ROOT = Path(__file__).resolve().parents[1]
FEATURES = available_features()
CFG = AnalystConfig(api_key="sk-test-not-real", model="test-model")


def proposal(**over: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "name": "laggard_bounce",
        "timeframe": "1h",
        "claim": "Short-term losers in an up-trend revert.",
        "evidence": "xs_reversal failed only on sample size.",
        "suggested_experiment": "Positive OOS EV after costs on several symbols.",
        "entry": {
            "all_of": [
                {"left": "xs_rank_ret_5", "op": "<", "right": "$rank"},
                {"left": "close", "op": ">", "right": "ema_200"},
            ]
        },
        "exit": {"stop_atr_mult": "$stop", "max_holding_bars": 12},
        "params": {"rank": 0.2, "stop": 2.0},
        "grid": {"rank": [0.1, 0.2], "stop": [1.5, 2.5]},
    }
    raw.update(over)
    return raw


def openai_transport(content: Any, seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        assert request.url.path.endswith("/chat/completions")
        text = content if isinstance(content, str) else json.dumps(content)
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": text}}],
                "usage": {"total_tokens": 1234},
            },
        )

    return httpx.MockTransport(handler)


# --- validation ------------------------------------------------------------------------------


def test_valid_proposal_becomes_a_namespaced_dsl_rule() -> None:
    p = validate_proposal(proposal(), FEATURES, ("1h", "4h"))
    assert p.spec.name == "ai_laggard_bounce" and p.spec.family == "ai"
    assert p.timeframe == "1h" and p.grid == {"rank": [0.1, 0.2], "stop": [1.5, 2.5]}
    assert p.spec.render({"rank": 0.1, "stop": 1.5}).exit.max_holding_bars == 12


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"name": "Bad Name!"}, "invalid name"),
        ({"timeframe": "1min"}, "timeframe"),
        ({"params": {"rank": "high", "stop": 2.0}}, "numeric"),
        ({"grid": {"other": [1, 2]}}, "no default"),
        ({"grid": {"rank": [0.1, 0.2, 0.3], "stop": [1, 2, 3]}}, "combinations"),
        ({"grid": {"rank": []}}, "1-4 values"),
        ({"exit": {"stop_atr_mult": 2.0, "max_holding_bars": None}}, "max_holding_bars"),
        ({"exit": {"stop_atr_mult": None, "max_holding_bars": 5}}, "invalid rule"),
        (
            {"entry": {"all_of": [{"left": "insider_flow", "op": ">", "right": 0}]}, "params": {},
             "grid": {}, "exit": {"stop_atr_mult": 2.0, "max_holding_bars": 5}},
            "unknown features",
        ),
        ({"entry": {"all_of": [{"left": "rsi", "op": "~", "right": 30}]}}, "invalid rule"),
    ],
)  # fmt: skip
def test_invalid_proposals_are_rejected_with_a_reason(over: dict[str, Any], reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        validate_proposal(proposal(**over), FEATURES, ("1h",))


# --- client ----------------------------------------------------------------------------------


def test_config_from_env_and_key_never_in_repr() -> None:
    assert analyst_config_from_env({}) is None
    default = analyst_config_from_env({"OPENAI_API_KEY": "sk-x"})
    assert default is not None and default.model == DEFAULT_MODEL
    cfg = analyst_config_from_env(
        {"OPENAI_API_KEY": "sk-secret", "OPENAI_MODEL_CHEAP": "cheap", "OPENAI_MODEL_STRONG": ""}
    )
    assert cfg is not None and cfg.model == "cheap"
    assert "sk-secret" not in repr(cfg) and "sk-secret" not in repr(OpenAIClient(cfg))


def test_client_errors_are_reported() -> None:
    def fail(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    with pytest.raises(AnalystError, match="429"):
        OpenAIClient(CFG, httpx.MockTransport(fail)).complete_json("s", "u")
    with pytest.raises(AnalystError, match="unexpected"):
        OpenAIClient(CFG, openai_transport("not json")).complete_json("s", "u")
    with pytest.raises(AnalystError, match="JSON object"):
        OpenAIClient(CFG, openai_transport("[1, 2]")).complete_json("s", "u")


# --- run_analyst -----------------------------------------------------------------------------


def test_run_analyst_stores_valid_rejects_invalid_and_dedupes() -> None:
    store = SQLiteStore()
    seen: list[httpx.Request] = []
    content = {
        "hypotheses": [
            proposal(),
            proposal(
                name="uses_unknown",
                entry={"all_of": [{"left": "x", "op": ">", "right": 1}]},
                params={},
                grid={},
            ),
            proposal(name="laggard_bounce_copy"),  # same rule as the first → different name only
            "not an object",
        ]
    }
    client = OpenAIClient(CFG, openai_transport(content, seen))
    res = run_analyst(store, client, CFG, "binance", ("1h",), {"xs_reversal": "..."})
    assert [p.name for p in res.created] == ["ai_laggard_bounce"]
    assert {n for n, _ in res.rejected} == {"uses_unknown", "laggard_bounce_copy", ""}
    assert "duplicate" in dict(res.rejected)["laggard_bounce_copy"]
    assert res.usage == {"total_tokens": 1234}
    hyps = HypothesisStore(store)
    pending = hyps.pending("1h")
    assert len(pending) == 1 and pending[0]["grid_obj"] == {"rank": [0.1, 0.2], "stop": [1.5, 2.5]}
    assert {h["status"] for h in hyps.recent()} == {"proposed", "invalid"}

    # the request carries the lab's context and the model choice, never the key in the body
    body = json.loads(seen[0].content)
    assert body["model"] == "test-model" and body["response_format"] == {"type": "json_object"}
    ctx = json.loads(body["messages"][1]["content"])
    assert ctx["allowed_timeframes"] == ["1h"] and "xs_rank_ret_5" in ctx["available_features"]
    assert "sk-test-not-real" not in seen[0].content.decode()

    # a second identical answer adds nothing new (all duplicates)
    again = run_analyst(store, client, CFG, "binance", ("1h",), {})
    assert not again.created and any("duplicate" in why for _, why in again.rejected)
    # the analyst sees its own previous proposals next time
    assert json.loads(json.loads(seen[1].content)["messages"][1]["content"])[
        "your_previous_hypotheses"
    ]


def test_run_analyst_respects_the_daily_budget_and_api_errors() -> None:
    store = SQLiteStore()
    cfg = AnalystConfig(api_key="k", model="m", max_calls_per_day=1)
    calls: list[httpx.Request] = []
    client = OpenAIClient(cfg, openai_transport({"hypotheses": []}, calls))
    assert run_analyst(store, client, cfg, "binance", ("1h",), {}, clock=lambda: 1e9).skipped == ""
    res = run_analyst(store, client, cfg, "binance", ("1h",), {}, clock=lambda: 1e9 + 60)
    assert "budget" in res.skipped and len(calls) == 1
    # next UTC day the budget resets
    assert run_analyst(store, client, cfg, "binance", ("1h",), {}, clock=lambda: 1e9 + 86_400)
    assert len(calls) == 2

    def down(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    broken = OpenAIClient(CFG, httpx.MockTransport(down))
    assert "500" in run_analyst(SQLiteStore(), broken, CFG, "binance", ("1h",), {}).skipped


# --- isolation: the analyst cannot reach anything that trades --------------------------------

FORBIDDEN = (
    "aqt.brokers",
    "aqt.risk",
    "aqt.stream.engine",
    "aqt.stream.alpaca",
    "aqt.stream.binance",
    "aqt.lab",
    "services",
)


def test_analyst_package_cannot_import_brokers_risk_or_the_engine() -> None:
    for path in (ROOT / "packages" / "aqt" / "analyst").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not name.startswith(FORBIDDEN), f"{path.name} imports {name}"
            if isinstance(node, ast.Name | ast.Attribute):
                ident = node.id if isinstance(node, ast.Name) else node.attr
                assert ident not in {"place_order", "submit_order"}, path.name
    # transitively, too: importing the analyst loads no broker, risk or engine module
    code = (
        "import sys, aqt.analyst.client, aqt.analyst.hypotheses, aqt.analyst.briefing\n"
        f"bad = [m for m in sys.modules if m.startswith({FORBIDDEN!r})]\n"
        "print(bad)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT
    )
    assert out.stdout.strip() == "[]", out.stdout


# --- the lab examines AI hypotheses ----------------------------------------------------------


def test_cycle_tests_pending_ai_hypotheses_in_the_global_fdr() -> None:
    n = 24 * 90
    data = {"LEADUSDC": hourly(n, 1, drift=0.0006)}
    for i in range(3):
        data[f"N{i}USDC"] = hourly(n, 10 + i)

    def interval_loader(symbol: str, start_ms: int, end_ms: int, timeframe: str) -> pd.DataFrame:
        df = data[symbol]
        lo, hi = (pd.Timestamp(t, unit="ms", tz="UTC") for t in (start_ms, end_ms))
        return df[(df.index >= lo) & (df.index < hi)]

    def no_seconds(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        raise AssertionError("hourly research needs no 1-second klines")

    store = SQLiteStore()
    hyps = HypothesisStore(store, clock=lambda: 1e9)
    raw = proposal(
        name="leader_trend",
        entry={"all_of": [{"left": "xs_rank_ret_20", "op": ">", "right": "$rank"},
                          {"left": "close", "op": ">", "right": "ema_50"}]},
        exit={"stop_atr_mult": 3.0, "max_holding_bars": 20},
        params={"rank": 0.7}, grid={"rank": [0.6, 0.7]},
    )  # fmt: skip
    hyps.add(validate_proposal(raw, FEATURES, ("1h",)), "test-model", {})
    cfg = LabConfig(
        symbols=tuple(data), days=85, timeframes=("1h",), swing_families=("trend_follow",),
        min_trades=10, walk_forward_windows=3, monte_carlo_sims=100, workers=1,
    )  # fmt: skip
    lab = KlineData(no_seconds, interval_loader=interval_loader)
    res = run_research_cycle(store, cfg, lab, end_ms=(T0 + n * H) * 1000, clock=lambda: 1e9)
    assert res.error == "", res.error
    (h,) = hyps.recent()
    assert h["status"] in {"promoted", "rejected"} and h["research_run"] == res.run_id
    assert h["verdict"]["symbols_tested"] == len(data)
    assert not hyps.pending()
    # the AI rule counted in the same global FDR as the catalog
    assert res.summary["hypotheses_by_timeframe"]["1h"] > 2 * len(data)


# --- CLI -------------------------------------------------------------------------------------


def test_analyst_cli_dry_run_off_and_mocked_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = str(tmp_path / "lab.sqlite")
    runner = CliRunner()
    res = runner.invoke(cli_module.app, ["analyst", "--dry-run", "--db", db])
    assert res.exit_code == 0, res.output
    assert '"available_features"' in res.output and "OPENAI" not in res.output
    res = runner.invoke(cli_module.app, ["analyst", "--db", db])
    assert res.exit_code == 0 and "AI Analyst: off" in res.output

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("OPENAI_MODEL_STRONG", "test-model")
    content = {"hypotheses": [proposal(), proposal(name="x")]}

    real = OpenAIClient.complete_json

    def fake_complete(self: OpenAIClient, system: str, user: str) -> Any:
        assert self.cfg.model == "test-model"
        return real(OpenAIClient(CFG, openai_transport(content)), system, user)

    monkeypatch.setattr(OpenAIClient, "complete_json", fake_complete)
    res = runner.invoke(cli_module.app, ["analyst", "--db", db, "--timeframes", "1h"])
    assert res.exit_code == 0, res.output
    assert "1 hypotheses accepted, 1 invalid" in res.output and "ai_laggard_bounce" in res.output
    assert "sk-test-not-real" not in res.output
