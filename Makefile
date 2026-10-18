.PHONY: test lint type format validate clean repogpt

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
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

repogpt:
	uv run --locked repogpt $(ARGS)
