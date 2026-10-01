"""Swing hypothesis catalog: hours-to-days horizons, long-only, built on documented anomalies.

Same format as the other catalogs (``name -> (StrategySpec, grid)``), researched on 1h/4h/1d bars
with the cross-sectional features of ``aqt.features.cross_section``:

* cross-sectional momentum — buy what ranks top of the universe over 20/60 bars
  (Jegadeesh & Titman; time-series/cross-sectional momentum literature);
* short-term reversal — buy last week's losers inside a long-term uptrend;
* relative strength with market breadth — leaders when most of the market is rising;
* trend following — moving-average trend with an ATR stop;
* breakout on volume — a 20-bar high confirmed by unusual volume;
* breadth dip — buy an oversold leader during a market-wide sell-off.

Holding periods are long enough for costs to be a small fraction of the expected move, which is
precisely where the minute-scale catalog failed.
"""

from __future__ import annotations

from aqt.strategies.dsl import Condition, ExitRules, Rule, StrategySpec

C = Condition
Grid = dict[str, list[float | int]]


def _exit(
    stop: str = "$stop", hold: str = "$hold", signal: Rule | None = None, target: str | None = None
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
}


def list_swing() -> list[str]:
    return sorted(SWING_CATALOG)
