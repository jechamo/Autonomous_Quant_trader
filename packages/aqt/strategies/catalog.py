"""Initial strategy catalogue (one representative per family) with parameter grids."""

from __future__ import annotations

from aqt.strategies.dsl import Condition, ExitRules, Rule, StrategySpec

C = Condition

CATALOG: dict[str, tuple[StrategySpec, dict[str, list[float | int]]]] = {
    "momentum": (
        StrategySpec(
            name="momentum",
            family="momentum",
            description="Positive 20-bar momentum in an established uptrend, not overbought.",
            entry=Rule(
                all_of=[
                    C(left="momentum_20", op=">", right="$mom_th"),
                    C(left="close", op=">", right="sma_200"),
                    C(left="rsi", op="<", right="$rsi_max"),
                ]
            ),
            exit=ExitRules(stop_atr_mult="$stop_atr", target_atr_mult=4.0, max_holding_bars=20),
            params={"mom_th": 0.05, "rsi_max": 75, "stop_atr": 2.5},
        ),
        {"mom_th": [0.03, 0.05, 0.08], "rsi_max": [70, 80], "stop_atr": [2.0, 3.0]},
    ),
    "mean_reversion": (
        StrategySpec(
            name="mean_reversion",
            family="mean_reversion",
            description="Oversold RSI pull-back above the long-term trend.",
            entry=Rule(
                all_of=[
                    C(left="rsi", op="<", right="$rsi_th"),
                    C(left="close", op=">", right="ema_200"),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult=2.0,
                max_holding_bars="$hold",
                exit_signal=Rule(all_of=[C(left="rsi", op=">", right=55)]),
            ),
            params={"rsi_th": 30, "hold": 10},
        ),
        {"rsi_th": [25, 30, 35], "hold": [5, 10, 15]},
    ),
    "breakout": (
        StrategySpec(
            name="breakout",
            family="breakouts",
            description="Close breaks the prior 20-bar high on above-average volume.",
            entry=Rule(
                all_of=[
                    C(left="close", op=">", right="prev_high_20"),
                    C(left="volume_ratio", op=">", right="$vol_th"),
                ]
            ),
            exit=ExitRules(stop_atr_mult="$stop_atr", target_atr_mult=3.0, max_holding_bars=15),
            params={"vol_th": 1.2, "stop_atr": 2.0},
        ),
        {"vol_th": [1.0, 1.2, 1.5], "stop_atr": [1.5, 2.0, 3.0]},
    ),
    "trend_following": (
        StrategySpec(
            name="trend_following",
            family="trend_following",
            description="EMA20 crosses above EMA50 while price is above SMA200.",
            entry=Rule(
                all_of=[
                    C(left="ema_20", op="crosses_above", right="ema_50"),
                    C(left="close", op=">", right="sma_200"),
                ]
            ),
            exit=ExitRules(
                stop_atr_mult="$stop_atr",
                max_holding_bars="$hold",
                exit_signal=Rule(all_of=[C(left="ema_20", op="crosses_below", right="ema_50")]),
            ),
            params={"stop_atr": 3.0, "hold": 60},
        ),
        {"stop_atr": [2.0, 3.0, 4.0], "hold": [40, 60, 100]},
    ),
    "candlestick": (
        StrategySpec(
            name="candlestick",
            family="candlestick_patterns",
            description="Bullish engulfing + low RSI + volume spike + price above EMA200.",
            entry=Rule(
                all_of=[
                    C(left="pat_bullish_engulfing", op="==", right=1),
                    C(left="rsi", op="<", right="$rsi_th"),
                    C(left="volume_ratio", op=">", right="$vol_th"),
                    C(left="close", op=">", right="ema_200"),
                ]
            ),
            exit=ExitRules(stop_atr_mult=2.0, target_atr_mult=3.0, max_holding_bars=10),
            params={"rsi_th": 40, "vol_th": 1.2},
        ),
        {"rsi_th": [32, 40, 50], "vol_th": [1.0, 1.2, 1.5]},
    ),
}


def list_strategies() -> list[str]:
    return sorted(CATALOG)


def get_strategy(name: str) -> tuple[StrategySpec, dict[str, list[float | int]]]:
    try:
        return CATALOG[name]
    except KeyError as exc:
        raise KeyError(f"Unknown strategy {name!r}. Available: {list_strategies()}") from exc


def resolve_strategy(
    name: str, catalog: str = "daily"
) -> tuple[StrategySpec, dict[str, list[float | int]]]:
    """Look a strategy up in the daily ``CATALOG`` or the ``intraday`` Research Lab catalog."""
    if catalog == "daily":
        return get_strategy(name)
    if catalog == "intraday":
        from aqt.strategies.intraday import INTRADAY_CATALOG

        try:
            return INTRADAY_CATALOG[name]
        except KeyError as exc:
            raise KeyError(f"Unknown intraday strategy {name!r}") from exc
    raise KeyError(f"Unknown catalog {catalog!r}")
