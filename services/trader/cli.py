"""Streaming trader CLI (PAPER only).

uv run python -m services.trader run                      # top-10 USDC pairs + dashboard + lab
uv run python -m services.trader run --symbols BTCUSDC,ETHUSDC --research-every 0
uv run python -m services.trader research --days 7        # one Research Lab cycle now
uv run python -m services.trader simulate --hours 72      # replay real history (optionally --learn)
uv run python -m services.trader replay                   # same engine over recorded ticks
uv run python -m services.trader ticks                    # what has been recorded
"""

from __future__ import annotations

import logging
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from aqt.common.config import load_dotenv, load_settings
from aqt.stream.engine import EngineConfig, StreamingEngine
from aqt.stream.store import SQLiteStore

app = typer.Typer(add_completion=False, help="Streaming paper trader (Binance crypto / US stocks)")


@app.callback()
def _load_env() -> None:
    """Read a local .env (gitignored) so API keys never have to be typed or committed."""
    load_dotenv()


DEFAULT_DB = Path("data/stream/aqt.sqlite")
STOCKS_DB = Path("data/stream/stocks.sqlite")  # own registry: rules never mix markets
DEFAULT_SYMBOLS = "top:10"  # the 10 most traded USDC pairs (aqt.stream.binance.rank_symbols)
FALLBACK_SYMBOLS = "BTCUSDC,ETHUSDC,SOLUSDC"


def _symbols(raw: str) -> tuple[str, ...]:
    syms = tuple(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))
    if not syms:
        raise typer.BadParameter("at least one symbol")
    return syms


@dataclass(frozen=True)
class Market:
    name: str
    session: str
    fee: float  # per side
    spread_bps: float  # assumed in simulations / golden checks (live uses the real book)
    slippage: float
    db: Path
    bvc: bool  # estimate order flow from bar returns (stocks: trades carry no aggressor side)
    timeframes: tuple[str, ...] = ("1min",)  # what the Research Lab studies by default
    lab_days: float = 365.0  # history per research cycle (crypto 1-minute is capped at 7 days)


MARKETS = {
    "binance": Market(
        "binance", "24/7", 0.001, 1.0, 0.0005, DEFAULT_DB, False, ("1min", "1h", "4h")
    ),
    # Alpaca: no commission; ~0.002 % covers SEC/FINRA sell fees. IEX spreads are conservative.
    "stocks": Market("stocks", "us_equity", 0.00002, 2.0, 0.0003, STOCKS_DB, True, ("15min", "1h")),
}


def _history(m: Market, sym: str, start_ms: int, end_ms: int, timeframe: str) -> Any:
    """Research bars at ``timeframe`` from the market's own source (cached on disk)."""
    from aqt.lab.cycle import BarData
    from aqt.stream.history import load_binance_klines, load_klines_1s, resample_klines

    if m.name == "stocks":
        return BarData(_stock_loader()).bars(sym, start_ms, end_ms, timeframe)
    if timeframe == "1min":
        return resample_klines(load_klines_1s(sym, start_ms, end_ms), "1min")
    return load_binance_klines(sym, start_ms, end_ms, timeframe)


def _warmup_ms(m: Market, timeframe: str, bars: int = 300) -> int:
    """Enough calendar time for ``bars`` bars (stocks only trade ~6.5 h a day, 5 days a week)."""
    from aqt.stream.history import TIMEFRAME_SECONDS

    scale = 5.2 if m.name == "stocks" else 1.0
    return int(TIMEFRAME_SECONDS[timeframe] * bars * scale * 1000)


def _market(name: str) -> Market:
    if name not in MARKETS:
        raise typer.BadParameter(f"market must be one of {sorted(MARKETS)}")
    return MARKETS[name]


def _market_symbols(m: Market, raw: str) -> tuple[str, ...]:
    if m.name == "stocks":
        from aqt.stream.stocks import DEFAULT_STOCKS

        return _symbols(DEFAULT_STOCKS if raw == DEFAULT_SYMBOLS else raw)
    return _universe(raw)


def _stock_loader() -> Any:
    """1-minute stock bars: Alpaca (years) when keys are in .env, otherwise Yahoo (~7 days)."""
    from aqt.stream.alpaca import stock_bar_loader

    source, loader = stock_bar_loader()
    if source == "yahoo":
        typer.echo("stock history: Yahoo (~7 days of 1-minute bars; add Alpaca keys for years)")
    return loader


