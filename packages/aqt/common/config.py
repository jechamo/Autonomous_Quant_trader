"""Runtime configuration.

Live trading requires TWO explicit opt-ins: ``TRADING_MODE=LIVE`` and
``LIVE_TRADING_ENABLED=true``. Anything else is refused.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ConfigError(RuntimeError):
    pass


class TradingMode(StrEnum):
    DEV = "DEV"
    PAPER = "PAPER"
    LIVE = "LIVE"


_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    trading_mode: TradingMode
    live_trading_enabled: bool
    kill_switch: bool
    data_dir: str
    reports_dir: str

    @property
    def is_live(self) -> bool:
        return self.trading_mode is TradingMode.LIVE and self.live_trading_enabled


def _flag(env: Mapping[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() in _TRUE


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    raw_mode = env.get("TRADING_MODE", "DEV").strip().upper()
    try:
        mode = TradingMode(raw_mode)
    except ValueError as exc:
        raise ConfigError(f"Invalid TRADING_MODE={raw_mode!r}") from exc

    live_enabled = _flag(env, "LIVE_TRADING_ENABLED")
    if mode is TradingMode.LIVE and not live_enabled:
        raise ConfigError("TRADING_MODE=LIVE requires LIVE_TRADING_ENABLED=true")
    if live_enabled and mode is not TradingMode.LIVE:
        raise ConfigError("LIVE_TRADING_ENABLED=true is only valid with TRADING_MODE=LIVE")

    return Settings(
        trading_mode=mode,
        live_trading_enabled=live_enabled,
        kill_switch=_flag(env, "GLOBAL_KILL_SWITCH"),
        data_dir=env.get("DATA_DIR", "data/parquet"),
        reports_dir=env.get("REPORTS_DIR", "reports"),
    )
