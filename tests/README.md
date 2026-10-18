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
uv sync --locked --group dev
```

Run the full suite with:

```bash
uv run pytest -q
```

Run the complete local/CI gate with `make validate` (locked sync, local pre-commit hooks, and pytest). Hooks use Ruff and Mypy from `uv.lock`; use `make format` to apply formatting.

Regression coverage includes control-flow traversal, duplicate symbol identities, physical lines and encoding, Markdown fences/links, MCP stdio recovery and argument validation, safe replacement selection, filesystem errors, atomic output, and strict retrieval inputs. Filesystem fault injection is deterministic and does not require root privileges or external indexes.

The current artifact contracts are AST v3 and code-units v6. Tests validate real exports and golden fixtures against fully closed schemas, including parser-specific attribute/metric objects, recursive children, statistics, failures, and metadata. Mutation tests reject missing, renamed, and unknown fields. Historical validation reports describe their recorded generations rather than the current contract.

MCP tests cover protocol 2025-06-18, identical native `structuredContent` and compact JSON text, the object wrapper for inline NDJSON, and every declared output-schema branch. File-mode tests check exact receipt fields and hashes, overwrite permissions, source/stdio/symlink protections, failure preservation, and subsequent-request recovery. Comparison validates `top_k` before reading input.

Retrieval tests preserve raw selected items while checking `context.text` and provenance segments from both public bundle helpers. They exercise real nested Python/Markdown exports, physical-line overlap, separate provenance groups, residual module ranges, conflicting coordinates, and token estimates based on rendered characters.

Cleanup tests copy the helper into temporary fixture repositories. They verify bytecode removal, retained virtual environments with custom names, symlink target preservation, exact build-output boundaries, and refusal before any deletion when a removal tree contains protected metadata or an environment. Tests do not run cleanup against the working repository.

Output transport tests use real child processes and pipes, with both buffered small output and a consumer closing after a prefix of large output. They also inject permission/replacement errors in child processes and check one diagnostic plus destination preservation. AST tests reject malformed nested children and cover both layouts in both formats. Markdown tests distinguish indented code from paragraph/list continuations, including tabs; architecture tests inspect internal imports across all source layers.

Golden fixtures normalize the repository root and snapshot marker; syntax errors already emit relative paths. The code-units fixture explicitly uses `--repo-key cli_repo`; it contains a deliberate syntax failure and therefore has `replace_scope: false`. Regenerate from the real CLI using the normalization helpers in `test_cli_contract.py`, then review the diff and validate against the schemas.

Useful targeted contract checks:

```bash
uv run pytest -q tests/integration/test_cli_contract.py
uv run pytest -q tests/integration/test_mcp_server.py
uv run pytest -q tests/integration/test_artifact_schemas.py
uv run pytest -q tests/integration/test_output_transport.py
uv run pytest -q tests/unit/test_clean_artifacts.py
uv run pytest -q tests/unit/utils/test_retrieval_profiles.py
```