def _universe(raw: str) -> tuple[str, ...]:
    """``top:N[:QUOTE]`` -> most liquid pairs (network); otherwise a comma-separated list."""
    from aqt.stream.binance import resolve_universe

    try:
        return _symbols(",".join(resolve_universe(raw)))
    except typer.BadParameter:
        raise
    except Exception as exc:  # offline: fall back to a fixed liquid set
        typer.echo(f"universe {raw!r} unavailable ({exc}); using {FALLBACK_SYMBOLS}")
        return _symbols(FALLBACK_SYMBOLS)


def _refuse_live() -> bool:
    settings = load_settings()
    if settings.is_live:
        typer.echo("LIVE is not available for the streaming trader: there is no live broker.")
        raise typer.Exit(2)
    return settings.kill_switch


@app.command()
def run(
    symbols: str = typer.Option(
        DEFAULT_SYMBOLS, help="top:N[:QUOTE] or a list of symbols sharing one quote asset"
    ),
    bar_seconds: float = typer.Option(5.0, help="Bar interval in seconds"),
    cash: float = typer.Option(100.0, help="Initial paper capital (quote currency)"),
    research_every: float = typer.Option(6.0, help="Research Lab cycle every N hours (0 = off)"),
    lab_days: float | None = typer.Option(None, help="Days of history per research cycle"),
    baseline: bool = typer.Option(True, help="Also run the 5 hand-written baseline rules"),
    aggressiveness: float = typer.Option(50.0, min=0, max=100),
    fee: float | None = typer.Option(None, help="Fee per side (default: market's)"),
    latency: float = typer.Option(0.25, help="Simulated order latency (s)"),
    db: Path | None = typer.Option(None, help="SQLite file (default: one per market)"),
    record: bool = typer.Option(False, help="Record raw ticks (large with many symbols)"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
    exchange_info: bool = typer.Option(True, help="Fetch lot sizes / 24h volume via REST"),
    market: str = typer.Option("binance", help="binance (crypto, 24/7) | stocks (Alpaca, US)"),
    broker: str = typer.Option(
        "local", help="local (simulated fills) | alpaca (orders to your Alpaca PAPER account)"
    ),
) -> None:
    """Run the paper trader on live data with the local dashboard and the Research Lab."""
    import uvicorn
    from aqt.stream.binance import BinanceFeed, fetch_symbol_info, quote_currency
    from aqt.stream.dsl_strategy import ResearchBarBook

    from services.trader.app import create_app
    from services.trader.golive_monitor import GoLiveMonitor
    from services.trader.lab_scheduler import LabScheduler, subprocess_runner
    from services.trader.notify import make_notifier
    from services.trader.runtime import TraderRuntime

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise typer.BadParameter("the dashboard controls the kill switch: bind to localhost only")
    kill = _refuse_live()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    m = _market(market)
    lab_days = m.lab_days if lab_days is None else lab_days
    if broker not in ("local", "alpaca"):
        raise typer.BadParameter("broker must be local or alpaca")
    if broker == "alpaca" and m.name != "stocks":
        raise typer.BadParameter("--broker alpaca requires --market stocks")
    fee = m.fee if fee is None else fee
    db = db or m.db
    syms = _market_symbols(m, symbols)
    infos: dict[str, Any] = {}
    feed: Any
    if m.name == "stocks":
        from aqt.stream.alpaca import HOW_TO_GET_KEYS, AlpacaFeed, alpaca_credentials

        creds = alpaca_credentials()
        if creds is None:
            typer.echo(HOW_TO_GET_KEYS)
            raise typer.Exit(2)
        currency = "USD"
        feed = AlpacaFeed(syms, *creds)
    else:
        if exchange_info:
            try:
                infos = fetch_symbol_info(syms)
            except Exception as exc:  # metadata is optional; the engine estimates volume
                typer.echo(f"exchange info unavailable ({exc}); using estimates")
        missing = [s for s in syms if infos and s not in infos]
        if missing:
            raise typer.BadParameter(f"unknown Binance symbols: {missing}")
        try:
            currency = quote_currency(syms, {s: i.quote_asset for s, i in infos.items()})
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        feed = BinanceFeed(syms)
    store = SQLiteStore(db)
    # One paper account per quote currency, market and venue.
    run_id = f"live-{currency}" + ("-stocks" if m.name == "stocks" else "")
    run_id += "-alpaca" if broker == "alpaca" else ""
    realized = store.realized_pnl(run_id)
    cfg = EngineConfig(
        symbols=syms,
        bar_seconds=bar_seconds,
        initial_cash=cash + realized,
        aggressiveness=aggressiveness,
        fee_pct=fee,
        latency_s=latency,
        run_id=run_id,
        currency=currency,
        session=m.session,
        min_order_notional=1.0 if m.name == "stocks" else 5.0,
    )
    venue = _alpaca_venue(syms, cfg.initial_cash) if broker == "alpaca" else None
    engine = StreamingEngine(cfg, store=store, broker=venue)
    engine.kill_switch = kill
    _apply_exchange_info(engine, infos)
    book = ResearchBarBook(bvc=m.bvc, session=m.session)
    _seed_book(book, syms, m, 60.0)
    lab = LabScheduler(
        engine,
        store,
        book,
        subprocess_runner(str(db), list(syms), lab_days, ["--fee", str(fee), "--market", m.name]),
        every_s=research_every * 3600,
        baseline=baseline,
        seeder=lambda tf: _seed_book(book, syms, m, tf),
    )
    lab.sync()  # load the registry's active rules before the first tick
    golive = GoLiveMonitor(engine, store, make_notifier(), external_venue=broker == "alpaca")
    runtime = TraderRuntime(engine, store, feed, record=record, lab=lab, golive=golive)
    url = f"http://{host}:{port}"
    where = "orders -> Alpaca PAPER account" if broker == "alpaca" else "local simulated fills"
    typer.echo(f"PAPER trader ({m.name}, {where}) on {', '.join(syms)} - dashboard {url}")
    lab_txt = f"every {research_every:g} h on {lab_days:g} days" if research_every else "off"
    typer.echo(f"Research Lab: {lab_txt}; live rules: {len(lab.registry.active())}")
    typer.echo(
        f"paper equity: {cfg.initial_cash:.2f} {currency} (carried realized {realized:+.2f})"
    )
    gate = golive.evaluate()
    typer.echo(f"go-live gate: {gate.summary()}")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(runtime), host=host, port=port, log_level="warning")


