import pandas as pd
import pytest
from aqt.strategies import CATALOG, Condition, ExitRules, Rule, StrategySpec, expand_grid
from pydantic import ValidationError


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"a": [1.0, 2.0, 3.0, 2.0, None], "b": [2.0, 2.0, 2.0, 2.0, 2.0]},
        index=pd.date_range("2024", periods=5, freq="D"),
    )


def test_conditions_and_crosses() -> None:
    f = _frame()
    assert Condition(left="a", op=">", right="b").evaluate(f).tolist() == [
        False,
        False,
        True,
        False,
        False,
    ]
    assert Condition(left="a", op="crosses_above", right="b").evaluate(f).tolist() == [
        False,
        False,
        True,
        False,
        False,
    ]
    assert Condition(left="a", op="crosses_below", right=2.5).evaluate(f).tolist() == [
        False,
        False,
        False,
        True,
        False,
    ]
    with pytest.raises(KeyError):
        Condition(left="zzz", op=">", right=1).evaluate(f)


def test_rule_logic() -> None:
    f = _frame()
    r = Rule(
        all_of=[Condition(left="a", op=">=", right=2)],
        any_of=[Condition(left="a", op="==", right=3), Condition(left="a", op="<", right=2.5)],
    )
    assert r.evaluate(f).tolist() == [False, True, True, True, False]
    assert Rule(all_of=[Condition(left="a", op=">", right=1)], negate=True).evaluate(f).iloc[0]
    assert r.features_used() == {"a"}
    with pytest.raises(ValidationError):
        Rule()


def test_exit_requires_stop() -> None:
    with pytest.raises(ValidationError):
        ExitRules(stop_atr_mult=None, stop_pct=None)


def test_render_and_grid() -> None:
    spec = StrategySpec(
        name="t",
        family="x",
        entry=Rule(all_of=[Condition(left="a", op="<", right="$th")]),
        exit=ExitRules(stop_atr_mult="$s"),
        params={"th": 2, "s": 1.5},
    )
    r = spec.render()
    assert r.entry.all_of[0].right == 2  # type: ignore[union-attr]
    assert r.exit.stop_atr_mult == 1.5
    with pytest.raises(ValueError):
        StrategySpec(
            name="t", family="x", entry=Rule(all_of=[Condition(left="a", op="<", right="$nope")])
        ).render()
    variants = expand_grid(spec, {"th": [1, 2, 3], "s": [1.0, 2.0]})
    assert len(variants) == 6
    assert len({v.config_hash() for v in variants}) == 6
    assert spec.config_hash() == spec.model_copy().config_hash()


def test_catalog_renders_on_features(features: pd.DataFrame) -> None:
    for spec, grid in CATALOG.values():
        assert spec.entry_signal(features).dtype == bool
        assert expand_grid(spec, grid)
