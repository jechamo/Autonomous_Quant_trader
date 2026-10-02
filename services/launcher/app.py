"""Full-screen terminal menu: pick how to start the system, fill in its options, launch it."""

from __future__ import annotations

import shlex
from typing import Any, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    Switch,
)

from services.launcher.catalog import (
    MODE_BY_KEY,
    MODES,
    Mode,
    Readiness,
    Value,
    build_args,
    dashboard_url,
    defaults,
    fmt_value,
    validate,
)

CSS = """
Screen { background: #0b0f14; }
#top { height: 3; padding: 0 2; background: #121821; border-bottom: solid #233040; }
#brand { width: 1fr; content-align: left middle; height: 3; text-style: bold; color: #60a5fa; }
#keys { width: auto; content-align: right middle; height: 3; }
#body { height: 1fr; }
#modes { width: 38; background: #121821; border-right: solid #233040; padding: 1 0; }
#modes > ListItem { padding: 1 2; background: #121821; }
#modes > ListItem.-highlight { background: #1e3a5f; }
#modes Label { width: 100%; }
#right { width: 1fr; }
#detail { padding: 1 3; height: 1fr; }
#title { text-style: bold; color: #dbe4ee; margin-bottom: 1; }
#summary { color: #dbe4ee; margin-bottom: 1; }
#when { color: #7f8ea3; margin-bottom: 1; }
#warn { color: #fecaca; background: #3a1414; padding: 0 1; margin-bottom: 1; }
#notes { color: #f59e0b; margin-bottom: 1; }
.row { height: auto; margin-top: 1; }
.label { width: 30; padding-top: 1; color: #dbe4ee; text-style: bold; }
.control { width: 32; }
.help { width: 1fr; padding: 1 0 0 2; color: #7f8ea3; }
.error { color: #ef4444; }
#form { height: auto; }
#cmdbox { margin: 0 3; padding: 1 2; background: #121821; border: round #233040; height: auto; }
#cmd { color: #a7f3d0; }
#url { color: #60a5fa; margin-top: 1; }
#actions { height: auto; margin: 1 3; }
#actions Button { margin-right: 2; }
"""