def _alpaca_venue(syms: tuple[str, ...], capital: float) -> Any:
    """Alpaca paper broker for a capital sub-account; refuses to start next to foreign positions."""
    import httpx
    from aqt.brokers.alpaca_paper import AlpacaPaperBroker
    from aqt.stream.alpaca import HOW_TO_GET_KEYS, alpaca_credentials, alpaca_trading_url
    from aqt.stream.binance import system_ssl_context

    creds = alpaca_credentials()
    if creds is None:
        typer.echo(HOW_TO_GET_KEYS)
        raise typer.Exit(2)
    try:
        base_url = alpaca_trading_url()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    headers = {"APCA-API-KEY-ID": creds[0], "APCA-API-SECRET-KEY": creds[1]}
    with httpx.Client(base_url=base_url, headers=headers, verify=system_ssl_context()) as c:
        acct = c.get("/v2/account")
        acct.raise_for_status()
        held = [p["symbol"] for p in c.get("/v2/positions").json() if p["symbol"] in syms]
    if held:
        typer.echo(
            f"your Alpaca paper account already holds {held}: the bot only starts flat on the "
            "symbols it trades (close them in Alpaca or remove them with --symbols)"
        )
        raise typer.Exit(2)
    a = acct.json()
    typer.echo(
        f"Alpaca paper account {a.get('status')}: cash {float(a.get('cash', 0)):,.0f} USD; "
        f"the bot manages a {capital:,.0f} USD sub-account inside it (never margin)"
    )
    return AlpacaPaperBroker(creds[0], creds[1], capital=capital, base_url=base_url, symbols=syms)


def _seed_book(book: Any, syms: tuple[str, ...], m: Market, timeframe_s: float) -> None:
    """Pre-load recent bars of every symbol at one timeframe so lab rules need no warm-up."""
    import time

    from aqt.stream.binance import recent_klines_1m
    from aqt.stream.dsl_strategy import TIMEFRAME_LABELS
    from aqt.stream.history import klines_frame, resample_klines

    tf = TIMEFRAME_LABELS[timeframe_s]
    now_ms = int(time.time() * 1000)
    frames = {}
    for sym in syms:
        try:
            if m.name != "stocks" and tf == "1min":
                frames[sym] = resample_klines(klines_frame(recent_klines_1m(sym)), "1min")
            else:
                frames[sym] = _history(m, sym, now_ms - _warmup_ms(m, tf), now_ms, tf)
        except Exception as exc:  # optional: rules then warm up live
            typer.echo(f"could not pre-load {tf} history for {sym}: {exc}")
    if frames:
        book.seed_many(timeframe_s, frames)


