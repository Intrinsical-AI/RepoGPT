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

Run the complete local/CI gate with `make validate` (locked sync, local pre-commit hooks, and pytest). Hooks use Ruff and Mypy from `uv.lock`; use `make format` to apply formatting.

Regression coverage includes control-flow traversal, duplicate symbol identities, physical lines and encoding, Markdown fences/links, MCP stdio recovery and argument validation, safe replacement selection, filesystem errors, atomic output, and strict retrieval inputs. Filesystem fault injection is deterministic and does not require root privileges or external indexes.

Output transport tests use real child processes and pipes, with both buffered small output and a consumer closing after a prefix of large output. They also inject permission/replacement errors in child processes and check one diagnostic plus destination preservation. AST tests reject malformed nested children and cover both layouts in both formats. Markdown tests distinguish indented code from paragraph/list continuations, including tabs; architecture tests inspect internal imports across all source layers.

Golden fixtures normalize the repository root, traceback path, and snapshot marker. The code-units fixture explicitly uses `--repo-key cli_repo`; it contains a deliberate syntax failure and therefore has `replace_scope: false`. Regenerate from the real CLI using the normalization helpers in `test_cli_contract.py`, then review the diff and validate against the schemas.

Useful targeted contract checks:

```bash
uv run pytest -q tests/integration/test_cli_contract.py
uv run pytest -q tests/integration/test_mcp_server.py
uv run pytest -q tests/integration/test_artifact_schemas.py
uv run pytest -q tests/integration/test_output_transport.py
```
