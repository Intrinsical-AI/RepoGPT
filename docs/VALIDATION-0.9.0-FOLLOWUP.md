# Follow-up validation — 0.9.0

Verified on 2026-09-12 with Linux and Python 3.12.13, on the working tree based on `19d6b15aa37f286e6ff1c8b408b64d9d381e4643`. This records the bounded follow-up to the review. The [first validation receipt](VALIDATION-0.9.0.md) is preserved unchanged; its wheel hash, test count, and packaging observations describe that earlier state.

## Delivered behavior

| Area | Result | Evidence |
| --- | --- | --- |
| CLI/MCP output | Early consumer close returns 0 during both write and buffered flush. Other output I/O errors retain 3 without a second shutdown failure. File errors have one contextual diagnostic and retain the previous artifact. | [Output transport](../tests/integration/test_output_transport.py), [atomic output](../tests/integration/test_export_safety.py) |
| CLI arguments | Conflicting output targets and explicit AST flattening on code-units fail with 2 before analysis; `/dev/stdout` remains an individual output alias. | [CLI contract](../tests/integration/test_cli_contract.py) |
| AST v1 | Both flat-node and whole-file-tree layouts remain available in JSON and NDJSON. Children are validated recursively; malformed children and grandchildren are rejected. | [Artifact schemas](../tests/integration/test_artifact_schemas.py) |
| MCP contract | Valid notifications remain silent; invalid envelopes without an ID return -32600. Invalid repository keys return -32602 before collection. | [MCP transport](../tests/integration/test_mcp_transport.py) |
| Source precision | Python comments retain hashes after the delimiter. Markdown suppresses links in indented code while retaining paragraph/list continuations and original link columns, including tabs. | [Text processing](../tests/unit/utils/test_text_processing.py), [Markdown parser](../tests/unit/adapters/parsers/test_md_parser.py) |
| Cleanup and architecture | Unused request/statistics fields are removed with migration notes; import sorting is enabled, pytest configuration is centralized, and source imports enforce the documented layer directions. | [Changelog](../CHANGELOG.md), [architecture tests](../tests/unit/test_architecture.py) |
| Packaging | SPDX metadata and license inclusion replace the deprecated declarations, with Setuptools >=77.0.3 for builds and unchanged runtime dependencies. | Build log and installed-package checks below |

The additional checks were exercised against the earlier behavior before fixing it: the first batch produced 20 expected failures, and the initial indented-code cases produced 12 expected failures. Subsequent targeted cases caught paragraph/list boundary mistakes and the non-pipe stdout shutdown error before the final gate.

## Final checks

`UV_CACHE_DIR=/tmp/uv-cache PRE_COMMIT_HOME=/tmp/repogpt-pre-commit make validate` passed on the final source:

- locked environment sync;
- pre-commit Ruff formatting, Ruff lint/import sorting, and strict Mypy;
- **257 tests passed in 19.33 seconds**, including the 205 existing tests and 52 additional cases.

`uv lock --check --offline` and `git diff --check` passed. The existing Python 3.10–3.12 CI matrix remains in place; only Python 3.12.13 was exercised locally. These checks do not claim remote CI or release publication.

AST v1/code-units v4 goldens and `uv.lock` are byte-identical to the starting working tree. The prior export-safety policy, retrieval loader, code-units projector, retained tree helper, and AST path fallback are also unchanged by this follow-up.

## Distribution and installed execution

`uv build --offline --out-dir <evidence>/dist` built an sdist and a wheel without deprecation warnings. SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| `repogpt-0.9.0-py3-none-any.whl` | `78d37ff24e52d5efb904427a18d7325b06220b7f18eb7206d9fac50f6c89d9c2` |
| `repogpt-0.9.0.tar.gz` | `49c9b6f5fe43f20333e19c7059e11ced5f9ec072d83574ea07ee7f06b413c027` |

The wheel was installed with uv into a new temporary environment using the lockfile runtime versions. Checks ran outside the checkout with `PYTHONPATH` and `PYTHONHOME` absent, and verified the import origin in that environment's `site-packages`.

All **40 Python package files** match the source byte for byte in the sdist, wheel, and installation. Both distributions contain the original MIT license. Wheel metadata contains `License-Expression: MIT` and `License-File: LICENSE`, without the deprecated license classifier.

Installed entrypoints passed both the earlier contract smoke and the new checks: identity/replacement safety, duplicate declarations, partial exports, AST layouts, Markdown/comment precision, rejected CLI combinations, MCP notification/error recovery and key validation, buffered/mid-write closed pipes, and non-pipe output failures retaining exit 3.

The earlier downstream RAG validator result remains historical evidence. This follow-up did not execute external imports, index replacement, or migration.

## Preservation and receipts

Evidence directory: `/tmp/repogpt-followup-20260912-vpqsw8l_/`.

- `before/`, `before.json`, `status-before.txt`, `head-before.txt`: copies/hashes of the 96 pre-existing working-tree files and Git baseline.
- `followup.diff`, `changes.json`, `freshness.json`: changes relative to that working tree and final preservation checks.
- `validate.log`, `validate-final.log`, `build.log`: local gate and build output.
- `runtime-requirements.txt`, `baseline_contract_smoke.py`, `followup_smoke.py`: installed-check inputs and scripts.
- `wheel-smoke.json`, `followup-smoke.json`, `dist/`: installed results and built distributions.

The previous `/tmp/repogpt-remediation-20260912/` evidence and its validation document were left intact. The only removed repository file is `pytest.ini`, whose setting moved to `pyproject.toml`; no broad cleanup was performed. Parser-specific tags, test-name selection, signature formatting, `all_comments`, and the reachable AST path fallback retain their established behavior.
