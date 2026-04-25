# RepoGPT

RepoGPT turns a source tree into deterministic structural artifacts for humans, automation, and LLM-oriented tooling.

Primary public interfaces today:

- CLI: `repogpt`
- MCP stdio server: `repogpt-mcp`

Runtime pipeline:

```text
[Collector] -> [Loader] -> [Parser] -> [Projector] -> [Writer]
     |            |           |            |             |
   paths      bytes/text   CodeNode IR   AST / code-units   file / stdout
```

Key properties:

- Supported languages in the current contract: Python (`.py`) and Markdown (`.md`)
- Public artifact contracts: AST JSON/NDJSON (`schema_version: "1"`) and `code-units` JSON (`schema_version: "4"`)
- Deterministic collection, projection, and snapshot-scoped identifiers
- Structured logs on STDERR, artifact data on STDOUT or file output
- Explicit partial-failure reporting with clean exit codes
- Retrieval profile helpers for `flat_rag_v1` and `structured_rag_v1`

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for contract and architecture details, and [ROADMAP.md](ROADMAP.md) for future work only.

## Installation

```bash
git clone https://github.com/Intrinsical-AI/RepoGPT.git
cd RepoGPT
uv sync
```

RepoGPT uses `uv` as the supported local and CI bootstrap path.
For development validation tools such as `pre-commit`, install the dev extra with `uv sync --extra dev`.

## Quick start

```bash
# analyze a repository and write AST JSON to a file
uv run repogpt path-to-project/ -o analysis.json

# stream AST NDJSON to stdout
uv run repogpt path-to-project/ --format ndjson --flatten file --stdout

# emit retrieval-oriented code-units JSON
uv run repogpt path-to-project/ --emit code-units --stdout

# compare the two built-in retrieval profiles over a code-units artifact
uv run python benchmark_retrieval_profiles.py code_units.json "helper"
```

## CLI reference

| Flag | Default | Description |
| --- | --- | --- |
| `--emit {ast,code-units}` | `ast` | `ast` emits the structural export. `code-units` emits the retrieval-oriented projection. |
| `--flatten {node,file}` | `node` | AST only. `node` emits every node; `file` emits only the root node per file. |
| `--format {json,ndjson}` | `json` | AST supports `json` and `ndjson`. `code-units` supports `json` only. |
| `--stdout` | off | Write the artifact to STDOUT instead of a file. |
| `-o, --output PATH` | depends on projection | Defaults to `analysis.json` for AST and `code_units.json` for `code-units`. |
| `--languages "py,md"` | all supported parsers | Comma-separated, case-insensitive whitelist of enabled languages. |
| `--include-tests` | off | Include `tests/` directories and `test_*.py` / `test-*.py` files. |
| `--log-level {INFO,DEBUG}` | `INFO` | Structured log level for STDERR output. |
| `--fail-fast` | off | Stop on the first parse error and return exit code `1`. |

Notes:

- `--emit code-units` only supports `--format json`.
- Passing `-o /dev/stdout` behaves like `--stdout`.
- AST JSON uses `records`; `code-units` JSON uses `documents`.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All collected files parsed successfully. |
| `1` | `--fail-fast` stopped the run after the first parse error. |
| `2` | Partial run: one or more files failed, artifact still emitted. |
| `3` | Invalid repository path or unrecoverable runtime error. |

Without `--fail-fast`, runs return `0` or `2`, never `1`.

## Collection and skip rules

RepoGPT collects files with deterministic pruned traversal plus stable relative-path ordering. The public artifact contains parsed files and parse failures; skipped files remain internal implementation detail.

Built-in ignores are always excluded:

`.git`, `.hg`, `.svn`, `__pycache__`, `.venv`, `venv`, `env`, `.mypy_cache`, `.pytest_cache`, `dist`, `build`, `node_modules`, `.tox`, `.DS_Store`, `.idea`, `.vscode`

Additional collection rules:

- `.repogptignore` uses gitignore-style matching via `pathspec`
- ignored directories are pruned before descent and are not expanded into per-file skips
- test paths are skipped unless `--include-tests` is set
- files larger than `2_000_000` bytes are skipped
- symlinks are skipped
- likely binary files are skipped
- unsupported extensions are skipped before parsing

Hidden files and directories are not excluded by default unless they match one of the built-in ignores or a `.repogptignore` rule.

Example `.repogptignore`:

```gitignore
# generated documentation
docs/build/

# large assets
*.png
*.pdf
```

## Artifact contracts

### AST export (`schema_version: "1"`)

AST export is the direct structural projection of the internal `CodeNode` tree.

- JSON payload keys: `schema_version`, `repo_root`, `stats`, `failures`, `records`
- NDJSON record types: `node`, `failure`, `summary`
- failure records include file digest information and parser error text

