from __future__ import annotations

import asyncio
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest
from aqt.features.cross_section import augment
from aqt.features.engine import FeatureEngine
from aqt.lab.cycle import KlineData, LabConfig, run_research_cycle
from aqt.lab.registry import RuleRegistry
from aqt.news import NEWS_COLUMNS, NEWS_LAG_S, NewsBook, NewsItem, classify_headline
from aqt.news.alpaca import fetch_news, item_from_dict, item_to_dict, parse_alpaca_news
from aqt.news.book import DAY_S, news_features
from aqt.strategies.dsl import Condition, ExitRules, Rule, StrategySpec
from aqt.strategies.swing import SWING_CATALOG
from aqt.stream.bars import BarAggregator
from aqt.stream.dsl_strategy import DslStreamStrategy, ResearchBarBook
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.events import Quote
from aqt.stream.stocks import bar_events
from aqt.stream.store import SQLiteStore

from services.trader.news_poller import OVERLAP_S, NewsPoller
from services.trader.runtime import TraderRuntime
from tests.test_swing import T0, H, _snap, hourly


def _item(i: int, ts: float, headline: str = "Acme wins a contract", *syms: str) -> NewsItem:
    return NewsItem(i, ts, headline, syms or ("ACME",))


def test_parse_alpaca_news_and_classify_headlines() -> None:
    payload = {
        "news": [
            {"id": 7, "created_at": "2026-10-01T12:30:00Z", "updated_at": "2026-10-01T13:00:00Z",
             "headline": "Apple Q4 EPS $1.64 Beats $1.60 Estimate", "symbols": ["aapl"],
             "source": "benzinga", "url": "https://x/7", "summary": " Strong quarter. "},
            {"id": 8, "created_at": "not a date", "headline": "broken"},
            {"id": 9, "created_at": "2026-10-01T12:31:00Z", "headline": "  "},
        ],
        "next_page_token": None,
    }  # fmt: skip
    (item,) = parse_alpaca_news(payload)
    assert item.id == 7 and item.symbols == ("AAPL",) and item.summary == "Strong quarter."
    assert item.created_at == pd.Timestamp("2026-10-01T12:30:00Z").timestamp()
    assert item.kind == "earnings" and item_from_dict(item_to_dict(item)) == item
    cases = {
        "Reddit Prices IPO At $34, Above Range": "ipo",
        "Nvidia Raises Full-Year Forecast": "guidance",
        "Morgan Stanley Upgrades Tesla To Overweight": "rating",
        "Microsoft To Acquire Activision": "m&a",
        "FDA Approves Lilly's Drug After Phase 3 Trial": "fda",
        "Google Sued Over Ad Tech": "legal",
        "Stocks Slide As CPI Comes In Hot": "macro",
        "Tesla Unveils A New Car": "other",
    }
    for headline, kind in cases.items():
        assert classify_headline(headline) == kind, headline


def test_news_features_are_causal_and_never_read_missing_coverage_as_quiet() -> None:
    idx = pd.date_range("2026-01-01", periods=40, freq="D", tz="UTC")
    start = idx[0].timestamp()
    book = NewsBook(coverage_start=start, covered_until=idx[35].timestamp())
    bar = idx[30].timestamp()
    cutoff = bar + DAY_S - NEWS_LAG_S
    added = book.add(
        [
            _item(1, cutoff, "Acme Q3 earnings top estimates"),  # exactly at the cutoff: counts
            _item(2, cutoff + 1),  # after the cutoff: belongs to the next bar
            _item(1, cutoff),  # duplicate id
            _item(3, bar, "Ten stocks to watch", "ACME", "B", "C", "D", "E", "F"),  # round-up
            *(_item(10 + k, start + (2 + k) * DAY_S) for k in range(20)),  # one a day: baseline
        ]
    )
    assert added == 23
    f = news_features(book, "acme", idx, DAY_S)
    assert list(f.columns) == list(NEWS_COLUMNS)
    assert f.iloc[:21].isna().all().all()  # the 20-day baseline is not covered yet
    assert f.iloc[35:].isna().all().all() and f.iloc[34].notna().all()  # past the coverage
    assert f["news_1d"].iloc[30] == 1 and f["news_earnings_1d"].iloc[30] == 1
    assert f["news_1d"].iloc[31] == 1 and f["news_earnings_1d"].iloc[31] == 0
    assert f["news_ratio"].iloc[30] == pytest.approx(1 / (12 / 20 + 1))  # days 10-21 of 20
    assert f["news_1d"].iloc[25] == 0 and f["news_ratio"].iloc[25] == 0
    # Causal: headlines published later never change earlier rows.
    later = NewsBook(coverage_start=start, covered_until=idx[35].timestamp())
    later.add([_item(1, cutoff, "Acme Q3 earnings top estimates")])
    later.add([_item(10 + k, start + (2 + k) * DAY_S) for k in range(20)])
    before = news_features(later, "ACME", idx[:31], DAY_S)
    pd.testing.assert_frame_equal(before, f.iloc[:31])
    assert news_features(book, "OTHER", idx, DAY_S)["news_1d"].iloc[30] == 0


