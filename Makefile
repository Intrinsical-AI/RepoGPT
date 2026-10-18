.PHONY: test lint type format validate clean distclean repogpt

ARGS ?= --help

lint:
	uv run --locked --group dev ruff check .

type:
	uv run --locked --group dev mypy src tests

test:
	uv run --locked --group dev pytest -q

format:
	uv run --locked --group dev ruff format .

validate:
	uv sync --locked --group dev
	uv run --locked --group dev pre-commit run --all-files
	uv run --locked --group dev pytest -q

clean:
	uv run --locked --no-sync python scripts/clean_artifacts.py

distclean:
	uv run --locked --no-sync python scripts/clean_artifacts.py --dist

repogpt:
	uv run --locked repogpt $(ARGS)
