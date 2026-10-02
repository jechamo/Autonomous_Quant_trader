from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from aqt.analyst.briefing import (
    BriefingStore,
    build_briefing_context,
    run_briefing,
    select_headlines,
    validate_briefing,
)
from aqt.analyst.client import AnalystConfig, OpenAIClient
from aqt.analyst.hypotheses import HypothesisStore
from aqt.news import NewsItem
from aqt.stream.dsl_strategy import ResearchBarBook
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.store import SQLiteStore
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import services.trader.cli as cli
from services.trader.app import create_app
from services.trader.lab_scheduler import LabScheduler
from services.trader.runtime import TraderRuntime
from tests.test_analyst import openai_transport, proposal

# Friday 2 October 2026, 08:50 in New York (12:50 UTC).
NOW = datetime(2026, 10, 2, 12, 50, tzinfo=UTC).timestamp()
CFG = AnalystConfig(api_key="sk-test-not-real", model="test-model", max_calls_per_day=3)
HEADLINES = [
    NewsItem(
        1, NOW - 3600, "Apple Q4 EPS $1.64 Beats $1.60 Estimate", ("AAPL",), url="https://n/1"
    ),
    NewsItem(2, NOW - 600, "Stocks Slide As CPI Comes In Hot", (), url="https://n/2"),
    NewsItem(3, NOW - 7200, "Nvidia Raises Full-Year Forecast", ("NVDA",), url="https://n/3"),
    NewsItem(4, NOW - 60, "Ford Recalls Trucks", ("F",), url="javascript:alert(1)"),
]
UNIVERSE = ("AAPL", "NVDA")
TFS = ("1h", "1d")


def answer(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "market_summary": "La inflación sorprende al alza y Apple bate previsiones.",
        "events": [
            {"headline_ids": [2], "symbols": [], "type": "macro", "importance": 5,
             "why_it_matters": "Un IPC alto retrasa bajadas de tipos."},
            {"headline_ids": [1, 99], "symbols": ["AAPL", "MSFT"], "type": "earnings",
             "importance": 9, "why_it_matters": "Apple supera el BPA esperado."},
            {"headline_ids": [42], "symbols": ["TSLA"], "type": "rating", "importance": 3,
             "why_it_matters": "Noticia inventada."},
        ],
        "watchlist": ["AAPL", "TSLA"],
        "hypotheses": [
            proposal(name="earnings_gap_follow", timeframe="1d"),
            proposal(name="bad", timeframe="1min"),
        ],
    }  # fmt: skip
    body.update(over)
    return body


def test_context_tells_the_date_the_market_status_and_only_real_headlines() -> None:
    chosen = select_headlines([*HEADLINES, HEADLINES[0]], UNIVERSE)
    assert [h.id for h in chosen] == [1, 3, 4, 2]  # universe first, then newest; deduplicated
    ctx = build_briefing_context(NOW, chosen, UNIVERSE, True, ["rsi"], TFS)
    assert ctx["today"] == {
        "date_new_york": "2026-10-02",
        "weekday": "Friday",
        "time_new_york": "08:50",
        "datetime_utc": "2026-10-02 12:50",
        "us_market_open_today": True,
    }
    first = ctx["headlines"][0]
    assert first["id"] == 1 and first["kind"] == "earnings"
    assert first["published_new_york"] == "2026-10-02 07:50"
    assert ctx["traded_universe"] == ["AAPL", "NVDA"] and ctx["allowed_timeframes"] == ["1h", "1d"]
    assert len(select_headlines(HEADLINES, (), limit=2)) == 2


def test_validation_discards_invented_ids_symbols_and_watchlist() -> None:
    b = validate_briefing(answer(), HEADLINES, "2026-10-02")
    assert [e.headline_ids for e in b.events] == [[2], [1]]  # importance clamped to 5; stable
    apple = b.events[1]
    assert apple.symbols == ["AAPL"] and apple.importance == 5 and apple.type == "earnings"
    assert b.watchlist == ["AAPL"]
    text = " | ".join(b.discarded)
    assert "[99]" in text and "Noticia inventada" in text and "MSFT" in text and "TSLA" in text
    odd = validate_briefing(
        {"market_summary": "x", "events": [{"headline_ids": [3], "type": "??", "importance": "a"}],
         "watchlist": "AAPL"}, HEADLINES, "d",
    )  # fmt: skip
    assert odd.events[0].type == "guidance" and odd.events[0].importance == 3
    assert odd.watchlist == []
    with pytest.raises(ValueError, match="market_summary"):
        validate_briefing({"events": []}, HEADLINES, "d")


