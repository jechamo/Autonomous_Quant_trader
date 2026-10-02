from __future__ import annotations

import asyncio

import pytest
import typer.main
from textual.widgets import Button, Input, ListView, Static

from services.launcher.app import LauncherApp
from services.launcher.catalog import (
    MODE_BY_KEY,
    MODES,
    Readiness,
    build_args,
    dashboard_url,
    defaults,
    readiness,
    validate,
)
from services.trader.cli import app as cli_app

READY = Readiness(alpaca=True, openai=True, notify=False)


def test_every_option_exists_in_the_real_cli_and_nothing_is_live() -> None:
    commands = typer.main.get_command(cli_app).commands  # type: ignore[attr-defined]
    for mode in MODES:
        cmd = commands[mode.fixed[0]]
        opts = {o for p in cmd.params for o in [*p.opts, *getattr(p, "secondary_opts", [])]}
        args = build_args(mode, defaults(mode))
        assert not validate(mode, defaults(mode)), mode.key
        for a in args[1:]:
            if a.startswith("--"):
                assert a in opts, f"{mode.key}: {a} is not an option of {mode.fixed[0]}"
        assert not any("live" in a.lower() for a in args)  # PAPER and research only
        assert mode.summary and mode.when and all(f.help for f in mode.fields)


def test_build_args_is_explicit_and_validation_explains() -> None:
    mode = MODE_BY_KEY["simulate"]
    values = {**defaults(mode), "market": "stocks", "hours": "48", "headless": True}
    assert build_args(mode, values) == [
        "simulate", "--market", "stocks", "--hours", "48", "--cash", "10000", "--learn",
        "--headless", "--speed", "300", "--port", "8001", "--open",
    ]  # fmt: skip
    assert dashboard_url(mode, values) == "http://127.0.0.1:8001"
    assert dashboard_url(MODE_BY_KEY["research"], {}) is None
    bad = {**values, "hours": "abc", "port": "80", "speed": "-1", "market": "forex"}
    assert validate(mode, bad) == {
        "hours": "tiene que ser un número", "port": "mínimo 1024", "speed": "mínimo 0",
        "market": "opción no válida",
    }  # fmt: skip
    live = MODE_BY_KEY["crypto_live"]
    assert validate(live, {**defaults(live), "symbols": "BTC USDC"}) == {
        "symbols": "sin espacios (separa con comas)"
    }
    assert validate(live, {**defaults(live), "port": "8000.5"})["port"].startswith("tiene que")
    research = MODE_BY_KEY["research"]
    assert "--timeframes" not in build_args(research, defaults(research))  # empty → CLI default


def test_readiness_never_needs_values() -> None:
    r = readiness({"ALPACA_KEY_PAPER": "k", "ALPACA_SECRET_PAPER": "s", "OPENAI_API_KEY": " "})
    assert not r.openai and not r.notify
    none = Readiness(False, False, False)
    assert none.missing(MODE_BY_KEY["stocks_alpaca"]) and none.missing(MODE_BY_KEY["analyst"])
    assert not none.missing(MODE_BY_KEY["crypto_live"])


def test_menu_shows_modes_builds_the_command_and_launches() -> None:
    async def go() -> list[str] | None:
        memory: dict[str, dict[str, object]] = {}
        app = LauncherApp(Readiness(alpaca=False, openai=True, notify=False), memory)  # type: ignore[arg-type]
        async with app.run_test(size=(160, 50)) as pilot:
            assert len(app.query_one("#modes", ListView).children) == len(MODES)
            assert "services.trader run --market binance" in str(
                app.query_one("#cmd", Static).render()
            )
            await pilot.press("down")  # Alpaca paper, but no keys → cannot launch
            await pilot.pause()
            assert app.mode.key == "stocks_alpaca"
            assert app.query_one("#go", Button).disabled
            assert "Alpaca" in str(app.query_one("#warn", Static).render())
            await pilot.press("up")
            await pilot.pause()
            cash = app.query_one("#f-cash", Input)
            cash.value = "2500"
            await pilot.pause()
            assert "--cash 2500" in app.command_line() and memory["crypto_live"]["cash"] == "2500"
            cash.value = "5"  # below the minimum → no command, no launch
            await pilot.pause()
            assert app.query_one("#go", Button).disabled
            await pilot.press("f5")
            assert app.return_value is None
            cash.value = "2500"
            await pilot.pause()
            await pilot.press("f2")
            await pilot.press("f5")
            await pilot.pause()
        return app.return_value

    args = asyncio.run(go())
    assert args is not None and args[:3] == ["run", "--market", "binance"]
    assert args[args.index("--cash") + 1] == "2500"


@pytest.mark.parametrize("key", [m.key for m in MODES])
def test_every_mode_renders(key: str) -> None:
    async def go() -> None:
        app = LauncherApp(READY)
        async with app.run_test(size=(160, 50)) as pilot:
            app.show_mode(MODE_BY_KEY[key])
            await pilot.pause()
            assert app.mode.key == key and not app.query_one("#go", Button).disabled

    asyncio.run(go())
