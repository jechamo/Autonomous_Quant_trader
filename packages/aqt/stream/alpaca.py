"""Alpaca market data for US stocks/ETFs: real-time IEX stream (quotes + trades) and calendar.

Market data only — this module never places orders. Credentials (paper keys are enough) come
from the environment / ``.env``: ``ALPACA_API_KEY_ID`` and ``ALPACA_API_SECRET_KEY``.

Alpaca trades carry no aggressor flag, so each trade is classified with the quote rule (at/above
the ask = buy, at/below the bid = sell) and the tick rule as a fallback (Lee & Ready). Live
strategies that use order-flow features read the bar-level BVC estimate instead (see
``aqt.stream.stocks``), exactly as in research; the classified trades feed the dashboard's flow.

The free IEX feed only shows IEX's own book (a few % of US volume), so its spreads are often
wider than the national best bid/offer — a conservative bias for a paper book.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from aqt.stream.binance import FeedStatus, system_ssl_context
from aqt.stream.events import Event, Quote, TradeTick

log = logging.getLogger(__name__)

STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"
TRADING_URL = "https://paper-api.alpaca.markets"
KEY_VAR, SECRET_VAR = "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"
HOW_TO_GET_KEYS = (
    "Alpaca needs free API keys even for paper trading and market data:\n"
    "  1. create an account at https://alpaca.markets (paper trading needs no deposit)\n"
    "  2. in the Paper Trading dashboard, generate API keys\n"
    f"  3. put them in .env (never commit it): {KEY_VAR}=... and {SECRET_VAR}=..."
)


# Accepted spellings (first match wins), so an existing .env does not have to be renamed.
KEY_ALIASES = (KEY_VAR, "ALPACA_KEY_PAPER", "APCA_API_KEY_ID")
SECRET_ALIASES = (SECRET_VAR, "ALPACA_SECRET_PAPER", "APCA_API_SECRET_KEY")
ENDPOINT_ALIASES = ("ALPACA_ENDPOINT", "ALPACA_endpoint", "APCA_API_BASE_URL")


def _first(env: Mapping[str, str], names: Sequence[str]) -> str:
    return next((env[n].strip() for n in names if env.get(n, "").strip()), "")


def alpaca_credentials(env: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    env = os.environ if env is None else env
    key, secret = _first(env, KEY_ALIASES), _first(env, SECRET_ALIASES)
    return (key, secret) if key and secret else None


def alpaca_trading_url(env: Mapping[str, str] | None = None) -> str:
    """The paper trading host. A live endpoint is refused: this system only trades paper."""
    env = os.environ if env is None else env
    raw = _first(env, ENDPOINT_ALIASES) or TRADING_URL
    host = raw.split("://", 1)[-1].split("/", 1)[0]
    if host != "paper-api.alpaca.markets":
        raise ValueError(f"only the Alpaca PAPER endpoint is allowed, got host {host!r}")
    return f"https://{host}"


def _ts(raw: str) -> float:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()


class AlpacaParser:
    """Stateful parser: remembers the last quote/trade per symbol to sign trades."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self._quotes: dict[str, Quote] = {}
        self._last_px: dict[str, float] = {}
        self._last_side: dict[str, bool] = {}

    def parse(self, msg: Mapping[str, Any]) -> Event | None:
        kind = msg.get("T")
        try:
            if kind == "q":
                q = Quote(
                    symbol=str(msg["S"]),
                    ts=self.clock(),
                    bid=float(msg["bp"]),
                    bid_qty=float(msg["bs"]),
                    ask=float(msg["ap"]),
                    ask_qty=float(msg["as"]),
                )
                if q.valid:
                    self._quotes[q.symbol] = q
                    return q
                return None
            if kind == "t":
                sym, px, qty = str(msg["S"]), float(msg["p"]), float(msg["s"])
                return TradeTick(sym, self.clock(), px, qty, self._seller_aggressor(sym, px))
        except (KeyError, TypeError, ValueError):
            log.warning("malformed Alpaca message: %s", str(msg)[:200])
        return None

    def _seller_aggressor(self, sym: str, px: float) -> bool:
        q = self._quotes.get(sym)
        if q is not None and px >= q.ask:
            sell = False
        elif q is not None and px <= q.bid:
            sell = True
        else:
            last = self._last_px.get(sym)
            if last is None or px == last:
                sell = self._last_side.get(sym, q is not None and px < q.mid)
            else:
                sell = px < last
        self._last_px[sym] = px
        self._last_side[sym] = sell
        return sell


class AlpacaFeed:
    def __init__(
        self,
        symbols: Sequence[str],
        key: str,
        secret: str,
        url: str = STREAM_URL,
        clock: Callable[[], float] = time.time,
        max_backoff_s: float = 30.0,
    ) -> None:
        if not symbols:
            raise ValueError("at least one symbol is required")
        self.symbols = [s.upper() for s in symbols]
        self._key, self._secret = key, secret
        self.url = url
        self.clock = clock
        self.max_backoff_s = max_backoff_s
        self.status = FeedStatus()
        self.parser = AlpacaParser(clock)

    def __repr__(self) -> str:  # never leak credentials
        return f"AlpacaFeed(symbols={self.symbols}, url={self.url})"

    async def events(self) -> AsyncIterator[Event]:  # pragma: no cover - network
        import websockets

        backoff = 1.0
        while True:
            try:
                async with websockets.connect(self.url, ssl=system_ssl_context()) as ws:
                    await ws.send(
                        json.dumps({"action": "auth", "key": self._key, "secret": self._secret})
                    )
                    await ws.send(
                        json.dumps(
                            {"action": "subscribe", "trades": self.symbols, "quotes": self.symbols}
                        )
                    )
                    async for raw in ws:
                        for msg in json.loads(raw):
                            if msg.get("T") == "error":
                                raise RuntimeError(
                                    f"Alpaca error {msg.get('code')}: {msg.get('msg')}"
                                )
                            if msg.get("T") == "success" and msg.get("msg") == "authenticated":
                                self.status.connected = True
                                backoff = 1.0
                            event = self.parser.parse(msg)
                            if event is not None:
                                self.status.messages += 1
                                self.status.last_message_at = self.clock()
                                yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.last_error = repr(exc)[:300]
                log.warning("Alpaca feed error: %s, reconnecting in %.0fs", exc, backoff)
            self.status.connected = False
            self.status.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.max_backoff_s)


