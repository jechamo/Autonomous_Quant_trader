#!/usr/bin/env sh
# Autonomous Quant Trader - launch menu (macOS / Linux). PAPER only.
cd "$(dirname "$0")" || exit 1
exec uv run python -m services.launcher
