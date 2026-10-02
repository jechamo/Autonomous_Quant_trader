"""Swing hypothesis catalog: hours-to-days horizons, long-only, built on documented anomalies.

Same format as the other catalogs (``name -> (StrategySpec, grid)``), researched on 1h/4h/1d bars
with the cross-sectional features of ``aqt.features.cross_section``:

* cross-sectional momentum — buy what ranks top of the universe over 20/60 bars
  (Jegadeesh & Titman; time-series/cross-sectional momentum literature);
* short-term reversal — buy last week's losers inside a long-term uptrend;
* relative strength with market breadth — leaders when most of the market is rising;
* trend following — moving-average trend with an ATR stop;
* breakout on volume — a 20-bar high confirmed by unusual volume;
* breadth dip — buy an oversold leader during a market-wide sell-off;
* short-term reversal on a single symbol — N lower closes in a row, RSI(2) or a close at the
  bottom of the bar's range (IBS), always inside a long-term uptrend (Jegadeesh 1990; Lehmann
  1990; Connors & Alvarez 2009; Pagonidis 2013);
* classic candlestick reversals (engulfing, hammer) with context — measured on purpose even if
  the evidence after costs is weak (Marshall, Young & Rose 2006);
* 52-week-high anchoring — daily only (George & Hwang 2004);
* turn of the month — daily US stocks only (Ariel 1987; Lakonishok & Smidt 1988);
* news (US stocks with a news source): big moves *with* abnormal news drift, big drops *without*
  news revert (Chan 2003); earnings headline + gap up + volume drifts (Bernard & Thomas 1989).

Holding periods are long enough for costs to be a small fraction of the expected move, which is
precisely where the minute-scale catalog failed. Why each rule is here, and which were left out
(IPO patterns among them), is argued in ``docs/estudio-reglas.md``.
"""

from __future__ import annotations

from collections.abc import Iterable

from aqt.strategies.dsl import Condition, ExitRules, Rule, Scalar, StrategySpec

C = Condition
Grid = dict[str, list[float | int]]


def _exit(
    stop: Scalar = "$stop",
    hold: Scalar = "$hold",
    signal: Rule | None = None,
    target: Scalar | None = None,
) -> ExitRules:
    return ExitRules(
        stop_atr_mult=stop, target_atr_mult=target, max_holding_bars=hold, exit_signal=signal
    )