@app.command()
def research(
    symbols: str = typer.Option(DEFAULT_SYMBOLS, help="top:N[:QUOTE] or a list of symbols"),
    days: float | None = typer.Option(None, help="Days of history (default: market's, 365)"),
    timeframes: str = typer.Option("", help="e.g. 1min,15min,1h,4h,1d (default: market's)"),
    end: str = typer.Option("", help="UTC end, e.g. 2026-09-30T00:00 (default: now)"),
    db: Path | None = typer.Option(None, help="SQLite with the rule registry (shared with run)"),
    fee: float | None = typer.Option(None, help="Fee per side (default: market's)"),
    spread_bps: float | None = typer.Option(None, help="Assumed spread in the golden check"),
    market: str = typer.Option("binance", help="binance | stocks"),
    families: str = typer.Option("", help="Comma-separated intraday families (default: all)"),
    max_active: int = typer.Option(10, help="Maximum live challenger/champion rules"),
    workers: int = typer.Option(0, help="Parallel processes (0 = CPUs - 1)"),
    review: bool = typer.Option(True, help="Also review live rules against forward evidence"),
    analyst: bool = typer.Option(
        True, help="First ask the AI Analyst for hypotheses (needs OPENAI_API_KEY)"
    ),
) -> None:
    """Run one Research Lab cycle: discover, validate and promote rules (no trading)."""
    import time
    from datetime import UTC, datetime

    from aqt.lab.cycle import BarData, LabConfig, run_research_cycle
    from aqt.lab.registry import RuleRegistry
    from aqt.lab.review import review_rules
    from aqt.risk.profile import RiskProfile
    from aqt.strategies.intraday import INTRADAY_CATALOG
    from aqt.stream.binance import quote_currency
    from aqt.stream.history import TIMEFRAME_SECONDS, load_klines_1s

    m = _market(market)
    fee = m.fee if fee is None else fee
    days = m.lab_days if days is None else days
    spread = (m.spread_bps if spread_bps is None else spread_bps) / 10_000
    tfs = tuple(t.strip() for t in timeframes.split(",") if t.strip()) or m.timeframes
    bad_tf = [t for t in tfs if t not in TIMEFRAME_SECONDS]
    if bad_tf:
        raise typer.BadParameter(f"unknown timeframes {bad_tf}; use {sorted(TIMEFRAME_SECONDS)}")
    syms = _market_symbols(m, symbols)
    data: Any
    if m.name == "stocks":
        quote, data = "USD", BarData(_stock_loader(), spread)
    else:
        data = load_klines_1s
        try:
            quote = quote_currency(syms)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    fams = tuple(f.strip() for f in families.split(",") if f.strip()) or tuple(INTRADAY_CATALOG)
    unknown = [f for f in fams if f not in INTRADAY_CATALOG]
    if unknown:
        raise typer.BadParameter(f"unknown families {unknown}; see {sorted(INTRADAY_CATALOG)}")
    kw: dict[str, Any] = {"workers": workers} if workers > 0 else {}
    cfg = LabConfig(
        symbols=syms,
        quote=quote,
        days=days,
        fee_pct=fee,
        spread_pct=spread,
        slippage_pct=m.slippage,
        session=m.session,
        families=fams,
        timeframes=tfs,
        max_active=max_active,
        **kw,
    )
    end_ms = None
    if end:
        end_ms = int(datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp() * 1000)
    store = SQLiteStore(db or m.db)
    if analyst:
        _run_analyst(store, m, tfs)
    typer.echo(
        f"research ({m.name}): {len(syms)} symbols, timeframes {', '.join(tfs)}, "
        f"{days:g} days, {cfg.workers} workers..."
    )
    t0 = time.monotonic()
    result = run_research_cycle(store, cfg, data, end_ms=end_ms)
    if result.error:
        typer.echo(f"research cycle #{result.run_id} failed: {result.error}")
        raise typer.Exit(1)
    s = result.summary
    typer.echo(
        f"\ncycle #{result.run_id} ({time.monotonic() - t0:.0f} s): {s['n_hypotheses']} "
        f"hypotheses, {s['n_global_discoveries']} survive global FDR, "
        f"{s['n_candidates']} candidates, promoted {len(result.promoted)}"
    )
    by_tf = ", ".join(f"{k} {v}" for k, v in s.get("hypotheses_by_timeframe", {}).items())
    typer.echo(f"hypotheses by timeframe: {by_tf or '-'}")
    for g in s["golden"]:
        verdict = "PASS" if g["passed"] else "fail"
        typer.echo(
            f"  golden {g['rule_id']}: {g['n_trades']} trades, "
            f"EV {g['mean_net_return']:+.3%} -> {verdict}"
        )
    fails = ", ".join(f"{k} {v}" for k, v in s["failed_checks"].items())
    typer.echo(f"failed checks: {fails or '-'}")
    typer.echo("best out-of-sample pairs:")
    for row in s["top_pairs"][:5]:
        ev = row.get("oos_ev") or 0.0
        typer.echo(
            f"  {row['symbol']:<12}{row.get('timeframe', ''):<7}{row['strategy']:<22}"
            f"OOS EV {ev:+.3%}  trades {row.get('oos_trades') or 0:<4} {row['decision']}"
        )
    if review:
        live_id = f"live-{quote}" + ("-stocks" if m.name == "stocks" else "")
        for c in review_rules(store, live_id, RiskProfile.from_aggressiveness(50)):
            typer.echo(f"  review: {c['rule_id']} -> {c['status']} ({c['reason']})")
    active = RuleRegistry(store).active()
    typer.echo(f"live rules now: {len(active)}")
    for r in active:
        typer.echo(f"  [{r.status}] {r.rule_id}")
    store.close()


