import pytest
from aqt.common.config import ConfigError, TradingMode, load_settings


def test_default_is_dev() -> None:
    s = load_settings({})
    assert s.trading_mode is TradingMode.DEV
    assert not s.is_live


def test_live_requires_both_flags() -> None:
    with pytest.raises(ConfigError):
        load_settings({"TRADING_MODE": "LIVE"})
    with pytest.raises(ConfigError):
        load_settings({"TRADING_MODE": "PAPER", "LIVE_TRADING_ENABLED": "true"})
    s = load_settings({"TRADING_MODE": "LIVE", "LIVE_TRADING_ENABLED": "true"})
    assert s.is_live


def test_invalid_mode_and_kill_switch() -> None:
    with pytest.raises(ConfigError):
        load_settings({"TRADING_MODE": "YOLO"})
    assert load_settings({"GLOBAL_KILL_SWITCH": "1"}).kill_switch
