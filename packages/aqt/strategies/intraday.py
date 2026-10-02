"""Intraday hypothesis catalog for the Research Lab (minute bars, crypto 24/7, long-only).

Same format as :data:`aqt.strategies.catalog.CATALOG` — ``name -> (StrategySpec, grid)`` — so
the existing research pipeline (IS sweep → BH-FDR → frozen OOS → walk-forward → Monte Carlo →
study-wide FDR) tests every variant unchanged. Rules use the causal ``FeatureEngine`` columns
plus the order-flow features ``flow_imbalance_{5,15}`` built from taker-buy volume.

Grids deliberately include wide targets and long holds: with ~0.1 % fees per side a 1-minute
ATR is usually far too small to pay for a round trip, and the search must be allowed to find
the horizon where moves are big enough.
"""

from __future__ import annotations

from aqt.strategies.dsl import Condition, ExitRules, Rule, StrategySpec

C = Condition
Grid = dict[str, list[float | int]]

INTRADAY_CATALOG: dict[str, tuple[StrategySpec, Grid]] = {
    "flow_breakout": (
        StrategySpec(
            name="flow_breakout",
            family="breakout",
            description="Breaks the 20-bar high with aggressive buying, above the 50-bar EMA.",
            entry=Rule(
                all_of=[
                    C(left="close", op=">", right="prev_high_20"),
                    C(left="flow_imbalance_5", op=">", right="$flow"),
                    C(left="close", op=">", right="ema_50"),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult="$stop", target_atr_mult="$target", max_holding_bars="$hold"
            ),
            params={"flow": 0.2, "stop": 2.0, "target": 6.0, "hold": 60},
        ),
        {"flow": [0.1, 0.3], "stop": [1.5, 3.0], "target": [4.0, 8.0], "hold": [30, 120]},
    ),
    "flow_momentum": (
        StrategySpec(
            name="flow_momentum",
            family="momentum",
            description="Sustained buying pressure over 15 bars with positive 5-bar momentum.",
            entry=Rule(
                all_of=[
                    C(left="flow_imbalance_15", op=">", right="$flow"),
                    C(left="ret_5", op=">", right="$mom"),
                    C(left="close", op=">", right="ema_20"),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult="$stop", target_atr_mult="$target", max_holding_bars="$hold"
            ),
            params={"flow": 0.2, "mom": 0.002, "stop": 2.0, "target": 6.0, "hold": 60},
        ),
        {
            "flow": [0.15, 0.3],
            "mom": [0.001, 0.003],
            "stop": [2.0, 3.0],
            "target": [5.0, 10.0],
            "hold": [60, 240],
        },
    ),
    "rsi_flow_reversion": (
        StrategySpec(
            name="rsi_flow_reversion",
            family="mean_reversion",
            description="Oversold RSI once selling pressure has faded; exit when RSI recovers.",
            entry=Rule(
                all_of=[
                    C(left="rsi", op="<", right="$rsi"),
                    C(left="flow_imbalance_5", op=">", right="$flow"),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult="$stop",
                max_holding_bars="$hold",
                exit_signal=Rule(all_of=[C(left="rsi", op=">", right="$rsi_exit")]),
            ),
            params={"rsi": 25, "flow": 0.0, "stop": 3.0, "hold": 60, "rsi_exit": 55},
        ),
        {
            "rsi": [20, 30],
            "flow": [-0.1, 0.1],
            "stop": [2.0, 4.0],
            "hold": [30, 120],
            "rsi_exit": [50, 65],
        },
    ),
    "bollinger_reversion": (
        StrategySpec(
            name="bollinger_reversion",
            family="mean_reversion",
            description="Close below the lower Bollinger band in a non-crashing market.",
            entry=Rule(
                all_of=[
                    C(left="bb_position", op="<", right="$bb"),
                    C(left="dist_sma_200", op=">", right="$floor"),
                    C(left="flow_imbalance_5", op=">", right=-0.3),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult="$stop",
                max_holding_bars="$hold",
                exit_signal=Rule(all_of=[C(left="bb_position", op=">", right=0.5)]),
            ),
            params={"bb": 0.0, "floor": -0.02, "stop": 3.0, "hold": 60},
        ),
        {"bb": [-0.1, 0.05], "floor": [-0.03, -0.01], "stop": [2.0, 4.0], "hold": [30, 120]},
    ),
    "vwap_reversion": (
        StrategySpec(
            name="vwap_reversion",
            family="mean_reversion",
            description="Price stretched below the rolling VWAP with buyers stepping back in.",
            entry=Rule(
                all_of=[
                    C(left="vwap_dev", op="<", right="$dev"),
                    C(left="flow_imbalance_5", op=">", right=0.0),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult="$stop",
                max_holding_bars="$hold",
                exit_signal=Rule(all_of=[C(left="vwap_dev", op=">", right=0.0)]),
            ),
            params={"dev": -0.004, "stop": 3.0, "hold": 60},
        ),
        {"dev": [-0.003, -0.006, -0.01], "stop": [2.0, 4.0], "hold": [30, 120]},
    ),
    "squeeze_breakout": (
        StrategySpec(
            name="squeeze_breakout",
            family="volatility",
            description="Quiet market (low ATR) breaking out on above-average volume.",
            entry=Rule(
                all_of=[
                    C(left="atr_pct", op="<", right="$atr_max"),
                    C(left="close", op=">", right="prev_high_20"),
                    C(left="volume_ratio", op=">", right="$vr"),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult="$stop", target_atr_mult="$target", max_holding_bars="$hold"
            ),
            params={"atr_max": 0.001, "vr": 2.0, "stop": 2.0, "target": 8.0, "hold": 120},
        ),
        {
            "atr_max": [0.0007, 0.0015],
            "vr": [1.5, 3.0],
            "stop": [1.5, 3.0],
            "target": [6.0, 12.0],
            "hold": [60, 240],
        },
    ),
    "trend_pullback": (
        StrategySpec(
            name="trend_pullback",
            family="trend_following",
            description="Uptrend (above EMA-200, positive trend strength) dipping to the EMA-20.",
            entry=Rule(
                all_of=[
                    C(left="close", op=">", right="ema_200"),
                    C(left="trend_strength", op=">", right="$trend"),
                    C(left="dist_ema_20", op="<", right="$pull"),
                    C(left="flow_imbalance_5", op=">", right=0.0),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult="$stop", target_atr_mult="$target", max_holding_bars="$hold"
            ),
            params={"trend": 2.0, "pull": -0.001, "stop": 2.5, "target": 8.0, "hold": 120},
        ),
        {
            "trend": [1.0, 3.0],
            "pull": [-0.0005, -0.002],
            "stop": [2.0, 3.5],
            "target": [6.0, 12.0],
            "hold": [60, 240],
        },
    ),
}


def list_intraday() -> list[str]:
    return sorted(INTRADAY_CATALOG)
