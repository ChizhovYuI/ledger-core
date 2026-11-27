.PHONY: install fmt lint test check replay failing timing pdf

install:
	uv sync

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -m "not known_gap"

# The one intentional failing test (see README).
failing:
	uv run pytest -m known_gap

replay:
	uv run python -m ledger $(ARGS)

# Not in check: about 1 minute.
timing:
	PYTHONPATH=. uv run python scripts/timing.py

pdf:
	typst compile docs/part2.typ docs/part2.pdf

check: lint test
