.PHONY: test lint type clean repogpt

lint:
	ruff check .

type:
	mypy src tests

test:
	pytest -q

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

repogpt:
	python -m repogpt.app.cli