def _families() -> dict[str, str]:
    from aqt.strategies.intraday import INTRADAY_CATALOG
    from aqt.strategies.swing import SWING_CATALOG

    return {n: s.description for n, (s, _) in {**INTRADAY_CATALOG, **SWING_CATALOG}.items()}


def _run_analyst(store: SQLiteStore, m: Market, tfs: tuple[str, ...]) -> None:
    """Ask the AI Analyst for new hypotheses; the next research cycle will examine them."""
    from aqt.analyst.client import OpenAIClient, analyst_config_from_env
    from aqt.analyst.hypotheses import run_analyst

    cfg = analyst_config_from_env()
    if cfg is None:
        typer.echo("AI Analyst: off (set OPENAI_API_KEY in .env)")
        return
    typer.echo(f"AI Analyst ({cfg.model}): reading the lab's results...")
    res = run_analyst(store, OpenAIClient(cfg), cfg, m.name, tfs, _families(), m.session)
    if res.skipped:
        typer.echo(f"AI Analyst skipped: {res.skipped}")
        return
    tokens = res.usage.get("total_tokens", "?")
    typer.echo(f"AI Analyst: {len(res.created)} hypotheses accepted, {len(res.rejected)} invalid "
               f"({tokens} tokens)")  # fmt: skip
    for h in res.created:
        typer.echo(f"  + {h.name} [{h.timeframe}] {h.claim[:110]}")
    for name, why in res.rejected:
        typer.echo(f"  - {name or '?'}: {why[:110]}")


@app.command()
def analyst(
    market: str = typer.Option("binance", help="binance | stocks"),
    db: Path | None = typer.Option(None, help="SQLite with the lab's memory"),
    timeframes: str = typer.Option("", help="Allowed timeframes (default: market's)"),
    dry_run: bool = typer.Option(False, help="Show what the analyst would read; no API call"),
) -> None:
    """Ask the AI Analyst for hypotheses now (tested by the next research cycle)."""
    import json

    from aqt.analyst.hypotheses import HypothesisStore, available_features, build_context

    m = _market(market)
    tfs = tuple(t.strip() for t in timeframes.split(",") if t.strip()) or m.timeframes
    store = SQLiteStore(db or m.db)
    if dry_run:
        ctx = build_context(
            store, m.name, tfs, _families(), available_features(m.session), HypothesisStore(store)
        )
        typer.echo(json.dumps(ctx, indent=2, default=str, ensure_ascii=False)[:6000])
        return
    _run_analyst(store, m, tfs)


@app.command()
def replay(
    db: Path = typer.Option(DEFAULT_DB, help="SQLite file with recorded ticks"),
    symbols: str = typer.Option("", help="Subset of symbols (default: all recorded)"),
    bar_seconds: float = typer.Option(5.0),
    cash: float = typer.Option(100.0),
    aggressiveness: float = typer.Option(50.0, min=0, max=100),
    fee: float = typer.Option(0.001),
    latency: float = typer.Option(0.25),
    out: Path | None = typer.Option(None, help="Write the replay audit trail to this SQLite"),
) -> None:
    """Run the exact live engine over recorded ticks (deterministic backtest)."""
    src = SQLiteStore(db)
    recorded = sorted({r["symbol"] for r in src.tick_summary()})
    syms = _symbols(symbols) if symbols else tuple(recorded)
    if not syms:
        typer.echo(f"no ticks recorded in {db}; run `run` first (it records by default)")
        raise typer.Exit(1)
    sink = SQLiteStore(out) if out else None
    cfg = EngineConfig(
        symbols=syms,
        bar_seconds=bar_seconds,
        initial_cash=cash,
        aggressiveness=aggressiveness,
        fee_pct=fee,
        latency_s=latency,
        run_id="replay",
    )
    engine = StreamingEngine(cfg, store=sink)
    for event in src.iter_ticks(syms):
        engine.on_event(event)
    engine.shutdown()
    if sink:
        sink.close()
    _print_summary(engine)