def test_fetch_news_paginates_oldest_first() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        token = request.url.params.get("page_token")
        rows = [{"id": 2 if token else 1, "created_at": "2026-10-01T12:00:00Z",
                 "headline": "Acme news", "symbols": ["ACME"]}]  # fmt: skip
        return httpx.Response(200, json={"news": rows, "next_page_token": None if token else "p2"})

    items = fetch_news(
        "key", "secret", 1.0e9, 1.1e9, ("ACME",), transport=httpx.MockTransport(handler)
    )
    assert [i.id for i in items] == [1, 2] and len(seen) == 2
    first = seen[0]
    assert first.url.path == "/v1beta1/news" and first.headers["APCA-API-KEY-ID"] == "key"
    assert first.url.params["symbols"] == "ACME" and first.url.params["sort"] == "asc"
    assert first.url.params["limit"] == "50" and first.url.params["start"].endswith("Z")
    assert seen[1].url.params["page_token"] == "p2"


NEWS_RULE = StrategySpec(
    name="news_parity",
    family="test",
    entry=Rule(all_of=[Condition(left="news_1d", op=">=", right=1)]),
    exit=ExitRules(stop_atr_mult=2.0, max_holding_bars=5),
)


def _news_book(index: pd.DatetimeIndex, every: int = 40) -> NewsBook:
    book = NewsBook(index[0].timestamp() - 30 * DAY_S, index[-1].timestamp() + H)
    book.add([_item(k, index[k].timestamp() + 600) for k in range(0, len(index), every)])
    return book


def test_live_news_rule_matches_research() -> None:
    raw = {"ACME": hourly(150, 3)}
    book = _news_book(pd.DatetimeIndex(raw["ACME"].index))
    feats = FeatureEngine().compute(augment(raw, H, news=book)["ACME"])
    tradable = NEWS_RULE.entry_signal(feats) & feats["atr"].notna()
    expected = {int(t.timestamp()) for t in feats.index[tradable.to_numpy()]}
    assert expected
    live = ResearchBarBook(news=book)
    strat = DslStreamStrategy(spec=NEWS_RULE, symbol="ACME", timeframe_s=H, book=live)
    agg = BarAggregator("ACME", 5.0)
    fired: set[int] = set()
    for e in bar_events(raw["ACME"], "ACME", 0.0001, H):
        for b in agg.on_quote(e) if isinstance(e, Quote) else agg.on_trade(e):
            strat.on_bar(b)
            if strat.entry(_snap("ACME", b.end)) is not None:
                fired.add(int(live.series("ACME", H).bars[-1][0]))
    assert fired == expected - {int(feats.index[-1].timestamp())}


def test_news_rule_never_signals_without_a_news_source() -> None:
    raw = hourly(60, 4)
    book = ResearchBarBook()  # no news connected
    book.seed("ACME", H, raw)
    spec = NEWS_RULE.model_copy(
        update={
            "exit": ExitRules(
                stop_atr_mult=2.0,
                exit_signal=Rule(all_of=[Condition(left="news_ratio", op=">", right=3)]),
            )
        }
    )
    strat = DslStreamStrategy(spec=spec, symbol="ACME", timeframe_s=H, book=book)
    book.series("ACME", H).final_seq += 1
    assert strat.entry(_snap("ACME", T0)) is None and strat.should_exit(_snap("ACME", T0)) is False


