import sys

from services.trader.cli import app

# Windows consoles/pipes default to cp1252; never crash on a non-ASCII character in output.
for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")

app()