def _print_summary(engine: StreamingEngine) -> None:
    snap = engine.snapshot()
    acc = snap["account"]
    ccy = engine.cfg.currency
    hours = (engine.now - engine.first_ts) / 3600 if engine.first_ts is not None else 0.0
    typer.echo(f"\n{engine.events:,} events · {hours:.1f} h · {', '.join(engine.symbols)}")
    typer.echo("\nShadow evidence (every signal, net of fees/spread/latency; BH-FDR adjusted):")
    typer.echo(
        f"{'strategy':<18}{'signals':>8}{'blocked':>8}{'n':>6}{'win%':>7}{'EV net':>9}"
        f"{'p adj':>7}{'edge':>6}  trades?"
    )
    for s in snap["strategies"]:
        typer.echo(
            f"{s['strategy_id']:<18}{s['signals']:>8}{s['cost_blocked']:>8}{s['n_trades']:>6}"
            f"{s['win_rate']:>7.1%}{s['mean_net_return']:>9.3%}{s['adjusted_p_value']:>7.3f}"
            f"{s['edge_score']:>6.1f}  {'YES' if s['eligible'] else 'no'}"
        )
    c = snap["counters"]
    recent = engine.paper_trades()
    wins = sum(1 for t in recent if t.pnl > 0)
    curve = [v for _, v, _ in engine.equity_history] or [acc["equity"]]
    peak, max_dd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    start, eq, bh = acc["initial"], acc["equity"], acc["buy_hold_equity"]
    typer.echo(
        f"\nPaper book: {c['paper_trades']} trades"
        + (f" (win {wins / len(recent):.0%})" if recent else "")
        + f" · signals {c['signals']} · approved {c['approved']} · rejected {c['rejected']}"
        f" · throttled {c['throttled']} · blocked by costs {c['cost_blocked']}"
    )
    typer.echo(
        f"Portfolio  {eq:,.2f} {ccy} ({eq / start - 1:+.2%}) · realized {acc['realized_pnl']:+,.2f}"
        f" · fees {acc['fees_paid']:,.2f} · max drawdown {max_dd:.2%}"
    )
    typer.echo(f"Buy & Hold {bh:,.2f} {ccy} ({bh / start - 1:+.2%})  <- doing nothing clever")


def _apply_exchange_info(engine: StreamingEngine, infos: dict[str, Any]) -> None:
    for sym, info in infos.items():
        if sym in engine.symbols:
            engine.set_quantity_step(sym, info.step_size)
            engine.set_adv(sym, info.volume_24h)
            engine.broker.min_notional = max(engine.broker.min_notional, info.min_notional)