def _planted(n: int, seed: int, drift_after: float) -> tuple[pd.DataFrame, list[int]]:
    """Hourly bars with a +3 % jump on heavy volume every 4 days, then ``drift_after`` per bar
    for 10 bars."""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, 0.003, n)
    vol = rng.exponential(100, n) + 50
    events = list(range(30, n - 12, 96))
    for k in events:
        ret[k] += 0.03
        vol[k] *= 5
        ret[k + 1 : k + 11] += drift_after
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[100.0], close[:-1]])
    df = pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.001,
         "low": np.minimum(open_, close) * 0.999, "close": close, "volume": vol,
         "taker_buy_volume": vol / 2},
        index=pd.to_datetime(T0 + H * np.arange(n), unit="s", utc=True),
    )  # fmt: skip
    return df, events


def test_cycle_finds_planted_news_drift_and_switches_news_off_without_a_source() -> None:
    """NEWS jumps on a burst of headlines and keeps drifting; QUIET makes the same jumps with no
    news and no drift. With headlines the lab must promote news_drift on NEWS only."""
    n = 24 * 200
    news_df, events = _planted(n, 1, drift_after=0.004)
    quiet_df, _ = _planted(n, 2, drift_after=0.0)
    data = {"NEWS": news_df, "QUIET": quiet_df}
    headlines = [
        _item(1000 * k + j, float(news_df.index[k].timestamp()) + 600, "Acme lands deal", "NEWS")
        for k in events
        for j in range(12)
    ]

    def interval_loader(symbol: str, start_ms: int, end_ms: int, timeframe: str) -> pd.DataFrame:
        df = data[symbol]
        lo, hi = (
            pd.Timestamp(start_ms, unit="ms", tz="UTC"),
            pd.Timestamp(end_ms, unit="ms", tz="UTC"),
        )
        return df[(df.index >= lo) & (df.index < hi)]

    calls: list[tuple[Any, ...]] = []

    def news_loader(symbols: Any, start_ms: int, end_ms: int) -> list[NewsItem]:
        calls.append((tuple(symbols), start_ms, end_ms))
        return [h for h in headlines if start_ms / 1000 <= h.created_at < end_ms / 1000]

    cfg = LabConfig(
        symbols=tuple(data), days=210, news_days=230, timeframes=("1h",),
        swing_families=("news_drift",), min_trades=10, walk_forward_windows=3,
        monte_carlo_sims=200, workers=1, session="24/7",
    )  # fmt: skip
    end_ms = (T0 + n * H) * 1000
    lab = KlineData(lambda *a: pd.DataFrame(), interval_loader=interval_loader)
    store = SQLiteStore()
    res = run_research_cycle(
        store, cfg, lab, end_ms=end_ms, clock=lambda: 1e9, news_loader=news_loader
    )
    assert res.error == "", res.error
    assert res.summary["news"] == {"enabled": True, "headlines": len(headlines), "days": 230}
    assert calls == [(("NEWS", "QUIET"), end_ms - 230 * 86_400_000, end_ms)]
    active = RuleRegistry(store).active()
    assert {r.symbol for r in active} == {"NEWS"}, res.summary["top_pairs"][:3]
    assert all(r.spec is not None and r.spec.name.startswith("news_drift") for r in active)

    # Without a news source (or when it fails) the news families are simply not tested.
    off = run_research_cycle(SQLiteStore(), cfg, lab, end_ms=end_ms, clock=lambda: 1e9)
    assert off.summary["news"] == {"enabled": False} and off.summary["n_hypotheses"] == 0

    def broken(*_: Any) -> list[NewsItem]:
        raise httpx.ConnectError("news down")

    failed = run_research_cycle(
        SQLiteStore(), cfg, lab, end_ms=end_ms, clock=lambda: 1e9, news_loader=broken
    )
    assert failed.error == "" and "news down" in failed.summary["news"]["error"]