class LauncherApp(App[list[str] | None]):
    TITLE = "Autonomous Quant Trader"
    CSS = CSS
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f5", "launch", "Arrancar"),
        Binding("ctrl+r", "launch", "Arrancar", show=False),
        Binding("f2", "copy", "Copiar comando"),
        Binding("escape", "quit", "Salir"),
    ]

    def __init__(self, ready: Readiness, memory: dict[str, dict[str, Value]] | None = None) -> None:
        super().__init__()
        self.ready = ready
        self.memory = memory if memory is not None else {}
        self.mode: Mode = MODES[0]
        self.values: dict[str, Value] = {}

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        def chip(ok: bool, name: str) -> str:
            return f"[{'green' if ok else 'grey50'}]{'●' if ok else '○'} {name}[/]"

        keys = "   ".join(
            [
                chip(self.ready.alpaca, "Alpaca paper"),
                chip(self.ready.openai, "OpenAI"),
                chip(self.ready.notify, "Avisos móvil"),
            ]
        )
        with Horizontal(id="top"):
            yield Static("◆ AUTONOMOUS QUANT TRADER  ·  solo PAPER", id="brand")
            yield Static(keys, id="keys")
        with Horizontal(id="body"):
            yield ListView(
                *[ListItem(Label(f"{m.icon}  {m.title}"), id=f"m-{m.key}") for m in MODES],
                id="modes",
            )
            with Vertical(id="right"):
                with VerticalScroll(id="detail"):
                    yield Static(id="title")
                    yield Static(id="summary")
                    yield Static(id="when")
                    yield Static(id="warn")
                    yield Static(id="notes")
                    yield Vertical(id="form")
                with Vertical(id="cmdbox"):
                    yield Static(id="cmd")
                    yield Static(id="url")
                with Horizontal(id="actions"):
                    yield Button("▶  Arrancar  (F5)", id="go", variant="success")
                    yield Button("Copiar comando  (F2)", id="copy")
        yield Footer()

    def on_mount(self) -> None:
        self.show_mode(MODES[0])
        self.query_one("#modes", ListView).focus()

    # ------------------------------------------------------------------ mode
    def show_mode(self, mode: Mode) -> None:
        self.mode = mode
        self.values = {**defaults(mode), **self.memory.get(mode.key, {})}
        self.query_one("#title", Static).update(Text(f"{mode.icon}  {mode.title}"))
        self.query_one("#summary", Static).update(Text(mode.summary))
        self.query_one("#when", Static).update(Text(f"Cuándo usarlo: {mode.when}"))
        notes = self.query_one("#notes", Static)
        notes.update(Text("\n".join(f"• {n}" for n in mode.notes)))
        notes.display = bool(mode.notes)
        form = self.query_one("#form", Vertical)
        form.remove_children()
        rows = []
        for f in mode.fields:
            v = self.values[f.key]
            widget: Any
            if f.kind == "bool":
                widget = Switch(value=bool(v), id=f"f-{f.key}")
            elif f.kind == "choice":
                widget = Select(
                    [(label, value) for value, label in f.choices],
                    value=v,
                    allow_blank=False,
                    id=f"f-{f.key}",
                )
            else:
                kind = {"int": "integer", "float": "number"}.get(f.kind, "text")
                text = fmt_value(f, v) if f.kind in ("int", "float") else str(v)
                widget = Input(value=text, type=kind, id=f"f-{f.key}")  # type: ignore[arg-type]
            widget.add_class("control")
            rows.append(
                Horizontal(
                    Label(f.label, classes="label"),
                    widget,
                    Static(Text(f.help), classes="help", id=f"h-{f.key}"),
                    classes="row",
                )
            )
        form.mount_all(rows)
        self.refresh_command()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None and event.item.id:
            self.show_mode(MODE_BY_KEY[event.item.id.removeprefix("m-")])

    # ------------------------------------------------------------------ values
    def _set(self, wid: str | None, value: Value) -> None:
        if not wid or not wid.startswith("f-"):
            return
        key = wid.removeprefix("f-")
        self.values[key] = value
        self.memory.setdefault(self.mode.key, {})[key] = value
        self.refresh_command()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._set(event.input.id, event.value)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._set(event.switch.id, event.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        if isinstance(event.value, str):
            self._set(event.select.id, event.value)

    def refresh_command(self) -> None:
        errors = validate(self.mode, self.values)
        for f in self.mode.fields:
            help_ = self.query(f"#h-{f.key}")
            if help_:
                h = help_.first(Static)
                err = errors.get(f.key)
                h.update(Text(f"⚠ {err}" if err else f.help))
                h.set_class(bool(err), "error")
        missing = self.ready.missing(self.mode)
        warn = self.query_one("#warn", Static)
        warn.update(Text("\n".join(missing)))
        warn.display = bool(missing)
        cmd = self.query_one("#cmd", Static)
        url = self.query_one("#url", Static)
        if errors:
            cmd.update(Text("Corrige los campos marcados para ver el comando."))
            url.display = False
        else:
            cmd.update(Text(self.command_line()))
            link = dashboard_url(self.mode, self.values)
            url.update(
                Text(f"Dashboard: {link}" if link else "Sin dashboard (se ve en la terminal)")
            )
            url.display = True
        self.query_one("#go", Button).disabled = bool(errors or missing)

    def command_line(self) -> str:
        args = build_args(self.mode, self.values)
        return "uv run python -m services.trader " + " ".join(shlex.quote(a) for a in args)

    # ------------------------------------------------------------------ actions
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go":
            self.action_launch()
        elif event.button.id == "copy":
            self.action_copy()

    def action_launch(self) -> None:
        if validate(self.mode, self.values) or self.ready.missing(self.mode):
            self.bell()
            return
        self.exit(build_args(self.mode, self.values))

    def action_copy(self) -> None:
        self.copy_to_clipboard(self.command_line())
        self.notify("Comando copiado al portapapeles")
