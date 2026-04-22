.PHONY: test lint type clean repogpt

lint:
	uv run ruff check .

type:
	uv run mypy src tests

test:
	uv run pytest -q

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

repogpt:
	uv run repogpt
