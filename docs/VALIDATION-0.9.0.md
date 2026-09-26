# Local validation — 0.9.0

Verified on 2026-09-12, Linux, Python 3.12.13. Changes are in the working tree based on `19d6b15aa37f286e6ff1c8b408b64d9d381e4643`; this is local implementation evidence, not a published release or remote CI receipt.

## Plan coverage

| Area | Result | Regression evidence |
| --- | --- | --- |
| Python traversal and relative imports | All statement branches preserve declaration scopes and ordering; import levels remain distinct | [Semantic regressions](../tests/integration/test_semantic_regressions.py) |
| Identity collisions | Accessors, overloads, redeclarations, heading suffixes, and same-line links retain distinct identities; residual collisions abort emission | [Semantic regressions](../tests/integration/test_semantic_regressions.py), [export safety](../tests/integration/test_export_safety.py) |
| Source fidelity | Physical LF/CRLF/CR spans, UTF-8 BOM, encoding cookies, and strict Python decoding with original digests | [Semantic regressions](../tests/integration/test_semantic_regressions.py) |
| Markdown fences | Opening length/type and valid closure delimit headings and links correctly | [Semantic regressions](../tests/integration/test_semantic_regressions.py) |
| MCP | STDERR logging, notification silence, no tool dispatch for notifications, argument validation, distinct errors, and session recovery | [Transport tests](../tests/integration/test_mcp_transport.py), [CLI parity](../tests/integration/test_mcp_server.py) |
| Collection and output | Ignore/traversal/stat/probe/read errors abort before output; failed atomic writes retain the destination and clean their temporary files | [Export safety](../tests/integration/test_export_safety.py), [collector tests](../tests/unit/adapters/fs/test_collector.py) |
| Scope replacement | Canonical or explicit repository keys; replacement defaults false; explicit replacement rejects incomplete selectors or results before writing | [Export safety](../tests/integration/test_export_safety.py) |
| Retrieval and pruning | Shared v4 loader, no silent malformed-entry filtering, duplicate-ID rejection, non-negative `top_k`, one semantic name/ID traversal, unused helpers/stats removed | [Retrieval tests](../tests/unit/utils/test_retrieval_artifact.py), [migration notes](../CHANGELOG.md) |
| Artifact contracts | AST v1 and code-units v4 retained; refreshed goldens and fresh regression artifacts validate against their schemas | [Schema tests](../tests/integration/test_artifact_schemas.py) |

## Executed checks

`UV_CACHE_DIR=/tmp/uv-cache PRE_COMMIT_HOME=/tmp/repogpt-pre-commit make validate` passed:

- locked environment sync;
- pre-commit Ruff formatting, Ruff checks, and Mypy using `uv.lock`;
- **205 tests passed** (final run: 9.26 seconds).

`uv lock --check --offline` and `git diff --check` also passed. The existing CI matrix still selects Python 3.10, 3.11, and 3.12 and now uses `make validate`; the additional interpreters and remote CI were not executed in this local check.

The benchmark CLI returned `2` for `--top-k -1` before opening a nonexistent artifact, and returned two empty bundles for `--top-k 0` with a valid artifact.

## Installed artifact and consumer boundary

Built `repogpt-0.9.0-py3-none-any.whl` with SHA-256:

```text
4765acc09492af07d474817636210b4d6215eb974ed19e2c4deb7301697818a2
```

Installed that wheel with the lockfile runtime dependency versions into a new temporary environment. The smoke ran outside the checkout with `PYTHONPATH` and `PYTHONHOME` absent and asserted the package import origin under that environment's `site-packages`. All 39 Python package files in the wheel and installation matched the current source byte for byte.

Installed CLI/MCP checks covered version metadata, automatic/explicit identity, preserved duplicate declarations, AST NDJSON, complete replacement, partial export, refusal preserving an existing artifact, JSON-RPC recovery, notifications, STDERR logs, and retrieval comparison.

RAG's current `validate_canonical_import_payload` and `resolve_canonical_import_replace_scope` accepted two nine-document artifacts: complete with replacement true and partial with replacement false. Forcing replacement on the partial artifact was rejected. The checked consumer HEAD was `90dec4cecc7cc66800cb68ec4c9d15376909cf84`. Only pure validators ran; no import use case or index mutation was invoked. This bounded check does not establish that every possible RepoGPT artifact fits consumer limits such as non-blank content, document length, or batch size.

## Evidence and remaining observation

Local receipts and replay scripts are under `/tmp/repogpt-remediation-20260912/`: `validate.log`, `build.log`, `wheel-smoke.json`, `consumer-check.json`, `benchmark-check.json`, and `freshness.json`. The earlier audit's temporary directory was unavailable after resuming; these are fresh implementation checks, not a reconstruction of that audit receipt.

The successful wheel build still reports pre-existing Setuptools deprecations for `project.license` as a table, `tool.setuptools.license-files`, and the license classifier in [pyproject.toml](../pyproject.toml). Migrating those packaging metadata fields to SPDX is a separate remaining cleanup; the remediation above does not alter the MIT license or the build-backend minimum version.
