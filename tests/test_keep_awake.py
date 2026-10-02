from __future__ import annotations

import sys

import pytest

from services.trader import keep_awake as ka


def test_keep_awake_is_a_no_op_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert ka.keep_awake() is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows power request")
def test_keep_awake_asks_windows_and_can_be_released() -> None:
    import ctypes

    try:
        assert ka.keep_awake() is True
    finally:  # release the request for the test runner's thread
        ctypes.windll.kernel32.SetThreadExecutionState(ka.ES_CONTINUOUS)
