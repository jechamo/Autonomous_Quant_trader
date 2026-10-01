"""Research CLI.

python -m services.research.cli --symbol SPY --timeframe 1d --strategy momentum
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer
from aqt.backtest import CostModel
from aqt.common.config import load_settings
from aqt.data import (
    CsvAdapter,
    DataUnavailableError,
    MarketDataAdapter,
    ParquetStore,
    SyntheticAdapter,
    YahooAdapter,
    get_instrument,
    resolve_universe,
)
from aqt.persistence import NullStore, ResultStore, SupabaseStore
from aqt.research import (
    ResearchConfig,
    StudyConfig,
    run_research,
    run_study,
    write_report,
    write_study_report,
)
from aqt.strategies import list_strategies

app = typer.Typer(add_completion=False, help="Autonomous Quant Trader — research engine")


class Source(StrEnum):
    synthetic = "synthetic"
    parquet = "parquet"
    csv = "csv"
    yahoo = "yahoo"


def _adapter(source: Source, data_dir: str, seed: int, bars: int) -> MarketDataAdapter:
    if source is Source.synthetic:
        return SyntheticAdapter(n=bars, seed=seed)
    if source is Source.parquet:
        return ParquetStore(data_dir)
    if source is Source.yahoo:
        return YahooAdapter()
    return CsvAdapter(data_dir)


@app.command()
def run(
    symbol: str = typer.Option("SPY", help="Ticker symbol"),
    timeframe: str = typer.Option("1d", help="Bar timeframe, e.g. 1d, 1h"),
    strategy: str = typer.Option("momentum", help=f"One of: {', '.join(list_strategies())}"),
    source: Source = typer.Option(Source.synthetic, help="Market data source"),
    data_dir: str | None = typer.Option(None, help="Parquet/CSV root (defaults to DATA_DIR)"),
    start: str | None = typer.Option(None),
    end: str | None = typer.Option(None),
    bars: int = typer.Option(3000, help="Synthetic bars"),
    seed: int = typer.Option(7),
    oos_fraction: float = typer.Option(0.3),
    wf_windows: int = typer.Option(5),
    fdr_q: float = typer.Option(0.05),
    spread: float = typer.Option(0.0005, help="Full spread fraction"),
    slippage: float = typer.Option(0.0005, help="Slippage per side"),
    fee_pct: float = typer.Option(0.0, help="Commission per side"),
    fx_pct: float = typer.Option(0.0015, help="FX conversion cost per side"),
    out: str | None = typer.Option(None, help="Output directory (defaults to REPORTS_DIR)"),
) -> None:
    """Run a full, reproducible research study for one strategy family."""
    if strategy not in list_strategies():
        raise typer.BadParameter(f"unknown strategy; choose from {list_strategies()}")
    settings = load_settings()
    adapter = _adapter(source, data_dir or settings.data_dir, seed, bars)
    df = adapter.get_ohlcv(symbol, timeframe, start, end)
    cfg = ResearchConfig(
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy,
        oos_fraction=oos_fraction,
        walk_forward_windows=wf_windows,
        fdr_q=fdr_q,
        seed=seed,
        costs=CostModel(fee_pct=fee_pct, spread_pct=spread, slippage_pct=slippage, fx_pct=fx_pct),
    )
    report = run_research(df, cfg)
    json_path, md_path = write_report(report, Path(out or settings.reports_dir))
    d = report.to_dict()
    o = d["out_of_sample"]
    typer.echo(f"Strategy  : {d['selected_strategy']['name']}")
    typer.echo(
        f"OOS trades: {o['n_trades']}  EV/trade: {o['expected_value']:.4%}  p={o['p_value']:.4f}"
    )
    typer.echo(f"Edge score: {d['edge']['score']:.1f}/100")
    typer.echo(f"Verdict   : {d['verdict']['decision']}")
    typer.echo(f"Report    : {md_path}\nJSON      : {json_path}")


@app.command()
def fetch(
    universe: str = typer.Option("default", help="Named universe or comma-separated symbols"),
    timeframe: str = typer.Option("1d"),
    start: str = typer.Option("2005-01-01"),
    end: str | None = typer.Option(None),
    data_dir: str | None = typer.Option(None, help="Parquet root (defaults to DATA_DIR)"),
) -> None:
    """Download history from Yahoo Finance into the Parquet store."""
    settings = load_settings()
    store = ParquetStore(data_dir or settings.data_dir)
    source = _fetch_adapter()
    failed = []
    for symbol in resolve_universe(universe):
        try:
            df = source.get_ohlcv(symbol, timeframe, start, end)
        except DataUnavailableError as exc:
            failed.append(symbol)
            typer.echo(f"FAIL {symbol}: {exc}", err=True)
            continue
        path = store.write(symbol, timeframe, df)
        typer.echo(
            f"ok   {symbol:10s} {len(df):6d} bars {df.index[0].date()} → "
            f"{df.index[-1].date()}  {path}"
        )
    if failed:
        raise typer.Exit(code=1)


def _fetch_adapter() -> MarketDataAdapter:
    return YahooAdapter()


def _result_store(persist: bool) -> ResultStore:
    return SupabaseStore.from_env() if persist else NullStore()


@app.command()
def study(
    universe: str = typer.Option("default", help="Named universe or comma-separated symbols"),
    strategies: str = typer.Option("all", help="'all' or comma-separated strategy names"),
    timeframe: str = typer.Option("1d"),
    source: Source = typer.Option(Source.parquet, help="Where to read market data from"),
    data_dir: str | None = typer.Option(None),
    start: str | None = typer.Option(None),
    end: str | None = typer.Option(None),
    bars: int = typer.Option(3000, help="Synthetic bars"),
    fdr_q: float = typer.Option(0.05),
    mc_sims: int = typer.Option(2000),
    name: str = typer.Option("study"),
    persist: bool = typer.Option(False, help="Store results in Supabase"),
    out: str | None = typer.Option(None),
) -> None:
    """Research every symbol × strategy with study-wide FDR control."""
    settings = load_settings()
    names = list_strategies() if strategies == "all" else strategies.split(",")
    unknown = set(names) - set(list_strategies())
    if unknown:
        raise typer.BadParameter(f"unknown strategies {sorted(unknown)}")
    symbols = resolve_universe(universe)
    adapter = _adapter(source, data_dir or settings.data_dir, 7, bars)
    data = {}
    for symbol in symbols:
        try:
            data[symbol] = adapter.get_ohlcv(symbol, timeframe, start, end)
        except (FileNotFoundError, DataUnavailableError) as exc:
            typer.echo(f"skip {symbol}: {exc}", err=True)
    if not data:
        raise typer.BadParameter("no data available; run `fetch` first")
    store = _result_store(persist)
    report = run_study(
        data,
        names,
        StudyConfig(timeframe=timeframe, fdr_q=fdr_q, monte_carlo_sims=mc_sims, name=name),
    )
    json_path, md_path = write_study_report(report, Path(out or settings.reports_dir))
    meta = report.to_dict()["meta"]
    typer.echo(
        f"Pairs: {meta['n_pairs']}  Hypotheses: {meta['n_hypotheses']}  "
        f"Global discoveries: {meta['n_global_discoveries']}  "
        f"Candidates: {meta['n_candidates']}"
    )
    for pair in report.candidates:
        typer.echo(
            f"  CANDIDATE {pair.symbol} {pair.strategy} ({get_instrument(pair.symbol).currency})"
        )
    experiment_id = store.persist_study(report, symbols)
    if experiment_id:
        typer.echo(f"Supabase experiment: {experiment_id}")
    typer.echo(f"Report: {md_path}\nJSON  : {json_path}")


@app.command("list")
def list_cmd() -> None:
    """List available strategy families."""
    for name in list_strategies():
        typer.echo(name)


if __name__ == "__main__":
    app()
