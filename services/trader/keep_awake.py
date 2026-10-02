"""Keep the computer from idle-sleeping while the trader runs (Windows; no-op elsewhere).

A per-process request (``SetThreadExecutionState``): it changes no power settings, the screen
may still turn off and the session may still lock, and Windows drops the request as soon as the
process exits. A closed lid or a manual Sleep still suspends the machine.
"""

from __future__ import annotations

import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake() -> bool:
    """Ask Windows not to idle-sleep while this thread lives; True when the request was taken."""
    if sys.platform != "win32":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    return bool(kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