def test_run_briefing_stores_it_queues_hypotheses_and_respects_the_budget() -> None:
    store = SQLiteStore()
    seen: list[httpx.Request] = []
    client = OpenAIClient(CFG, openai_transport(answer(), seen))

    def run(**kw: Any) -> Any:
        return run_briefing(
            store, client, CFG, HEADLINES, NOW, True, UNIVERSE, TFS, "us_equity",
            clock=lambda: NOW, **kw,
        )  # fmt: skip

    res = run()
    assert res.skipped == "" and res.briefing is not None
    sent = json.loads(seen[0].content)
    assert "{max_hypotheses}" not in sent["messages"][0]["content"]
    user = json.loads(sent["messages"][1]["content"])
    assert user["today"]["date_new_york"] == "2026-10-02" and len(user["headlines"]) == 4
    assert [p.name for p in res.created] == ["ai_earnings_gap_follow"]
    assert res.rejected and res.rejected[0][0] == "bad"
    hyps = HypothesisStore(store, clock=lambda: NOW)
    assert [h["name"] for h in hyps.pending()] == ["ai_earnings_gap_follow"]
    latest = BriefingStore(store).latest()
    assert latest is not None and latest["date"] == "2026-10-02" and latest["n_headlines"] == 4
    assert {h["id"] for h in latest["headlines"]} == {1, 2}  # only the cited headlines are kept
    assert latest["discarded"] and latest["model"] == "test-model"
    # Once per New York day, unless forced; forced runs still share the analyst's daily budget.
    assert run().skipped.startswith("ya hay un resumen") and len(seen) == 1
    assert run(force=True).briefing is not None and len(seen) == 2
    assert run(force=True).briefing is not None and len(seen) == 3
    assert "budget" in run(force=True).skipped and len(seen) == 3
    empty = run_briefing(store, client, CFG, [], NOW + 86_400, None, (), TFS, clock=lambda: NOW)
    assert empty.skipped.startswith("no hay titulares") and len(seen) == 3


def test_briefing_survives_api_errors_and_bad_answers() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    store = SQLiteStore()
    bad = OpenAIClient(CFG, httpx.MockTransport(failing))
    res = run_briefing(store, bad, CFG, HEADLINES, NOW, None, UNIVERSE, TFS, clock=lambda: NOW)
    assert "HTTP 500" in res.skipped and BriefingStore(store).latest() is None
    empty = OpenAIClient(CFG, openai_transport({"events": []}))
    res = run_briefing(store, empty, CFG, HEADLINES, NOW, None, UNIVERSE, TFS, clock=lambda: NOW)
    assert "market_summary" in res.skipped and BriefingStore(store).latest() is None


def test_scheduler_runs_the_briefing_once_per_new_york_weekday_after_08_45() -> None:
    store = SQLiteStore()
    calls: list[float] = []

    async def briefing(now: float) -> str:
        calls.append(now)
        return "" if len(calls) == 1 else "boom"

    eng = StreamingEngine(EngineConfig(symbols=("AAPL",), run_id="t"))
    lab = LabScheduler(eng, store, ResearchBarBook(), None, every_s=0, briefing=briefing)
    early = datetime(2026, 10, 2, 12, 30, tzinfo=UTC).timestamp()  # 08:30 New York
    saturday = datetime(2026, 10, 3, 14, 0, tzinfo=UTC).timestamp()
    assert not lab.briefing_due(early) and lab.briefing_due(NOW) and not lab.briefing_due(saturday)
    asyncio.run(lab.run_briefing(NOW))
    assert calls == [NOW] and not lab.briefing_due(NOW + 3600)
    monday = datetime(2026, 10, 5, 13, 0, tzinfo=UTC).timestamp()
    assert lab.briefing_due(monday)
    asyncio.run(lab.run_briefing(monday))
    status = lab.status()
    assert status["briefing"] is True and status["briefing_error"] == "boom"
    assert not LabScheduler(eng, store, ResearchBarBook(), None).briefing_due(monday)