def parse_calendar(rows: Sequence[Mapping[str, Any]]) -> set[date]:
    """Trading days from Alpaca's ``/v2/calendar`` response."""
    return {date.fromisoformat(str(r["date"])) for r in rows}


def fetch_trading_days(
    key: str, secret: str, start: date, end: date, base_url: str = TRADING_URL
) -> set[date]:  # pragma: no cover - network
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    with httpx.Client(base_url=base_url, headers=headers, verify=system_ssl_context()) as c:
        r = c.get("/v2/calendar", params={"start": str(start), "end": str(end)})
        r.raise_for_status()
    return parse_calendar(r.json())


DATA_URL = "https://data.alpaca.markets"


def parse_alpaca_bars(payload: Mapping[str, Any], symbol: str) -> pd.DataFrame:
    """``/v2/stocks/bars`` JSON → regular-session 1-minute OHLCV (UTC index)."""
    from aqt.stream.session import UsEquitySession

    rows = (payload.get("bars") or {}).get(symbol) or []
    if not rows:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC"),
            dtype=float,
        )
    df = pd.DataFrame(
        {
            "open": [r["o"] for r in rows],
            "high": [r["h"] for r in rows],
            "low": [r["l"] for r in rows],
            "close": [r["c"] for r in rows],
            "volume": [r["v"] for r in rows],
        },
        index=pd.to_datetime([r["t"] for r in rows], utc=True),
        dtype=float,
    )
    session = UsEquitySession()
    mask = [session.is_open(t.timestamp()) for t in df.index]
    return df[mask]


def load_alpaca_1m(
    symbol: str,
    start_ms: int,
    end_ms: int,
    key: str,
    secret: str,
    cache_dir: str | Path = "data/stream/alpaca1m",
) -> pd.DataFrame:  # pragma: no cover - network
    """Years of 1-minute IEX bars (regular session) with BVC flow; complete days are cached."""
    from aqt.stream.session import NY
    from aqt.stream.stocks import with_bvc

    cache = Path(cache_dir) / symbol.upper()
    cache.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(start_ms, unit="ms", tz="UTC")
    end = pd.Timestamp(end_ms, unit="ms", tz="UTC")
    today = datetime.now(NY).date()
    frames, missing = [], []
    for d in pd.date_range(start.tz_convert(NY).date(), end.tz_convert(NY).date(), freq="D"):
        f = cache / f"{d.date()}.parquet"
        if d.date() < today and f.exists():
            frames.append(pd.read_parquet(f))
        elif d.weekday() < 5:
            missing.append(d.date())
    if missing:
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        lo = pd.Timestamp(str(missing[0]), tz=NY).tz_convert("UTC")
        hi = min(
            end, pd.Timestamp(str(missing[-1]), tz=NY).tz_convert("UTC") + pd.Timedelta(days=1)
        )
        params: dict[str, Any] = {
            "symbols": symbol, "timeframe": "1Min", "start": lo.isoformat(), "end": hi.isoformat(),
            "limit": 10_000, "feed": "iex", "adjustment": "raw",
        }  # fmt: skip
        got = []
        with httpx.Client(base_url=DATA_URL, headers=headers, verify=system_ssl_context()) as c:
            while True:
                r = c.get("/v2/stocks/bars", params=params, timeout=30)
                r.raise_for_status()
                body = r.json()
                got.append(parse_alpaca_bars(body, symbol))
                token = body.get("next_page_token")
                if not token:
                    break
                params["page_token"] = token
        fresh = pd.concat(got) if got else parse_alpaca_bars({}, symbol)
        days = pd.DatetimeIndex(fresh.index).tz_convert(NY).strftime("%Y-%m-%d")
        for d in sorted(set(days)):
            if d < str(today):
                fresh[days == d].to_parquet(cache / f"{d}.parquet")
        for day in missing:  # past weekdays without bars are market holidays: cache them empty
            if day < today and str(day) not in set(days):
                parse_alpaca_bars({}, symbol).to_parquet(cache / f"{day}.parquet")
        frames.append(fresh)
    bars = pd.concat(frames) if frames else parse_alpaca_bars({}, symbol)
    bars = bars[~bars.index.duplicated(keep="last")].sort_index()
    return with_bvc(bars[(bars.index >= start) & (bars.index < end)].astype(float))


def stock_bar_loader(
    env: Mapping[str, str] | None = None,
) -> tuple[str, Callable[..., pd.DataFrame]]:
    """Alpaca (years of history) when keys are configured, else Yahoo (~7 days)."""
    creds = alpaca_credentials(env)
    if creds is None:
        from aqt.stream.stocks import load_yahoo_1m

        return "yahoo", load_yahoo_1m

    def load(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        return load_alpaca_1m(symbol, start_ms, end_ms, *creds)

    return "alpaca", load
