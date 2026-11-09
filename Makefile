.PHONY: sync sync-hooks install-hooks pre-commit test lint type format validate build smoke-package clean distclean repogpt

ARGS ?= --help
DIST_DIR ?= dist
PACKAGE_EVIDENCE_DIR ?= $(DIST_DIR)/package-evidence
UV ?= uv
HOOK_ENV ?= $(CURDIR)/.cache/hooks-env
HOOK_PYTHON ?= 3.12
PRE_COMMIT_HOME ?= $(CURDIR)/.cache/pre-commit
override DEV_UV_PROJECT_ENVIRONMENT := $(if $(UV_PROJECT_ENVIRONMENT),$(UV_PROJECT_ENVIRONMENT),$(CURDIR)/.venv)
PRE_COMMIT := PRE_COMMIT_HOME="$(PRE_COMMIT_HOME)" uv run --no-project --no-sync --python "$(HOOK_ENV)/bin/python" python -m pre_commit

lint:
	$(UV) run --locked --group dev --extra mcp ruff check .

type:
	$(UV) run --locked --group dev --extra mcp mypy src tests scripts benchmark_*.py

test:
	$(UV) run --locked --group dev --extra mcp pytest -q

format:
	$(UV) run --locked --group dev ruff format .

sync:
	$(UV) sync --locked --group dev --extra mcp

sync-hooks:
	$(UV) run --no-project --no-sync --python "$(HOOK_PYTHON)" python -c 'from pathlib import Path; import sys; source, hooks = (Path(value).resolve() for value in sys.argv[1:]); overlap = source == hooks or source in hooks.parents or hooks in source.parents; sys.exit("HOOK_ENV must be separate from the source environment") if overlap else None' "$(DEV_UV_PROJECT_ENVIRONMENT)" "$(HOOK_ENV)"
	UV_PROJECT_ENVIRONMENT="$(HOOK_ENV)" $(UV) sync --locked --only-group hooks --python "$(HOOK_PYTHON)"

install-hooks: sync-hooks
	$(PRE_COMMIT) install --install-hooks

pre-commit: install-hooks
	$(MAKE) sync
	$(PRE_COMMIT) run --all-files

validate: install-hooks
	$(MAKE) sync
	$(PRE_COMMIT) run --all-files
	$(UV) run --locked --group dev --extra mcp pytest -q

build:
	$(UV) build --out-dir "$(DIST_DIR)"

smoke-package:
	$(UV) run --frozen --no-sync python scripts/smoke_package.py --dist-dir "$(DIST_DIR)" --receipt-dir "$(PACKAGE_EVIDENCE_DIR)"

clean:
	$(UV) run --locked --no-sync python scripts/clean_artifacts.py

distclean:
	$(UV) run --locked --no-sync python scripts/clean_artifacts.py --dist

repogpt:
	$(UV) run --locked repogpt $(ARGS)
