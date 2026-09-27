.PHONY: test lint type format validate clean repogpt

lint:
	uv run --locked --extra dev ruff check .

type:
	uv run --locked --extra dev mypy src tests

test:
	uv run --locked --extra dev pytest -q

format:
	uv run --locked --extra dev ruff format .

validate:
	uv sync --extra dev --locked
	uv run --locked pre-commit run --all-files
	uv run --locked pytest -q

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

repogpt:
	uv run repogpt
