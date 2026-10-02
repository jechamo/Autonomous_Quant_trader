"""Runtime configuration.

Live trading requires TWO explicit opt-ins: ``TRADING_MODE=LIVE`` and
``LIVE_TRADING_ENABLED=true``. Anything else is refused.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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


def load_dotenv(path: str = ".env", env: MutableMapping[str, str] | None = None) -> list[str]:
    """Load ``KEY=VALUE`` lines from a local ``.env`` (never committed) without overriding
    variables already set. Returns the keys loaded (values are never logged)."""
    target = os.environ if env is None else env
    loaded: list[str] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in target:
            target[key] = value
            loaded.append(key)
    return loaded


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