### Code-units (`schema_version: "4"`)

`code-units` is the retrieval-oriented projection for downstream indexing and lightweight structured expansion.

Top-level payload fields:

- `schema_version`
- `kind`
- `repo_key`
- `snapshot_id`
- `scope`
- `replace_scope`
- `stats`
- `failures`
- `documents`

Each document exposes retrieval-facing fields at the top level and duplicates them under `metadata` for generic import flows. Key fields include:

- `external_id`
- `source_id`
- `qualified_name`
- `unit_level`
- `container_id`
- `depth`
- `ancestor_path`
- `content_hash`
- `docstring_present`
- `has_children`

Contract notes:

- `external_id` is the semantic public identifier for a projected document
- `snapshot_id` is a repository-snapshot marker derived from collected file hashes
- `content_hash` is `sha256(content)` for the exact emitted span
- if a file produces no selected units for its language, the projector falls back to the root module document

## MCP interface

RepoGPT ships a compact MCP server over stdio:

```bash
uv run repogpt-mcp
# or
uv run python -m repogpt.mcp_server
```

Transport and envelope:

- protocol: line-delimited JSON-RPC over stdio
- initialization: `initialize`
- tool discovery: `tools/list`
- tool execution: `tools/call`
- tool results are returned as JSON text content inside the JSON-RPC response

Built-in tools:

- `repogpt_emit_code_units`
- `repogpt_emit_ast`
- `repogpt_compare_profiles`

Tool behavior summary:

- `repogpt_emit_code_units` returns `{"exit_code", "artifact", "stderr"}`
- `repogpt_emit_ast` returns `{"exit_code", "artifact", "stderr"}`
- `repogpt_compare_profiles` returns `{"exit_code", "comparison", "stderr"}`

`repogpt_compare_profiles` expects a path to an existing `code-units` artifact on disk.

Minimal request example:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
```

## Retrieval profiles and benchmark path

RepoGPT includes a small benchmark path for comparing two retrieval presets over a `code-units` artifact:

- `flat_rag_v1`: rank documents and return the top `k` seeds without expansion
- `structured_rag_v1`: rank documents, keep the same seeds, then add at most one enclosing container hop per seed when available

The benchmark path is intended for contract-level comparison, not as a full retrieval engine or production-quality relevance evaluation.

## Logging and diagnostics

RepoGPT keeps data and logs separate:

- artifact data -> STDOUT or output file
- logs -> STDERR

Example log lines:

```text
2026-03-24 02:45:04 [info     ] starting run                   format=json repo=/abs/path/to/repo
2026-03-24 02:45:04 [error    ] parse error                    path=bad.py error='File "/abs/path/to/repo/bad.py", line 1

    def broken(:

               ^

SyntaxError: invalid syntax'
```

## Development workflow

### Pre-commit vs full validation

`pre-commit` is a fast local quality gate. In this repository it covers:

- `ruff-format`
- `ruff`
- `mypy`

It does not run `pytest`. Run the test suite separately before pushing or opening a PR.

Setup and common commands:

```bash
uv sync --extra dev
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest -q
```

### Make targets

| Target | Command | Description |
| --- | --- | --- |
| `make lint` | `uv run ruff check .` | Lint the codebase |
| `make type` | `uv run mypy src tests` | Run type checks |
| `make test` | `uv run pytest -q` | Run the test suite |
| `make clean` | cleanup helpers | Remove Python cache artifacts |

## Project layout

```text
src/repogpt/
  adapters/
    fs/
    parsers/
    projectors/
    writers/
  application/
  app/
  domain/
  ports/
  utils/
  mcp_server.py
  runtime.py
tests/
docs/
```

High-level responsibilities:

- `runtime.py` wires the shared analysis runtime
- `app/cli.py` exposes the CLI entry point
- `mcp_server.py` exposes the MCP stdio server
- `adapters/` contains filesystem, parser, projector, and writer implementations
- `application/` contains use-case orchestration and exit-code policy
- `domain/` contains analysis, file, node, and error models

## Tests

Run the full suite with:

```bash
uv run pytest -q
```

Relevant coverage areas:

- collector behavior and skip rules
- Python and Markdown parser behavior
- AST and `code-units` contract stability
- CLI exit codes and partial-failure semantics
- MCP parity with CLI outputs

Targeted integration checks:

```bash
uv run pytest -q tests/integration/test_cli_contract.py
uv run pytest -q tests/integration/test_mcp_server.py
```

## Additional documents

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): current architecture, public contracts, interfaces, and invariants
- [docs/CHALLENGES.md](docs/CHALLENGES.md): open design questions and tradeoffs, not a committed roadmap
- [ROADMAP.md](ROADMAP.md): future work after the current shipped baseline

## License

[MIT](LICENSE)