@app.command()
def simulate(
    symbols: str = typer.Option(DEFAULT_SYMBOLS, help="top:N[:QUOTE] or a list of symbols"),
    hours: float = typer.Option(72.0, help="Hours of history to simulate"),
    end: str = typer.Option("", help="UTC end, e.g. 2026-09-30T00:00 (default: now)"),
    cash: float = typer.Option(10_000.0, help="Initial capital"),
    speed: float = typer.Option(300.0, help="x real time in the dashboard (0 = maximum)"),
    headless: bool = typer.Option(False, help="No dashboard: run at full speed and summarise"),
    learn: bool = typer.Option(False, help="Run the Research Lab inside the simulation"),
    lab_days: float | None = typer.Option(None, help="Days of history per research cycle"),
    timeframes: str = typer.Option("", help="Lab timeframes, e.g. 1min,1h (default: market's)"),
    research_every: float = typer.Option(24.0, help="Research every N simulated hours"),
    workers: int = typer.Option(0, help="Research processes (0 = CPUs - 1)"),
    families: str = typer.Option("", help="Intraday families for --learn (default: all)"),
    bar_seconds: float = typer.Option(5.0),
    aggressiveness: float = typer.Option(50.0, min=0, max=100),
    fee: float | None = typer.Option(None, help="Fee per side (default: market's)"),
    latency: float = typer.Option(0.25, help="Simulated order latency (s)"),
    spread_bps: float | None = typer.Option(None, help="Assumed spread (historical book unknown)"),
    db: Path | None = typer.Option(None, help="SQLite (default: a fresh file per simulation)"),
    market: str = typer.Option("binance", help="binance (1-s klines) | stocks (Yahoo 1-min bars)"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Simulate the bot on real Binance history (1-second klines), optionally learning as it goes.

    With ``--learn`` the lab first researches the ``lab_days`` *before* the simulated period,
    then re-researches every ``research_every`` simulated hours using only data up to that
    moment, reviews rules against their forward results and hot-swaps them — the live loop,
    replayed without look-ahead. Each simulation gets its own database so rules learned in one
    simulation can never leak into another one that starts earlier.
    """
    import time
    from datetime import UTC, datetime

    from aqt.features.engine import FeatureEngine
    from aqt.lab.cycle import BarData, LabConfig, run_research_cycle
    from aqt.lab.learning import learn_meta_filters
    from aqt.lab.live import sync_engine_rules
    from aqt.lab.registry import RuleRegistry
    from aqt.lab.review import review_rules
    from aqt.stream.binance import fetch_symbol_info, quote_currency
    from aqt.stream.dsl_strategy import ResearchBarBook
    from aqt.stream.history import (
        HistoricalFeed,
        kline_events,
        load_klines_1s,
        merge_events,
    )
    from aqt.stream.stocks import bar_events

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise typer.BadParameter("the dashboard controls the kill switch: bind to localhost only")
    _refuse_live()
    m = _market(market)
    lab_days = m.lab_days if lab_days is None else lab_days
    fee = m.fee if fee is None else fee
    spread = (m.spread_bps if spread_bps is None else spread_bps) / 10_000
    syms = _market_symbols(m, symbols)
    if m.name == "stocks":
        currency = "USD"
    else:
        try:
            currency = quote_currency(syms)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    end_dt = datetime.fromisoformat(end).replace(tzinfo=UTC) if end else datetime.now(UTC)
    end_ms = int(end_dt.timestamp() * 1000) // 1000 * 1000
    start_ms = end_ms - int(hours * 3_600_000)
    start_ts = start_ms / 1000

    frames = {}
    for sym in syms:
        kind = "1-minute bars" if m.name == "stocks" else "1-second klines"
        typer.echo(f"loading {hours:g} h of {kind} for {sym}...")
        frames[sym] = (_stock_loader() if m.name == "stocks" else load_klines_1s)(
            sym, start_ms, end_ms
        )
        if frames[sym].empty:
            raise typer.BadParameter(f"no history for {sym} in that period")
    if m.name == "stocks":
        events = merge_events([bar_events(frames[s], s, spread) for s in syms])
    else:
        events = merge_events([kline_events(frames[s], s, spread) for s in syms])

    run_id = f"sim-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    store = SQLiteStore(db or Path("data/stream/sims") / f"{run_id}.sqlite")
    cfg = EngineConfig(
        symbols=syms,
        bar_seconds=bar_seconds,
        initial_cash=cash,
        aggressiveness=aggressiveness,
        fee_pct=fee,
        latency_s=latency,
        run_id=run_id,
        currency=currency,
        equity_every_seconds=max(5.0, hours * 3600 / 4000),
        session=m.session,
        min_order_notional=1.0 if m.name == "stocks" else 5.0,
    )
    engine = StreamingEngine(cfg, store=store)
    if m.name != "stocks":
        try:
            _apply_exchange_info(engine, fetch_symbol_info(syms))
        except Exception as exc:  # optional metadata
            typer.echo(f"exchange info unavailable ({exc}); using defaults")
    start_dt = datetime.fromtimestamp(start_ts, UTC)
    span = f"{start_dt:%Y-%m-%d %H:%M} -> {end_dt:%Y-%m-%d %H:%M} UTC"
    typer.echo(f"simulation {run_id}: {span}, {cash:,.0f} {currency}, fees {fee:.3%}/side")

    def sim_now() -> float:
        return engine.now or start_ts

    book = ResearchBarBook(bvc=m.bvc, session=m.session)
    registry = RuleRegistry(store, sim_now)
    lab_extra: dict[str, Any] = {"workers": workers} if workers > 0 else {}
    fams = tuple(f.strip() for f in families.split(",") if f.strip())
    if fams:
        lab_extra["families"] = fams
    lab_cfg = LabConfig(
        symbols=syms,
        quote=currency,
        days=lab_days,
        fee_pct=fee,
        spread_pct=spread,
        slippage_pct=m.slippage,
        session=m.session,
        timeframes=tuple(t.strip() for t in timeframes.split(",") if t.strip()) or m.timeframes,
        **lab_extra,
    )
    lab_data: Any = BarData(_stock_loader(), spread) if m.name == "stocks" else load_klines_1s

    def research(end_ts: float) -> str:
        t0 = time.monotonic()
        res = run_research_cycle(store, lab_cfg, lab_data, int(end_ts * 1000), sim_now)
        when = datetime.fromtimestamp(end_ts, UTC).strftime("%m-%d %H:%M")
        s = res.summary
        typer.echo(
            f"  [{when}] research #{res.run_id}: {s.get('n_hypotheses', 0)} hypotheses, "
            f"{s.get('n_candidates', 0)} candidates, promoted {len(res.promoted)} "
            f"({time.monotonic() - t0:.0f} s){' ERROR ' + res.error if res.error else ''}"
        )
        return res.error

    def review_and_sync() -> None:
        stamp = f"{datetime.fromtimestamp(sim_now(), UTC):%m-%d %H:%M}"
        for c in review_rules(
            store, run_id, engine.profile, engine.evidence.table(), clock=sim_now
        ):
            typer.echo(f"  [{stamp}] {c['rule_id']} -> {c['status']}: {c['reason']}")
        ids = [s.strategy_id for s in engine.strategies]
        for x in learn_meta_filters(store, run_id, registry, ids):
            verdict = f"learned filter {x['rule_id']}" if x["accepted"] else x["reason"]
            typer.echo(f"  [{stamp}] meta-learning {x['strategy_id']}: {verdict}")
        sync_engine_rules(engine, registry, book)

    if learn:
        typer.echo(f"initial research on the {lab_days:g} days before the simulation...")
        research(start_ts)
        # Causal (lagged cross-sectional) research features over [start - warm-up, end] for every
        # timeframe the lab studies: its rules are warm from the first bar, without look-ahead.
        from aqt.features.cross_section import augment
        from aqt.stream.history import TIMEFRAME_SECONDS

        for tf in lab_cfg.all_timeframes:
            warm_ms = 86_400_000 if tf == "1min" and m.name != "stocks" else _warmup_ms(m, tf)
            frames = {sym: _history(m, sym, start_ms - warm_ms, end_ms, tf) for sym in syms}
            frames = {k: v for k, v in frames.items() if not v.empty}
            tf_s = float(TIMEFRAME_SECONDS[tf])
            for sym, aug in augment(frames, tf_s, m.session).items():
                book.preload(sym, tf_s, FeatureEngine().compute(aug))
        sync_engine_rules(engine, registry, book)
        typer.echo(f"live rules at start: {len(registry.active())}")

    if headless:
        t0 = time.monotonic()
        every = research_every * 3600
        next_research, next_review = start_ts + every, start_ts + 3600
        for event in events:
            engine.on_event(event)
            if learn and engine.now >= next_research:
                research(engine.now)
                review_and_sync()
                next_research = engine.now + every  # a weekend gap must not trigger twice
                next_review = engine.now + 3600
            elif learn and engine.now >= next_review:
                review_and_sync()
                next_review += 3600
        engine.shutdown()
        _print_summary(engine)
        if learn:
            _print_lab_summary(registry)
        store.close()
        typer.echo(f"\n({time.monotonic() - t0:.0f} s of compute) database: {store.path}")
        return

    import asyncio

    import uvicorn

    from services.trader.app import create_app
    from services.trader.lab_scheduler import LabScheduler
    from services.trader.runtime import TraderRuntime

    feed = HistoricalFeed(events, start_ts, end_ms / 1000, speed)
    lab = None
    if learn:

        async def runner(end_ts: float) -> str:
            return await asyncio.to_thread(research, end_ts)

        lab = LabScheduler(
            engine, store, book, runner, every_s=research_every * 3600, clock=feed.now,
            poll_s=0.5, on_pause=feed.pause,
        )  # fmt: skip
    runtime = TraderRuntime(
        engine, store, feed, record=False, clock=feed.now, persist_controls=False, lab=lab
    )
    url = f"http://{host}:{port}"
    typer.echo(f"dashboard {url} - speed x{speed:g} (change it from the dashboard)")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(runtime), host=host, port=port, log_level="warning")


def _print_lab_summary(registry: Any) -> None:
    rules = registry.rules()
    typer.echo(f"\nResearch Lab: {len(registry.runs(1000))} cycles, {len(rules)} rules discovered")
    for r in rules:
        fwd = r.metrics.get("forward", {})
        typer.echo(
            f"  [{r.status:<10}] {r.rule_id:<36} research EV "
            f"{(r.metrics.get('research', {}).get('oos_ev') or 0):+.3%} | forward "
            f"{fwd.get('n_trades', 0)} trades {fwd.get('mean_net_return', 0):+.3%}"
        )
    for lesson in registry.lessons(8)[::-1]:
        typer.echo(f"  lesson ({lesson['kind']}): {lesson['text']}")


@app.command()
def ticks(db: Path = typer.Option(DEFAULT_DB)) -> None:
    """Summarise recorded ticks."""
    rows = SQLiteStore(db).tick_summary()
    if not rows:
        typer.echo("no ticks recorded")
    for r in rows:
        dur = (r["last"] - r["first"]) / 3600
        typer.echo(f"{r['symbol']:<10}{r['kind']:>3}{r['n']:>12,}  {dur:.2f} h")


if __name__ == "__main__":  # pragma: no cover
    app()
