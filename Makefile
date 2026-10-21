.PHONY: test lint type format validate clean distclean repogpt

ARGS ?= --help

lint:
	uv run --locked --group dev --extra mcp ruff check .

type:
	uv run --locked --group dev --extra mcp mypy src tests scripts benchmark_*.py

test:
	uv run --locked --group dev --extra mcp pytest -q

format:
	uv run --locked --group dev ruff format .

validate:
	uv sync --locked --group dev --extra mcp
	uv run --locked --group dev --extra mcp pre-commit run --all-files
	uv run --locked --group dev --extra mcp pytest -q

clean:
	uv run --locked --no-sync python scripts/clean_artifacts.py

distclean:
	uv run --locked --no-sync python scripts/clean_artifacts.py --dist

repogpt:
	uv run --locked repogpt $(ARGS)
