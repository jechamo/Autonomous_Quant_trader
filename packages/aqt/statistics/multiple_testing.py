"""Multiple-hypothesis control. Test 50 000 strategies and some will look great by luck."""

from __future__ import annotations

import numpy as np


def benjamini_hochberg(p_values: np.ndarray, q: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini–Hochberg FDR control.

    Returns ``(rejected, adjusted_p)`` aligned with the input order.
    """
    p = np.asarray(p_values, dtype=float)
    m = p.size
    if m == 0:
        return np.zeros(0, dtype=bool), np.zeros(0)
    if np.any((p < 0) | (p > 1) | np.isnan(p)):
        raise ValueError("p-values must be in [0, 1]")
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    adjusted_sorted = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1.0)
    adjusted = np.empty(m)
    adjusted[order] = adjusted_sorted
    return adjusted <= q, adjusted
