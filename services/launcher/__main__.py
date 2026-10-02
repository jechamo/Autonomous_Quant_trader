"""``python -m services.launcher`` (or double-click ``AQT.cmd``): menu → launch → back to menu."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from aqt.common.config import load_dotenv
from rich.console import Console
from rich.panel import Panel

from services.launcher.app import LauncherApp
from services.launcher.catalog import Value, readiness

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    os.chdir(ROOT)
    load_dotenv()  # only to know which keys exist; values are never shown
    console = Console()
    memory: dict[str, dict[str, Value]] = {}
    while True:
        args = LauncherApp(readiness(), memory).run()
        if not args:
            console.print("[grey50]Hasta luego.[/]")
            return
        console.print(
            Panel(
                "python -m services.trader " + " ".join(args)
                + "\n\n[grey50]Ctrl+C para pararlo y volver al menú.[/]",
                title="Arrancando", border_style="green",
            )
        )  # fmt: skip
        proc = subprocess.Popen([sys.executable, "-m", "services.trader", *args], cwd=ROOT)
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.wait()  # the child got Ctrl+C too and shuts down in order
        try:
            input("\nPulsa Enter para volver al menú…")
        except (KeyboardInterrupt, EOFError):
            return


if __name__ == "__main__":
    main()
