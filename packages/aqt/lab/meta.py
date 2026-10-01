"""Meta-labeling: learn from a strategy's own good and bad trades *when* to trust its signals.

Every shadow trade stores the features seen at the decision (its context) and its net outcome.
A gradient-boosting classifier learns P(trade wins after costs | context). It is evaluated with
purged K-fold cross-validation (no leakage between neighbouring trades): each trade is scored by
a model that never saw it, then we ask whether keeping only the trades above a probability
threshold would have had a positive, significant and better expected value.

Only if it does is a *new version* of the strategy created — the original rule plus this filter —
and it starts again as a challenger: it must prove itself in the forward shadow book before the
Risk Engine lets it trade. The model never sizes or sends orders; it can only say "skip".
"""

from __future__ import annotations

import hashlib
import pickle
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aqt.statistics.confidence import mean_return_test
from aqt.statistics.validation import purged_kfold_splits
from aqt.stream.bars import Bar
from aqt.stream.features import FeatureSnapshot
from aqt.stream.strategies import EntryIntent, StreamStrategy

# Price levels and clocks say *when* a trade happened, not *what* the market looked like.
_EXCLUDE = re.compile(
    r"^(ts|bars_seen|close|open|high|low|volume|ema_fast|ema_slow|rolling_mean|prior_high|"
    r"(sma|ema|high|low|prev_high|prev_low)_\d+|atr|macd.*)$"
)


def usable_features(contexts: Sequence[Mapping[str, float]]) -> list[str]:
    keys = sorted({k for c in contexts for k in c})
    return [k for k in keys if not _EXCLUDE.match(k)]


@dataclass(frozen=True)
class MetaConfig:
    min_trades: int = 60
    n_splits: int = 5
    embargo: int = 2
    thresholds: tuple[float, ...] = (0.45, 0.5, 0.55, 0.6, 0.65)
    min_kept: int = 20
    alpha: float = 0.05  # Bonferroni-corrected across thresholds
    seed: int = 7


@dataclass
class MetaResult:
    accepted: bool
    reason: str
    n_trades: int
    features: list[str] = field(default_factory=list)
    threshold: float = 0.5
    ev_all: float = 0.0
    ev_kept: float = 0.0
    kept_fraction: float = 0.0
    p_value: float = 1.0
    importance: dict[str, float] = field(default_factory=dict)
    model: Any = None

    def summary(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "n_trades": self.n_trades,
            "threshold": self.threshold,
            "ev_all": self.ev_all,
            "ev_kept": self.ev_kept,
            "kept_fraction": self.kept_fraction,
            "p_value": self.p_value,
            "importance": self.importance,
            "features": self.features,
        }


def _matrix(contexts: Sequence[Mapping[str, float]], features: list[str]) -> np.ndarray:
    df = pd.DataFrame(list(contexts), columns=features, dtype=float)
    med = df.median().fillna(0.0)
    return df.fillna(med).to_numpy(dtype=float)


def _classifier(seed: int) -> Any:
    from sklearn.ensemble import GradientBoostingClassifier

    return GradientBoostingClassifier(
        n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=seed
    )


