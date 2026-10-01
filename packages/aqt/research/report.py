"""Reproducible JSON + Markdown research reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aqt.research.pipeline import ResearchReport


def _pct(x: Any) -> str:
    return "n/a" if x is None else f"{x:.2%}"


def _num(x: Any, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def render_markdown(report: ResearchReport) -> str:
    d = report.to_dict()
    s, o, i = d["selected_strategy"], d["out_of_sample"], d["in_sample"]
    mt, c, wf, mc, e, v = (
        d["multiple_testing"],
        d["cost_analysis"],
        d["walk_forward"],
        d["monte_carlo"],
        d["edge"],
        d["verdict"],
    )
    lines = [
        f"# Research report — {d['config']['symbol']} {d['config']['timeframe']} "
        f"`{d['config']['strategy']}`",
        "",
        f"**Verdict: {v['decision']}**"
        + (f" — failed: {', '.join(v['failed'])}" if v["failed"] else ""),
        "",
        f"- Generated: {d['meta']['generated_at']} · aqt {d['meta']['aqt_version']}",
        f"- Data: {d['meta']['n_bars']} bars, {d['meta']['data_start']} → {d['meta']['data_end']}"
        f" · hash `{d['meta']['data_hash']}`",
        f"- Selected: `{s['name']}` · config hash `{s['config_hash']}`",
        "",
        "## Multiple-hypothesis control",
        f"{mt['n_hypotheses']} variants tested, {mt['n_discoveries']} survive BH-FDR "
        f"(q={mt['q']}). Selected raw p={_num(mt['selected_raw_p'], 4)}, "
        f"adjusted p={_num(mt['selected_adjusted_p'], 4)}.",
        "",
        "## In-sample vs out-of-sample",
        "| Metric | In-sample | Out-of-sample |",
        "|---|---|---|",
        f"| Trades | {i['n_trades']} | {o['n_trades']} |",
        f"| Win rate | {_pct(i['win_rate'])} | {_pct(o['win_rate'])} |",
        f"| Avg win | {_pct(i['avg_win'])} | {_pct(o['avg_win'])} |",
        f"| Avg loss | {_pct(i['avg_loss'])} | {_pct(o['avg_loss'])} |",
        f"| EV / trade (net) | {_pct(i['expected_value'])} | {_pct(o['expected_value'])} |",
        f"| Profit factor | {_num(i['profit_factor'], 2)} | {_num(o['profit_factor'], 2)} |",
        f"| Max drawdown | {_pct(i['max_drawdown'])} | {_pct(o['max_drawdown'])} |",
        f"| Sharpe | {_num(i['sharpe'], 2)} | {_num(o['sharpe'], 2)} |",
        f"| Sortino | {_num(i['sortino'], 2)} | {_num(o['sortino'], 2)} |",
        "",
        f"OOS win-rate 95% CI (Wilson): {_pct(o['win_rate_ci95'][0])}–{_pct(o['win_rate_ci95'][1])}"
        f" · Bayesian P(win) {_pct(o['bayes_p_win'])} "
        f"(95% credible {_pct(o['bayes_p_win_credible95'][0])}–"
        f"{_pct(o['bayes_p_win_credible95'][1])})",
        f"OOS EV 95% CI: {_pct(o['ev_ci95'][0])} to {_pct(o['ev_ci95'][1])} · "
        f"p(EV>0)={_num(o['p_value'], 4)}",
        "",
        "## Cost awareness",
        f"Gross EV {_pct(c['gross_ev'])} − costs {_pct(c['cost_per_trade'])} = "
        f"**net EV {_pct(c['net_ev'])}** over {c['n_trades']} trades "
        f"(round trip ≈ {_pct(d['config']['round_trip_cost_pct'])}).",
        "",
        "## Walk-forward",
        f"{len(wf['windows'])} windows, {wf['oos_trades']} OOS trades, "
        f"OOS EV {_pct(wf['oos_ev'])}, efficiency {_num(wf['efficiency'], 2)}.",
        "",
        "| Test window | Selected | IS EV | OOS EV | OOS trades |",
        "|---|---|---|---|---|",
        *[
            f"| {w['test_start'][:10]} → {w['test_end'][:10]} | `{w['selected']}` | "
            f"{_pct(w['is_ev'])} | {_pct(w['oos_ev'])} | {w['oos_trades']} |"
            for w in wf["windows"]
        ],
        "",
        "## Monte Carlo",
        f"{mc['n_simulations']} bootstrap resamples of walk-forward OOS trades at 100% "
        "exposure per trade (stress view, before position sizing): final return p5/p50/p95 = "
        f"{_pct(mc['final_return_p5'])} / {_pct(mc['final_return_p50'])} / "
        f"{_pct(mc['final_return_p95'])}; median MDD {_pct(mc['max_drawdown_p50'])}, "
        f"worst-5% MDD {_pct(mc['max_drawdown_p95'])}; "
        f"P(loss)={_pct(mc['prob_loss'])}, "
        f"P(MDD<{_pct(mc['drawdown_threshold'])})={_pct(mc['prob_drawdown_exceeds'])}.",
        "",
        "## Regimes",
        f"Current regime: `{d['regimes']['current']}` · compatibility "
        f"{_num(d['regimes']['compatibility'], 2)}",
        "",
        "| Regime | Trades | Win rate | EV |",
        "|---|---|---|---|",
        *[
            f"| {k} | {r['n_trades']} | {_pct(r['win_rate'])} | {_pct(r['expected_value'])} |"
            for k, r in d["regimes"]["by_regime"].items()
        ],
        "",
        "## Parameter stability",
        f"{d['parameter_stability']['n_variants']} variants · "
        f"{_pct(d['parameter_stability']['fraction_positive'])} with positive IS EV · "
        f"stability score {_num(d['parameter_stability']['stability_score'], 2)}",
        "",
        "## Edge Score",
        f"**{_num(e['score'], 1)} / 100** — P(win) {_pct(e['p_win'])}, "
        f"EV {_pct(e['expected_value'])}, "
        f"confidence {_num(e['confidence'], 3)}, regime compatibility "
        f"{_num(e['regime_compatibility'], 2)}, P(EV>0) {_pct(e['prob_positive_ev'])}.",
        "",
        "## Verdict checks",
        *[f"- [{'x' if ok else ' '}] {k}" for k, ok in v["checks"].items()],
        "",
        f"_{v['note']}_",
        "",
    ]
    return "\n".join(lines)


def write_report(report: ResearchReport, out_dir: str | Path) -> tuple[Path, Path]:
    d = report.to_dict()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = d["config"]
    chash = d["selected_strategy"]["config_hash"]
    stem = f"{cfg['symbol']}_{cfg['timeframe']}_{cfg['strategy']}_{chash}"
    json_path = out / f"{stem}.json"
    md_path = out / f"{stem}.md"
    json_path.write_text(json.dumps(d, indent=2, sort_keys=True, default=str))
    md_path.write_text(render_markdown(report))
    return json_path, md_path
