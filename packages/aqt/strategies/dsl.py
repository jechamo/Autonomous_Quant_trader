"""Declarative Strategy DSL.

A strategy is pure data (JSON-serialisable), so thousands of variants can be generated,
hashed, stored and audited. Values may reference parameters with ``"$name"``, which are
substituted by :meth:`StrategySpec.render`.

Example::

    StrategySpec(
        name="rsi_reversion",
        family="mean_reversion",
        entry=Rule(all_of=[
            Condition(left="rsi", op="<", right="$rsi_th"),
            Condition(left="close", op=">", right="ema_200"),
            Condition(left="volume_ratio", op=">", right=1.5),
        ]),
        exit=ExitRules(stop_atr_mult=2.0, target_atr_mult=3.0, max_holding_bars=10),
        params={"rsi_th": 30},
    )
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

Operator = Literal["<", "<=", ">", ">=", "==", "!=", "crosses_above", "crosses_below"]
Scalar = float | int | str


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    left: str
    op: Operator
    right: Scalar

    def evaluate(self, features: pd.DataFrame) -> pd.Series:
        lhs = _resolve(features, self.left)
        rhs = _resolve(features, self.right)
        if self.op == "<":
            res = lhs < rhs
        elif self.op == "<=":
            res = lhs <= rhs
        elif self.op == ">":
            res = lhs > rhs
        elif self.op == ">=":
            res = lhs >= rhs
        elif self.op == "==":
            res = lhs == rhs
        elif self.op == "!=":
            res = lhs != rhs
        else:
            diff = lhs - rhs
            prev = diff.shift(1) if isinstance(diff, pd.Series) else diff
            res = (
                (prev <= 0) & (diff > 0) if self.op == "crosses_above" else (prev >= 0) & (diff < 0)
            )
        series = pd.Series(res, index=features.index) if not isinstance(res, pd.Series) else res
        # Missing data never produces a signal.
        valid = _valid_mask(features, self.left) & _valid_mask(features, self.right)
        return series.fillna(False).astype(bool) & valid


class Rule(BaseModel):
    """Boolean combination: all_of AND any_of (each optional), optionally negated."""

    model_config = ConfigDict(frozen=True)

    all_of: list[Condition | Rule] = Field(default_factory=list)
    any_of: list[Condition | Rule] = Field(default_factory=list)
    negate: bool = False

    @model_validator(mode="after")
    def _non_empty(self) -> Rule:
        if not self.all_of and not self.any_of:
            raise ValueError("Rule needs at least one condition in all_of or any_of")
        return self

    def evaluate(self, features: pd.DataFrame) -> pd.Series:
        out = pd.Series(True, index=features.index)
        for c in self.all_of:
            out &= c.evaluate(features)
        if self.any_of:
            anyv = pd.Series(False, index=features.index)
            for c in self.any_of:
                anyv |= c.evaluate(features)
            out &= anyv
        return ~out if self.negate else out

    def features_used(self) -> set[str]:
        used: set[str] = set()
        for c in [*self.all_of, *self.any_of]:
            if isinstance(c, Condition):
                used.add(c.left)
                if isinstance(c.right, str) and not c.right.startswith("$"):
                    used.add(c.right)
            else:
                used |= c.features_used()
        return used


class ExitRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    stop_atr_mult: Scalar | None = 2.0
    target_atr_mult: Scalar | None = None
    stop_pct: Scalar | None = None
    target_pct: Scalar | None = None
    max_holding_bars: Scalar | None = 20
    exit_signal: Rule | None = None

    @model_validator(mode="after")
    def _has_stop(self) -> ExitRules:
        if self.stop_atr_mult is None and self.stop_pct is None:
            raise ValueError("Every strategy must define a protective stop (ATR or %)")
        return self


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    family: str
    version: int = 1
    description: str = ""
    entry: Rule
    exit: ExitRules = Field(default_factory=ExitRules)
    params: dict[str, float | int] = Field(default_factory=dict)

    def render(self, overrides: Mapping[str, float | int] | None = None) -> StrategySpec:
        """Return a copy with ``$param`` references substituted by numeric values."""
        params = {**self.params, **(overrides or {})}
        data = _substitute(self.model_dump(mode="json"), params)
        data["params"] = params
        rendered = StrategySpec.model_validate(data)
        unresolved = _find_refs(rendered.model_dump(mode="json", exclude={"params"}))
        if unresolved:
            raise ValueError(f"Unresolved parameters: {sorted(unresolved)}")
        return rendered

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def entry_signal(self, features: pd.DataFrame) -> pd.Series:
        return self.render().entry.evaluate(features)

    def exit_signal(self, features: pd.DataFrame) -> pd.Series | None:
        spec = self.render()
        return spec.exit.exit_signal.evaluate(features) if spec.exit.exit_signal else None


def expand_grid(
    spec: StrategySpec, grid: Mapping[str, Iterable[float | int]]
) -> list[StrategySpec]:
    """Cartesian product of parameter values -> list of rendered strategy variants."""
    keys = list(grid)
    variants = []
    for values in itertools.product(*(list(grid[k]) for k in keys)):
        overrides = dict(zip(keys, values, strict=True))
        suffix = ",".join(f"{k}={v}" for k, v in overrides.items())
        rendered = spec.render(overrides)
        variants.append(rendered.model_copy(update={"name": f"{spec.name}[{suffix}]"}))
    return variants


def _resolve(features: pd.DataFrame, ref: Scalar) -> pd.Series | float:
    if isinstance(ref, str):
        if ref.startswith("$"):
            raise ValueError(f"Unrendered parameter {ref}; call render() first")
        if ref not in features.columns:
            raise KeyError(f"Unknown feature {ref!r}")
        return features[ref].astype(float)
    return float(ref)


def _valid_mask(features: pd.DataFrame, ref: Scalar) -> pd.Series:
    if isinstance(ref, str) and ref in features.columns:
        return features[ref].notna()
    return pd.Series(True, index=features.index)


def _substitute(obj: Any, params: Mapping[str, float | int]) -> Any:
    if isinstance(obj, dict):
        return {k: _substitute(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(v, params) for v in obj]
    if isinstance(obj, str) and obj.startswith("$") and obj[1:] in params:
        return params[obj[1:]]
    return obj


def _find_refs(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set().union(*(_find_refs(v) for v in obj.values())) if obj else set()
    if isinstance(obj, list):
        return set().union(*(_find_refs(v) for v in obj)) if obj else set()
    if isinstance(obj, str) and obj.startswith("$"):
        return {obj}
    return set()


__all__ = ["Condition", "ExitRules", "Rule", "StrategySpec", "expand_grid"]
