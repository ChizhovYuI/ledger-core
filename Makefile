.PHONY: install fmt lint test check replay failing

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

check: lint test
