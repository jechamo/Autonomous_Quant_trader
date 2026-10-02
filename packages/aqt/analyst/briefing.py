"""Morning news briefing: the AI Analyst reads today's real headlines, knowing what day it is.

A language model does not know today's news; asked without a source it invents them. So the
model receives the date and time (New York and UTC), whether the US market opens today, and a
list of real headlines (Alpaca News) with their ids — and is told to use nothing else. The
answer is then checked against that list: an event must cite headline ids that exist, and its
symbols must appear in those headlines; anything else is discarded and reported as discarded.

The briefing is information for the operator (dashboard panel «Noticias del día»). Its
hypotheses join the analyst's queue and are tested by the next research cycle under the global
FDR. It never trades, sizes positions or touches risk settings, and its text is never used as a
backtest feature: a model has read what happened after historical headlines.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from aqt.analyst.client import AnalystConfig, AnalystError, OpenAIClient
from aqt.analyst.hypotheses import (
    HYPOTHESIS_RULES,
    HYPOTHESIS_SCHEMA,
    HypothesisStore,
    Proposal,
    available_features,
    ingest_proposals,
)
from aqt.news.classify import KINDS
from aqt.news.items import NewsItem

if TYPE_CHECKING:  # the analyst never imports the store at runtime (it pulls broker types in)
    from aqt.stream.store import SQLiteStore

NY = ZoneInfo("America/New_York")
MAX_HEADLINES = 120
MAX_EVENTS = 8
MAX_HYPOTHESES = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS news_briefings (
    id INTEGER PRIMARY KEY, created_at REAL NOT NULL, date TEXT NOT NULL, model TEXT,
    n_headlines INTEGER, content TEXT NOT NULL, headlines TEXT NOT NULL, usage TEXT
);
CREATE INDEX IF NOT EXISTS news_briefings_date ON news_briefings(date);
"""

SYSTEM_PROMPT = (
    """You are the morning news analyst of a long-only systematic trading lab. You never \
trade and never tell anyone to buy or sell: you summarise the day's news and propose testable \
hypotheses that the lab examines out-of-sample before anything can trade.

`today` gives the current date and time in New York and UTC and whether the US stock market \
opens today. `headlines` is the ONLY information you have about the news: real headlines with \
their ids, newest first. Do not use outside knowledge about events, prices or companies and do \
not invent news. If nothing important happened, say so.

Answer in Spanish with this JSON object only:
{"market_summary": "at most 120 words: what matters today and why",
 "events": [{"headline_ids": [<ids from headlines>], "symbols": ["<tickers that appear in those \
headlines>"], "type": "<one of kinds>", "importance": <1-5>, "why_it_matters": "one or two \
sentences"}],
 "watchlist": ["<tickers from the headlines worth watching today>"],
 "hypotheses": [<0 to {max_hypotheses} rules>]}

At most 8 events, most important first; every event cites at least one headline id. A \
hypothesis is a general, economically motivated effect the day suggests (e.g. how stocks behave \
after a kind of news), not a bet on one headline. Each is one long-only rule in this JSON DSL:
"""
    + HYPOTHESIS_SCHEMA
    + "\n\n"
    + HYPOTHESIS_RULES
)


@dataclass
class BriefingEvent:
    headline_ids: list[int]
    symbols: list[str]
    type: str
    importance: int
    why_it_matters: str


@dataclass
class Briefing:
    date: str  # New York date the briefing is for
    market_summary: str
    events: list[BriefingEvent]
    watchlist: list[str]
    discarded: list[str] = field(default_factory=list)  # what the model said that was not true

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BriefingResult:
    briefing: Briefing | None = None
    created: list[Proposal] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    skipped: str = ""


def ny_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, NY).date().isoformat()


def select_headlines(
    headlines: Sequence[NewsItem], universe: Sequence[str], limit: int = MAX_HEADLINES
) -> list[NewsItem]:
    """De-duplicated, newest first, those about the traded universe ahead of the rest."""
    mine = {s.upper() for s in universe}
    unique = {h.id: h for h in headlines}.values()
    ranked = sorted(unique, key=lambda h: (not mine & set(h.symbols), -h.created_at))
    return ranked[:limit]


def build_briefing_context(
    now: float,
    headlines: Sequence[NewsItem],
    universe: Sequence[str],
    market_open_today: bool | None,
    features: Sequence[str],
    timeframes: Sequence[str],
) -> dict[str, Any]:
    ny = datetime.fromtimestamp(now, NY)
    return {
        "today": {
            "date_new_york": ny.date().isoformat(),
            "weekday": ny.strftime("%A"),
            "time_new_york": ny.strftime("%H:%M"),
            "datetime_utc": datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d %H:%M"),
            "us_market_open_today": market_open_today,
        },
        "kinds": list(KINDS),
        "traded_universe": list(universe),
        "headlines": [
            {
                "id": h.id,
                "published_new_york": datetime.fromtimestamp(h.created_at, NY).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "symbols": list(h.symbols[:8]),
                "kind": h.kind,
                "headline": h.headline,
                "summary": h.summary[:240],
            }
            for h in headlines
        ],
        "allowed_timeframes": list(timeframes),
        "available_features": list(features),
    }