def test_api_news_serves_the_latest_briefing() -> None:
    store = SQLiteStore()
    eng = StreamingEngine(EngineConfig(symbols=("AAPL",), run_id="t"))
    rt = TraderRuntime(eng, store, feed=None, clock=lambda: NOW)
    with TestClient(create_app(rt)) as client:
        assert client.get("/api/news").json() == {
            "briefing": None,
            "poller": None,
            "scheduled": False,
        }
    b = validate_briefing(answer(), HEADLINES, "2026-10-02")
    BriefingStore(store, clock=lambda: NOW).add(b, HEADLINES, "test-model", {}, 4)
    with TestClient(create_app(rt)) as client:
        got = client.get("/api/news").json()["briefing"]
    assert got["market_summary"].startswith("La inflación")
    assert got["events"][1]["symbols"] == ["AAPL"]
    assert got["headlines"][0]["url"].startswith("https://")


def test_news_cli_needs_keys_shows_the_date_and_runs_the_briefing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = CliRunner()
    db = str(tmp_path / "news.sqlite")
    res = runner.invoke(cli.app, ["news", "--db", db])
    assert res.exit_code == 2 and "needs Alpaca keys" in res.output
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    fetched: list[tuple[Any, ...]] = []

    def fake_fetch(
        key: str, secret: str, start: float, end: float, symbols: Any = (), **kw: Any
    ) -> list[NewsItem]:
        fetched.append((tuple(symbols), kw))
        return list(HEADLINES) if not symbols else [HEADLINES[0]]

    monkeypatch.setattr("aqt.news.alpaca.fetch_news", fake_fetch)
    monkeypatch.setattr(cli, "_market_open_today", lambda creds, now: True)
    res = runner.invoke(cli.app, ["news", "--dry-run", "--db", db, "--symbols", "AAPL,NVDA"])
    assert res.exit_code == 0, res.output
    ctx = json.loads(res.output)
    assert ctx["today"]["us_market_open_today"] is True and len(ctx["headlines"]) == 4
    assert set(ctx["available_features"]) >= {"news_ratio", "rsi_2"}  # stocks + keys: news on
    assert fetched[0] == ((), {"max_items": 400, "sort": "desc"})
    assert fetched[1][0] == ("AAPL", "NVDA")
    res = runner.invoke(cli.app, ["news", "--db", db])
    assert res.exit_code == 0 and "off (set OPENAI_API_KEY" in res.output

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    real = OpenAIClient.complete_json

    def fake_complete(self: OpenAIClient, system: str, user: str) -> Any:
        return real(OpenAIClient(CFG, openai_transport(answer())), system, user)

    monkeypatch.setattr(OpenAIClient, "complete_json", fake_complete)
    res = runner.invoke(cli.app, ["news", "--db", db])
    assert res.exit_code == 0, res.output
    assert "Noticias del día" in res.output and "watchlist: AAPL" in res.output
    assert "descartado" in res.output and "+ hypothesis ai_earnings_gap_follow" in res.output
    assert "sk-test-not-real" not in res.output
    res = runner.invoke(cli.app, ["news", "--db", db])
    assert "skipped: ya hay un resumen" in res.output
    assert cli._briefing_runner(tmp_path / "x.sqlite", cli.MARKETS["stocks"], ("AAPL",))
    monkeypatch.delenv("OPENAI_API_KEY")
    assert cli._briefing_runner(tmp_path / "x.sqlite", cli.MARKETS["stocks"], ("AAPL",)) is None


def test_news_cli_reports_download_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    def down(*a: Any, **k: Any) -> list[NewsItem]:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("aqt.news.alpaca.fetch_news", down)
    res = CliRunner().invoke(cli.app, ["news", "--dry-run"])
    assert res.exit_code == 1 and "could not download headlines: offline" in res.output