SWING_CATALOG: dict[str, tuple[StrategySpec, Grid]] = {
    "xs_momentum": (
        StrategySpec(
            name="xs_momentum",
            family="xs_momentum",
            description="Top of the universe by 20-bar return, above its 50-bar EMA.",
            entry=Rule(
                all_of=[
                    C(left="xs_rank_ret_20", op=">", right="$rank"),
                    C(left="close", op=">", right="ema_50"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="xs_rank_ret_20", op="<", right=0.5)])),
            params={"rank": 0.8, "stop": 3.0, "hold": 20},
        ),
        {"rank": [0.7, 0.85], "stop": [2.0, 3.0], "hold": [10, 40]},
    ),
    "xs_momentum_long": (
        StrategySpec(
            name="xs_momentum_long",
            family="xs_momentum",
            description="Top of the universe by 60-bar return in an established uptrend.",
            entry=Rule(
                all_of=[
                    C(left="xs_rank_ret_60", op=">", right="$rank"),
                    C(left="ema_50", op=">", right="ema_200"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="xs_rank_ret_60", op="<", right=0.5)])),
            params={"rank": 0.8, "stop": 3.0, "hold": 40},
        ),
        {"rank": [0.7, 0.85], "stop": [2.5, 4.0], "hold": [20, 80]},
    ),
    "xs_reversal": (
        StrategySpec(
            name="xs_reversal",
            family="xs_reversal",
            description="Bottom of the universe by 5-bar return, still above its 200-bar EMA.",
            entry=Rule(
                all_of=[
                    C(left="xs_rank_ret_5", op="<", right="$rank"),
                    C(left="close", op=">", right="ema_200"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="xs_rank_ret_5", op=">", right=0.6)])),
            params={"rank": 0.15, "stop": 3.0, "hold": 10},
        ),
        {"rank": [0.1, 0.25], "stop": [2.0, 3.0], "hold": [5, 15]},
    ),
    "relative_strength": (
        StrategySpec(
            name="relative_strength",
            family="relative_strength",
            description="Beats the universe median over 20 bars while most of the market rises.",
            entry=Rule(
                all_of=[
                    C(left="xs_rel_ret_20", op=">", right="$rel"),
                    C(left="xs_breadth", op=">", right="$breadth"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="xs_rel_ret_20", op="<", right=0.0)])),
            params={"rel": 0.02, "breadth": 0.6, "stop": 3.0, "hold": 40},
        ),
        {"rel": [0.01, 0.03], "breadth": [0.5, 0.7], "stop": [2.0, 3.0], "hold": [20, 60]},
    ),
    "trend_follow": (
        StrategySpec(
            name="trend_follow",
            family="trend_following",
            description="EMA-50 above EMA-200, price above EMA-50 and positive 20-bar momentum.",
            entry=Rule(
                all_of=[
                    C(left="ema_50", op=">", right="ema_200"),
                    C(left="close", op=">", right="ema_50"),
                    C(left="momentum_20", op=">", right="$mom"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="close", op="<", right="ema_50")])),
            params={"mom": 0.0, "stop": 3.0, "hold": 100},
        ),
        {"mom": [0.0, 0.02], "stop": [2.0, 3.5], "hold": [50, 150]},
    ),
    "breakout_volume": (
        StrategySpec(
            name="breakout_volume",
            family="breakout",
            description="New 20-bar high on unusual volume.",
            entry=Rule(
                all_of=[
                    C(left="close", op=">", right="prev_high_20"),
                    C(left="volume_ratio", op=">", right="$vr"),
                ]
            ),
            exit=_exit(target="$target"),
            params={"vr": 2.0, "stop": 2.0, "target": 6.0, "hold": 40},
        ),
        {"vr": [1.5, 2.5], "stop": [1.5, 3.0], "target": [4.0, 8.0], "hold": [20, 60]},
    ),
    "breadth_dip": (
        StrategySpec(
            name="breadth_dip",
            family="mean_reversion",
            description="Oversold symbol in a long uptrend during a market-wide sell-off.",
            entry=Rule(
                all_of=[
                    C(left="xs_breadth", op="<", right="$breadth"),
                    C(left="close", op=">", right="ema_200"),
                    C(left="rsi", op="<", right=35),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="rsi", op=">", right=55)])),
            params={"breadth": 0.35, "stop": 3.0, "hold": 20},
        ),
        {"breadth": [0.3, 0.4], "stop": [2.5, 4.0], "hold": [10, 40]},
    ),
    "streak_reversion": (
        StrategySpec(
            name="streak_reversion",
            family="short_term_reversal",
            description="N lower closes in a row inside a long-term uptrend; out on RSI(2) > 70.",
            entry=Rule(
                all_of=[
                    C(left="down_streak", op=">=", right="$n"),
                    C(left="close", op=">", right="sma_200"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="rsi_2", op=">", right=70)])),
            params={"n": 3, "stop": 2.5, "hold": 5},
        ),
        {"n": [2, 3, 4], "hold": [3, 6]},
    ),
    "rsi2_reversion": (
        StrategySpec(
            name="rsi2_reversion",
            family="short_term_reversal",
            description="RSI(2) deeply oversold above the 200-bar SMA; out on RSI(2) > 70.",
            entry=Rule(
                all_of=[
                    C(left="rsi_2", op="<", right="$th"),
                    C(left="close", op=">", right="sma_200"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="rsi_2", op=">", right=70)])),
            params={"th": 10, "stop": 2.5, "hold": 5},
        ),
        {"th": [5, 10, 15]},
    ),
    "ibs_reversion": (
        StrategySpec(
            name="ibs_reversion",
            family="short_term_reversal",
            description="Close at the bottom of the bar's range (low IBS) in a long-term uptrend.",
            entry=Rule(
                all_of=[
                    C(left="close_position", op="<", right="$ibs"),
                    C(left="close", op=">", right="sma_200"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="close_position", op=">", right=0.7)])),
            params={"ibs": 0.2, "stop": 2.5, "hold": 3},
        ),
        {"ibs": [0.1, 0.2], "hold": [1, 3]},
    ),
    "candle_reversal": (
        StrategySpec(
            name="candle_reversal",
            family="candlestick_patterns",
            description="Bullish engulfing or hammer, oversold, above the 200-bar EMA.",
            entry=Rule(
                all_of=[
                    C(left="rsi", op="<", right="$rsi"),
                    C(left="close", op=">", right="ema_200"),
                ],
                any_of=[
                    C(left="pat_bullish_engulfing", op="==", right=1),
                    C(left="pat_hammer", op="==", right=1),
                ],
            ),
            exit=_exit(stop=2.0, hold=10, target=3.0),
            params={"rsi": 40},
        ),
        {"rsi": [35, 45]},
    ),
    "near_52w_high": (
        StrategySpec(
            name="near_52w_high",
            family="anchoring_52w_high",
            description="Within a few % of the 52-week high in an uptrend; out 10 % below it.",
            entry=Rule(
                all_of=[
                    C(left="dist_high_252", op=">", right="$near"),
                    C(left="close", op=">", right="sma_200"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="dist_high_252", op="<", right=-0.1)])),
            params={"near": -0.03, "stop": 3.0, "hold": 40},
        ),
        {"near": [-0.02, -0.05], "hold": [20, 60]},
    ),
    "turn_of_month": (
        StrategySpec(
            name="turn_of_month",
            family="calendar",
            description="Long over the turn of the month: last days of a month to its 3rd day.",
            entry=Rule(all_of=[C(left="days_to_month_end", op="<=", right="$pre")]),
            exit=_exit(
                stop=3.0,
                hold=8,
                signal=Rule(
                    all_of=[
                        C(left="day_of_month", op=">=", right=3),
                        C(left="day_of_month", op="<=", right=20),
                    ]
                ),
            ),
            params={"pre": 2},
        ),
        {"pre": [2, 4]},
    ),
    "news_drift": (
        StrategySpec(
            name="news_drift",
            family="news",
            description="Strong rise on abnormal news flow and volume: the news keeps drifting in.",
            entry=Rule(
                all_of=[
                    C(left="news_ratio", op=">", right="$k"),
                    C(left="ret_1", op=">", right=0.02),
                    C(left="volume_ratio", op=">", right=1.5),
                ]
            ),
            exit=_exit(),
            params={"k": 2.0, "stop": 2.5, "hold": 10},
        ),
        {"k": [2.0, 3.0], "hold": [5, 20]},
    ),
    "quiet_drop_reversal": (
        StrategySpec(
            name="quiet_drop_reversal",
            family="news",
            description="Sharp drop with no more news than usual, in an uptrend: likely to revert.",
            entry=Rule(
                all_of=[
                    C(left="ret_1", op="<", right="$drop"),
                    C(left="news_ratio", op="<", right=1.0),
                    C(left="close", op=">", right="sma_200"),
                ]
            ),
            exit=_exit(signal=Rule(all_of=[C(left="rsi_2", op=">", right=70)])),
            params={"drop": -0.03, "stop": 2.5, "hold": 5},
        ),
        {"drop": [-0.02, -0.04], "hold": [3, 6]},
    ),
    "earnings_gap_drift": (
        StrategySpec(
            name="earnings_gap_drift",
            family="news",
            description="Earnings headline, gap up and heavy volume: post-earnings drift.",
            entry=Rule(
                all_of=[
                    C(left="news_earnings_1d", op=">=", right=1),
                    C(left="gap", op=">", right="$gap"),
                    C(left="volume_ratio", op=">", right=2.0),
                ]
            ),
            exit=_exit(stop=3.0),
            params={"gap": 0.03, "hold": 20},
        ),
        {"gap": [0.02, 0.05], "hold": [20, 40]},
    ),
}

# Effects documented on daily bars only, calendar effects documented on US equities only, and
# rules that need the news_* features (``aqt.news``).
DAILY_ONLY = frozenset({"near_52w_high", "turn_of_month"})
EQUITY_ONLY = frozenset({"turn_of_month"})
NEWS_FAMILIES = frozenset({"news_drift", "quiet_drop_reversal", "earnings_gap_drift"})


def swing_families_for(
    families: Iterable[str], timeframe_s: float, session: str, news: bool = False
) -> tuple[str, ...]:
    """The families worth testing at this timeframe and session (fewer, better hypotheses)."""
    return tuple(
        f
        for f in families
        if not (f in DAILY_ONLY and timeframe_s < 86_400)
        and not (f in EQUITY_ONLY and session != "us_equity")
        and not (f in NEWS_FAMILIES and not news)
    )


def list_swing() -> list[str]:
    return sorted(SWING_CATALOG)