def _int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def validate_briefing(raw: dict[str, Any], headlines: Sequence[NewsItem], date: str) -> Briefing:
    """Keep only what the headlines support; record everything that was dropped."""
    summary = str(raw.get("market_summary") or "").strip()
    if not summary:
        raise ValueError("no market_summary")
    known = {h.id: h for h in headlines}
    every_symbol = {s for h in headlines for s in h.symbols}
    discarded: list[str] = []
    events: list[BriefingEvent] = []
    raw_events = raw.get("events")
    for ev in raw_events if isinstance(raw_events, list) else []:
        if not isinstance(ev, dict):
            continue
        why = str(ev.get("why_it_matters") or "").strip()[:400]
        cited = [_int(i) for i in ev.get("headline_ids") or []]
        ids = [i for i in cited if i is not None and i in known]
        if len(ids) < len(cited):
            discarded.append(f"ids inexistentes {sorted(set(cited) - set(ids), key=str)}")
        if not ids:
            discarded.append(f"evento sin titular real: {why[:80]}")
            continue
        allowed = {s for i in ids for s in known[i].symbols}
        asked = [str(s).upper() for s in ev.get("symbols") or []]
        invented = [s for s in asked if s not in allowed]
        if invented:
            discarded.append(f"símbolos que no están en sus titulares: {invented}")
        kind = str(ev.get("type") or "")
        importance = _int(ev.get("importance")) or 3
        events.append(
            BriefingEvent(
                headline_ids=ids,
                symbols=[s for s in dict.fromkeys(asked) if s in allowed],
                type=kind if kind in KINDS else known[ids[0]].kind,
                importance=min(max(importance, 1), 5),
                why_it_matters=why,
            )
        )
    events.sort(key=lambda e: -e.importance)
    raw_watch = raw.get("watchlist")
    watch = [str(s).upper() for s in raw_watch] if isinstance(raw_watch, list) else []
    invented = [s for s in watch if s not in every_symbol]
    if invented:
        discarded.append(f"watchlist fuera de los titulares: {invented}")
    return Briefing(
        date=date,
        market_summary=summary[:1500],
        events=events[:MAX_EVENTS],
        watchlist=[s for s in dict.fromkeys(watch) if s in every_symbol][:15],
        discarded=discarded,
    )


class BriefingStore:
    def __init__(self, store: SQLiteStore, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock
        store.executescript(SCHEMA)

    def add(
        self,
        briefing: Briefing,
        headlines: Sequence[NewsItem],
        model: str,
        usage: dict[str, Any],
        n_headlines: int,
    ) -> int:
        cited = {i for e in briefing.events for i in e.headline_ids}
        rows = [
            {"id": h.id, "created_at": h.created_at, "headline": h.headline, "url": h.url,
             "symbols": list(h.symbols), "source": h.source}
            for h in headlines
            if h.id in cited
        ]  # fmt: skip
        return self.store.execute(
            "INSERT INTO news_briefings (created_at, date, model, n_headlines, content, "
            "headlines, usage) VALUES (?,?,?,?,?,?,?)",
            (self.clock(), briefing.date, model, n_headlines, json.dumps(briefing.to_dict()),
             json.dumps(rows), json.dumps(usage)),
        )  # fmt: skip

    def has_date(self, date: str) -> bool:
        return bool(self.store.query("SELECT 1 FROM news_briefings WHERE date=? LIMIT 1", (date,)))

    def latest(self) -> dict[str, Any] | None:
        rows = self.store.query(
            "SELECT id, created_at, date, model, n_headlines, content, headlines "
            "FROM news_briefings ORDER BY id DESC LIMIT 1"
        )
        if not rows:
            return None
        row = rows[0]
        return {
            **{k: row[k] for k in ("id", "created_at", "date", "model", "n_headlines")},
            **json.loads(row["content"]),
            "headlines": json.loads(row["headlines"]),
        }


def run_briefing(
    store: SQLiteStore,
    client: OpenAIClient,
    cfg: AnalystConfig,
    headlines: Sequence[NewsItem],
    now: float,
    market_open_today: bool | None,
    universe: Sequence[str],
    timeframes: Sequence[str],
    session: str = "us_equity",
    news_features: bool = False,
    force: bool = False,
    clock: Callable[[], float] = time.time,
) -> BriefingResult:
    """One briefing per New York day; shares the analyst's daily call budget."""
    briefings = BriefingStore(store, clock)
    date = ny_date(now)
    if not force and briefings.has_date(date):
        return BriefingResult(skipped=f"ya hay un resumen para {date}")
    chosen = select_headlines(headlines, universe)
    if not chosen:
        return BriefingResult(skipped="no hay titulares en la ventana pedida")
    hyps = HypothesisStore(store, clock)
    if hyps.calls_today() >= cfg.max_calls_per_day:
        return BriefingResult(skipped=f"daily budget reached ({cfg.max_calls_per_day} calls)")
    features = available_features(session, news_features)
    context = build_briefing_context(now, chosen, universe, market_open_today, features, timeframes)
    system = SYSTEM_PROMPT.replace("{max_hypotheses}", str(MAX_HYPOTHESES))
    hyps.count_call()
    try:
        completion = client.complete_json(system, json.dumps(context, ensure_ascii=False))
        briefing = validate_briefing(completion.content, chosen, date)
    except (AnalystError, ValueError) as exc:
        return BriefingResult(skipped=str(exc))
    result = BriefingResult(briefing=briefing, usage=completion.usage)
    result.created, result.rejected = ingest_proposals(
        hyps, completion.content.get("hypotheses"), features, timeframes,
        completion.model, completion.usage, MAX_HYPOTHESES,
    )  # fmt: skip
    briefings.add(briefing, chosen, completion.model, completion.usage, len(chosen))
    return result
