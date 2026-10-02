"""Alpaca News (Benzinga headlines): historical with publication timestamps, and the latest.

Market data only — the same paper keys as the bars (``ALPACA_API_KEY_ID`` /
``ALPACA_API_SECRET_KEY``); nothing here trades. History is cached per symbol and month under
``data/stream/alpaca_news`` (complete months only), so a backfill is paid once.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from aqt.news.items import NewsItem

log = logging.getLogger(__name__)

DATA_URL = "https://data.alpaca.markets"
NEWS_PATH = "/v1beta1/news"
PAGE_LIMIT = 50  # the API maximum


def _ts(raw: str) -> float:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()


def parse_alpaca_news(payload: Mapping[str, Any]) -> list[NewsItem]:
    """``/v1beta1/news`` JSON → items (rows without id, time or headline are skipped)."""
    out = []
    for row in payload.get("news") or []:
        try:
            item = NewsItem(
                id=int(row["id"]),
                created_at=_ts(str(row["created_at"])),
                headline=str(row["headline"]).strip(),
                symbols=tuple(str(s).upper() for s in row.get("symbols") or ()),
                source=str(row.get("source") or ""),
                url=str(row.get("url") or ""),
                summary=str(row.get("summary") or "").strip(),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if item.headline:
            out.append(item)
    return out


def item_to_dict(item: NewsItem) -> dict[str, Any]:
    return {
        "id": item.id, "created_at": item.created_at, "headline": item.headline,
        "symbols": list(item.symbols), "source": item.source, "url": item.url,
        "summary": item.summary,
    }  # fmt: skip


def item_from_dict(row: Mapping[str, Any]) -> NewsItem:
    return NewsItem(
        id=int(row["id"]),
        created_at=float(row["created_at"]),
        headline=str(row["headline"]),
        symbols=tuple(row.get("symbols") or ()),
        source=str(row.get("source") or ""),
        url=str(row.get("url") or ""),
        summary=str(row.get("summary") or ""),
    )


def fetch_news(
    key: str,
    secret: str,
    start: float,
    end: float,
    symbols: Sequence[str] = (),
    max_items: int = 100_000,
    transport: httpx.BaseTransport | None = None,
) -> list[NewsItem]:
    """Every headline published in ``[start, end)`` (epoch s), oldest first; no ``symbols`` =
    the whole feed. Retries politely on rate limits (HTTP 429)."""
    from aqt.stream.binance import system_ssl_context

    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    params: dict[str, Any] = {
        "start": datetime.fromtimestamp(start, UTC).isoformat().replace("+00:00", "Z"),
        "end": datetime.fromtimestamp(end, UTC).isoformat().replace("+00:00", "Z"),
        "limit": PAGE_LIMIT, "sort": "asc", "include_content": "false",
    }  # fmt: skip
    if symbols:
        params["symbols"] = ",".join(symbols)
    kw: dict[str, Any] = (
        {"transport": transport} if transport is not None else {"verify": system_ssl_context()}
    )
    items: list[NewsItem] = []
    with httpx.Client(base_url=DATA_URL, headers=headers, timeout=30, **kw) as c:
        while len(items) < max_items:
            r = c.get(NEWS_PATH, params=params)
            if r.status_code == 429:  # pragma: no cover - live rate limit
                time.sleep(float(r.headers.get("Retry-After", "3")))
                continue
            r.raise_for_status()
            body = r.json()
            items.extend(parse_alpaca_news(body))
            token = body.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
    return items


def load_alpaca_news(
    symbols: Iterable[str],
    start_ms: int,
    end_ms: int,
    key: str,
    secret: str,
    cache_dir: str | Path = "data/stream/alpaca_news",
) -> list[NewsItem]:  # pragma: no cover - network
    """Headlines of ``symbols`` between two instants; complete past months are cached."""
    start = pd.Timestamp(start_ms, unit="ms", tz="UTC")
    end = pd.Timestamp(end_ms, unit="ms", tz="UTC")
    this_month = pd.Timestamp.now(tz="UTC").to_period("M")
    seen: dict[int, NewsItem] = {}
    for sym in sorted({s.upper() for s in symbols}):
        cache = Path(cache_dir) / sym
        cache.mkdir(parents=True, exist_ok=True)
        for month in pd.period_range(start.to_period("M"), end.to_period("M"), freq="M"):
            f = cache / f"{month}.json"
            if month < this_month and f.exists():
                rows = json.loads(f.read_text(encoding="utf-8"))
                got = [item_from_dict(r) for r in rows]
            else:
                lo = month.start_time.tz_localize("UTC").timestamp()
                hi = min((month + 1).start_time.tz_localize("UTC").timestamp(), time.time())
                got = fetch_news(key, secret, lo, hi, (sym,))
                if month < this_month:
                    f.write_text(json.dumps([item_to_dict(i) for i in got]), encoding="utf-8")
                log.info("news %s %s: %d headlines", sym, month, len(got))
            for item in got:
                seen[item.id] = item
    lo_s, hi_s = start.timestamp(), end.timestamp()
    return sorted(
        (i for i in seen.values() if lo_s <= i.created_at < hi_s), key=lambda i: i.created_at
    )
