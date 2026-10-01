.PHONY: install lint format typecheck test check research

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check . --fix

typecheck:
	uv run mypy

test:
	uv run pytest --cov --cov-report=term-missing

check: lint typecheck test

research:
	uv run python -m services.research.cli run --symbol SPY --timeframe 1d --strategy momentum