def test_news_families_only_with_news() -> None:
    stocks = LabConfig(symbols=("A",), session="us_equity")
    news_families = {"news_drift", "quiet_drop_reversal", "earnings_gap_drift"}
    assert not news_families & set(stocks.catalog_for("1d")[1])
    assert news_families <= set(stocks.catalog_for("1d", news=True)[1])
    assert news_families <= set(SWING_CATALOG)


def test_news_poller_backfills_then_overlaps_and_survives_errors() -> None:
    now = [1_000_000.0]
    windows: list[tuple[float, float]] = []

    def fetch(start: float, end: float) -> list[NewsItem]:
        windows.append((start, end))
        return [_item(len(windows), end - 10)]

    poller = NewsPoller(fetch, every_s=0.0, clock=lambda: now[0])
    assert poller.book.coverage_start == pytest.approx(now[0] - 22 * DAY_S)
    assert poller.poll_once() == 1
    now[0] += 60
    poller.poll_once()
    assert windows == [(now[0] - 60 - 22 * DAY_S, now[0] - 60), (now[0] - 60 - OVERLAP_S, now[0])]
    assert poller.status()["headlines"] == 2 and poller.book.covered_until == now[0]

    def boom(start: float, end: float) -> list[NewsItem]:
        raise RuntimeError("api down")

    broken = NewsPoller(boom, every_s=0.01, clock=lambda: now[0])

    async def run_briefly() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(broken.loop(), 0.05)

    asyncio.run(run_briefly())
    assert broken.status()["last_error"] == "RuntimeError: api down"
    eng = StreamingEngine(EngineConfig(symbols=("ACME",), run_id="t"))
    rt = TraderRuntime(eng, SQLiteStore(), feed=None, clock=lambda: now[0], news=poller)
    assert rt.snapshot()["news"]["polls"] == 2


def test_ai_news_hypotheses_wait_for_a_news_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from aqt.analyst.hypotheses import HypothesisStore, available_features, validate_proposal

    import services.trader.cli as cli
    from tests.test_analyst import proposal

    with_news = available_features("us_equity", news=True)
    assert set(NEWS_COLUMNS) <= set(with_news)
    assert not set(NEWS_COLUMNS) & set(available_features("us_equity"))
    store = SQLiteStore()
    hyps = HypothesisStore(store, clock=lambda: 1e9)
    raw = proposal(
        name="news_burst",
        entry={"all_of": [{"left": "news_ratio", "op": ">", "right": "$k"}]},
        exit={"stop_atr_mult": 2.0, "max_holding_bars": 5},
        params={"k": 2},
        grid={"k": [2, 3]},
    )
    hyps.add(validate_proposal(raw, with_news, ("1h",)), "test-model", {})
    n = 24 * 40
    data = hourly(n, 1)

    def interval_loader(symbol: str, start_ms: int, end_ms: int, timeframe: str) -> pd.DataFrame:
        return data

    cfg = LabConfig(
        symbols=("A",), days=40, timeframes=("1h",), swing_families=("trend_follow",),
        min_trades=10, walk_forward_windows=3, monte_carlo_sims=50, workers=1,
    )  # fmt: skip
    lab = KlineData(lambda *a: pd.DataFrame(), interval_loader=interval_loader)
    res = run_research_cycle(store, cfg, lab, end_ms=(T0 + n * H) * 1000, clock=lambda: 1e9)
    assert res.error == "", res.error
    assert [h["name"] for h in hyps.pending()] == ["ai_news_burst"]  # untested: still waiting
    # The CLI only wires news for stocks with Alpaca keys.
    assert cli._news_loader(cli.MARKETS["binance"]) is None
    assert cli._news_loader(cli.MARKETS["stocks"]) is None and cli._news_poller(("AAPL",)) is None
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    assert callable(cli._news_loader(cli.MARKETS["stocks"]))
    assert isinstance(cli._news_poller(("AAPL",)), NewsPoller)