def train_meta_filter(
    contexts: Sequence[Mapping[str, float]], returns: Sequence[float], cfg: MetaConfig | None = None
) -> MetaResult:
    cfg = cfg or MetaConfig()
    r = np.asarray(returns, dtype=float)
    n = int(r.size)
    if n < cfg.min_trades:
        return MetaResult(False, f"only {n} trades (< {cfg.min_trades})", n)
    features = usable_features(contexts)
    if not features:
        return MetaResult(False, "no usable features", n)
    x = _matrix(contexts, features)
    y = (r > 0).astype(int)
    if y.min() == y.max():
        return MetaResult(False, "all trades have the same outcome", n, features)

    oof = np.full(n, np.nan)
    for train_idx, test_idx in purged_kfold_splits(n, cfg.n_splits, cfg.embargo):
        if len(set(y[train_idx])) < 2:
            continue
        model = _classifier(cfg.seed).fit(x[train_idx], y[train_idx])
        oof[test_idx] = model.predict_proba(x[test_idx])[:, 1]
    scored = ~np.isnan(oof)
    ev_all = float(r[scored].mean()) if scored.any() else 0.0

    best: tuple[float, float, float, int] | None = None  # (ev, threshold, p, kept)
    for th in cfg.thresholds:
        kept = scored & (oof >= th)
        if kept.sum() < cfg.min_kept:
            continue
        ev = float(r[kept].mean())
        p = mean_return_test(r[kept]).p_value
        if best is None or ev > best[0]:
            best = (ev, th, p, int(kept.sum()))
    if best is None:
        return MetaResult(False, "filter keeps too few trades", n, features, ev_all=ev_all)
    ev_kept, th, p, kept_n = best
    p_adj = min(1.0, p * len(cfg.thresholds))
    final = _classifier(cfg.seed).fit(x, y)
    importance = dict(
        sorted(
            zip(features, (float(v) for v in final.feature_importances_), strict=True),
            key=lambda kv: kv[1],
            reverse=True,
        )[:8]
    )
    accepted = ev_kept > 0 and ev_kept > ev_all and p_adj < cfg.alpha
    if accepted:
        reason = "filtered trades beat the unfiltered strategy out of fold"
    elif ev_kept <= 0:
        reason = "even the best filter keeps a negative expected value"
    elif ev_kept <= ev_all:
        reason = "the filter does not improve on taking every signal"
    else:
        reason = f"improvement not significant (p={p_adj:.3f})"
    return MetaResult(
        accepted=accepted,
        reason=reason,
        n_trades=n,
        features=features,
        threshold=th,
        ev_all=ev_all,
        ev_kept=ev_kept,
        kept_fraction=kept_n / max(int(scored.sum()), 1),
        p_value=p_adj,
        importance=importance,
        model=final,
    )


def save_model(model: Any, directory: Path, name: str) -> tuple[str, str]:
    """Persist a trained model; returns (path, sha256). Only our own files are ever loaded."""
    directory.mkdir(parents=True, exist_ok=True)
    blob = pickle.dumps(model)
    digest = hashlib.sha256(blob).hexdigest()
    path = directory / f"{name}-{digest[:12]}.pkl"
    path.write_bytes(blob)
    return str(path), digest


def load_model(path: str, digest: str) -> Any:
    blob = Path(path).read_bytes()
    if hashlib.sha256(blob).hexdigest() != digest:
        raise ValueError(f"model file {path} does not match its registered hash")
    return pickle.loads(blob)


@dataclass
class MetaFilteredStrategy(StreamStrategy):
    """The inner strategy's signals, kept only when the learned P(win) clears the threshold."""

    inner: StreamStrategy
    model: Any
    feature_names: list[str]
    threshold: float
    strategy_id: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        self.features = self.inner.features  # same feature time scale as the wrapped strategy
        self.min_cost_multiple = self.inner.min_cost_multiple
        if not self.strategy_id:
            self.strategy_id = f"{self.inner.strategy_id}~meta"
        if not self.description:
            self.description = (
                f"{self.inner.description} + filtro aprendido (p >= {self.threshold:.2f})"
            )
        self.last_probability: float | None = None

    def on_bar(self, bar: Bar) -> None:
        self.inner.on_bar(bar)

    def entry(self, f: FeatureSnapshot) -> EntryIntent | None:
        intent = self.inner.entry(f)
        if intent is None:
            return None
        ctx = dict(intent.context or {})
        if not ctx:
            ctx = {k: float(v) for k, v in f.to_dict().items() if isinstance(v, int | float)}
        row = np.array([[ctx.get(k, np.nan) for k in self.feature_names]], dtype=float)
        row = np.where(np.isnan(row), 0.0, row)
        p = float(self.model.predict_proba(row)[0, 1])
        self.last_probability = p
        if p < self.threshold:
            return None
        return EntryIntent(
            self.strategy_id,
            intent.symbol,
            intent.ts,
            intent.stop_pct,
            intent.target_pct,
            intent.max_hold_bars,
            f"{intent.reason} | meta p={p:.2f}",
            ctx,
        )

    def should_exit(self, f: FeatureSnapshot) -> bool:
        return self.inner.should_exit(f)

    def clears_costs(self, intent: EntryIntent, round_trip_cost: float) -> bool:
        return self.inner.clears_costs(intent, round_trip_cost)
