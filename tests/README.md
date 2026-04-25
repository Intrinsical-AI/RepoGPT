# Test Suite Notes

This directory mixes unit tests, integration tests, golden payloads, and parser fixtures.

Current layout:

- `tests/unit/`: focused tests for adapters, application logic, runtime wiring, and utilities
- `tests/integration/`: CLI, MCP, and public schema contract coverage
- `tests/golden/`: stable payload fixtures for public artifact contracts
- `tests/data/`: parser-oriented sample files and edge cases
- `tests/fixtures/`: small fixture repositories for end-to-end contract tests

Install the dev environment before running the full suite; schema validation tests use the dev-only `jsonschema` dependency.

```bash
uv sync --extra dev --locked
```

Run the full suite with:

```bash
uv run pytest -q
```

Useful targeted contract checks:

```bash
uv run pytest -q tests/integration/test_cli_contract.py
uv run pytest -q tests/integration/test_mcp_server.py
uv run pytest -q tests/integration/test_artifact_schemas.py
```
