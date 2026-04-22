# Test Suite Notes

This directory mixes unit tests, integration tests, golden payloads, and parser fixtures.

Current layout:

- `tests/unit/`: focused tests for adapters, application logic, runtime wiring, and utilities
- `tests/integration/`: CLI and MCP contract coverage
- `tests/golden/`: stable payload fixtures for public artifact contracts
- `tests/data/`: parser-oriented sample files and edge cases
- `tests/fixtures/`: small fixture repositories for end-to-end contract tests

Run the full suite with:

```bash
uv run pytest -q
```
