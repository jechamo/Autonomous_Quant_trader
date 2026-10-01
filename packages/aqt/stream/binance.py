"""Binance spot public market data: WebSocket stream (bookTicker + aggTrade) and REST metadata.

Market data only — no API key, no account access, no order endpoints. The default host is
Binance's public market-data mirror (``data-stream.binance.vision``). Events are timestamped with
the local receive time, which is the moment the engine can actually act on them.

TLS uses the operating-system certificate store, so it also works behind antivirus/corporate
proxies that re-sign HTTPS (where the bundled ``certifi`` store fails).
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from aqt.stream.events import Event, Quote, TradeTick

log = logging.getLogger(__name__)

WS_URL = "wss://data-stream.binance.vision"
REST_URL = "https://data-api.binance.vision"


def system_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def parse_message(msg: dict[str, Any], ts: float) -> Event | None:
    """Parse a combined-stream message (``{"stream": ..., "data": {...}}``)."""
    data = msg.get("data", msg)
    stream = str(msg.get("stream", ""))
    try:
        if stream.endswith("@bookTicker") or {"b", "a", "B", "A"} <= data.keys():
            return Quote(
                symbol=str(data["s"]).upper(),
                ts=ts,
                bid=float(data["b"]),
                bid_qty=float(data["B"]),
                ask=float(data["a"]),
                ask_qty=float(data["A"]),
            )
        if data.get("e") == "aggTrade" or stream.endswith("@aggTrade"):
            return TradeTick(
                symbol=str(data["s"]).upper(),
                ts=ts,
                price=float(data["p"]),
                qty=float(data["q"]),
                buyer_is_maker=bool(data["m"]),
            )
    except (KeyError, TypeError, ValueError):
        log.warning("malformed message: %s", str(msg)[:200])
    return None


@dataclass
class FeedStatus:
    connected: bool = False
    messages: int = 0
    reconnects: int = 0
    last_message_at: float = 0.0
    last_error: str = ""

    def healthy(self, now: float, max_silence_s: float = 10.0) -> bool:
        return self.connected and now - self.last_message_at <= max_silence_s


class BinanceFeed:
    def __init__(
        self,
        symbols: Sequence[str],
        base_url: str = WS_URL,
        clock: Callable[[], float] = time.time,
        max_backoff_s: float = 30.0,
    ) -> None:
        if not symbols:
            raise ValueError("at least one symbol is required")
        self.symbols = [s.upper() for s in symbols]
        self.base_url = base_url.rstrip("/")
        self.clock = clock
        self.max_backoff_s = max_backoff_s
        self.status = FeedStatus()

    @property
    def url(self) -> str:
        streams = "/".join(
            f"{s.lower()}@{kind}" for s in self.symbols for kind in ("bookTicker", "aggTrade")
        )
        return f"{self.base_url}/stream?streams={streams}"

    async def events(self) -> AsyncIterator[Event]:  # pragma: no cover - network
        import websockets

        backoff = 1.0
        while True:
            try:
                async with websockets.connect(
                    self.url, ssl=system_ssl_context(), open_timeout=15, ping_interval=20
                ) as ws:
                    self.status.connected = True
                    backoff = 1.0
                    log.info("connected to %s", self.url)
                    async for raw in ws:
                        now = self.clock()
                        self.status.messages += 1
                        self.status.last_message_at = now
                        event = parse_message(json.loads(raw), now)
                        if event is not None:
                            yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.last_error = repr(exc)[:300]
                log.warning("feed error: %s — reconnecting in %.0fs", exc, backoff)
            self.status.connected = False
            self.status.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.max_backoff_s)


KNOWN_QUOTES = ("FDUSD", "USDC", "USDT", "EUR", "TRY", "BRL", "BTC", "ETH", "BNB")


def quote_currency(symbols: Sequence[str], known: dict[str, str] | None = None) -> str:
    """The single quote asset shared by ``symbols`` (the paper account currency).

    Mixing quote assets would need FX between them, which the paper book does not model.
    """
    quotes = set()
    for s in symbols:
        q = (known or {}).get(s) or next((k for k in KNOWN_QUOTES if s.endswith(k)), "")
        if not q:
            raise ValueError(f"cannot infer quote asset of {s}")
        quotes.add(q)
    if len(quotes) != 1:
        raise ValueError(f"all symbols must share one quote asset, got {sorted(quotes)}")
    return quotes.pop()


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    base_asset: str
    quote_asset: str
    step_size: float
    min_notional: float
    volume_24h: float  # base asset


def parse_symbol_info(
    exchange_info: dict[str, Any], tickers: list[dict[str, Any]]
) -> dict[str, SymbolInfo]:
    vol = {t["symbol"]: float(t.get("volume", 0.0)) for t in tickers}
    out: dict[str, SymbolInfo] = {}
    for s in exchange_info.get("symbols", []):
        filters = {f["filterType"]: f for f in s.get("filters", [])}
        step = float(filters.get("LOT_SIZE", {}).get("stepSize", 1e-8))
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        out[s["symbol"]] = SymbolInfo(
            symbol=s["symbol"],
            base_asset=s.get("baseAsset", ""),
            quote_asset=s.get("quoteAsset", ""),
            step_size=step,
            min_notional=float(notional.get("minNotional", 0.0)),
            volume_24h=vol.get(s["symbol"], 0.0),
        )
    return out


def fetch_symbol_info(
    symbols: Sequence[str], base_url: str = REST_URL, timeout: float = 10.0
) -> dict[str, SymbolInfo]:  # pragma: no cover - network
    syms = json.dumps([s.upper() for s in symbols], separators=(",", ":"))
    with httpx.Client(base_url=base_url, timeout=timeout, verify=system_ssl_context()) as c:
        info = c.get("/api/v3/exchangeInfo", params={"symbols": syms})
        info.raise_for_status()
        tick = c.get("/api/v3/ticker/24hr", params={"symbols": syms})
        tick.raise_for_status()
    return parse_symbol_info(info.json(), tick.json())


STABLECOINS = frozenset(
    {"USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EUR", "EURI", "AEUR", "USD1", "PYUSD"}
)


def rank_symbols(
    tickers: list[dict[str, Any]], quote: str = "USDC", n: int = 10, min_quote_volume: float = 0.0
) -> list[str]:
    """The ``n`` most traded ``*<quote>`` pairs by 24 h quote volume, excluding stable/fiat bases.

    A stablecoin-vs-stablecoin pair barely moves, so it can never pay the fees.
    """
    quote = quote.upper()
    rows = []
    for t in tickers:
        sym = str(t.get("symbol", ""))
        if not sym.endswith(quote) or len(sym) <= len(quote):
            continue
        if sym[: -len(quote)] in STABLECOINS:
            continue
        qv = float(t.get("quoteVolume", 0.0) or 0.0)
        if qv > min_quote_volume:
            rows.append((qv, sym))
    return [s for _, s in sorted(rows, reverse=True)[:n]]


def top_symbols(
    quote: str = "USDC", n: int = 10, base_url: str = REST_URL, timeout: float = 15.0
) -> list[str]:  # pragma: no cover - network
    with httpx.Client(base_url=base_url, timeout=timeout, verify=system_ssl_context()) as c:
        r = c.get("/api/v3/ticker/24hr", params={"type": "MINI"})
        r.raise_for_status()
    return rank_symbols(r.json(), quote, n)


def resolve_universe(spec: str) -> list[str]:  # pragma: no cover - network for "top:"
    """``"top:10"`` / ``"top:10:EUR"`` → most liquid pairs; otherwise a comma-separated list."""
    if spec.lower().startswith("top:"):
        parts = spec.split(":")
        n = int(parts[1]) if len(parts) > 1 and parts[1] else 10
        quote = parts[2].upper() if len(parts) > 2 else "USDC"
        return top_symbols(quote, n)
    return [s.strip().upper() for s in spec.split(",") if s.strip()]


def recent_klines_1m(
    symbol: str, limit: int = 1000, base_url: str = REST_URL, timeout: float = 15.0
) -> list[list[Any]]:  # pragma: no cover - network
    """Most recent *completed* 1-minute klines (the still-open minute is dropped)."""
    with httpx.Client(base_url=base_url, timeout=timeout, verify=system_ssl_context()) as c:
        r = c.get("/api/v3/klines", params={"symbol": symbol, "interval": "1m", "limit": limit})
        r.raise_for_status()
    now_ms = time.time() * 1000
    return [row for row in r.json() if int(row[6]) < now_ms]
