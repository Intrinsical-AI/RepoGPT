# RepoGPT

RepoGPT turns a source tree into deterministic structural artifacts for humans, automation, and LLM-oriented tooling.

Primary public interfaces today:

- CLI: `repogpt`
- MCP stdio server: `repogpt-mcp`

Runtime pipeline:

```text
[Collector] -> [Loader] -> [Parser] -> [Projector]
     |            |           |            |
   paths      bytes/text   CodeNode IR   AST / code-units
                                           |
                                  CLI writer / MCP result
```

Key properties:

- Supported languages in the current contract: Python (`.py`) and Markdown (`.md`)
- Public artifact contracts: AST JSON/NDJSON (`schema_version: "2"`) and `code-units` JSON (`schema_version: "5"`)
- Deterministic collection, origin-based internal node IDs, and semantic code-unit IDs
- Structured logs on STDERR, artifact data on STDOUT or file output
- Explicit partial-failure reporting with clean exit codes
- Retrieval profile helpers for `flat_rag_v2` and `structured_rag_v2`

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for contract and architecture details, and [ROADMAP.md](ROADMAP.md) for future work only.

The current source tree introduces breaking AST v2 and code-units v5 contracts. Earlier artifacts must be regenerated and downstream indexes reingested; there are no compatibility aliases or v4 readers in this contract.

## Installation

```bash
git clone https://github.com/Intrinsical-AI/RepoGPT.git
cd RepoGPT
uv sync
```

RepoGPT uses `uv` as the supported local and CI bootstrap path.
For development validation tools such as `pre-commit`, `mypy`, and schema tests, install the dev extra with `uv sync --extra dev --locked`.

## Quick start

```bash
# analyze a repository and write AST JSON to a file
uv run repogpt path-to-project/ -o analysis.json

# stream AST NDJSON to stdout
uv run repogpt path-to-project/ --format ndjson --flatten file --stdout

# emit retrieval-oriented code-units JSON
uv run repogpt path-to-project/ --emit code-units --stdout

# request a complete replacement artifact with a portable repository identity
uv run repogpt path-to-project/ --emit code-units --repo-key my-project --include-tests --replace-scope -o code_units.json

# compare the two built-in retrieval profiles over a code-units artifact
uv run python benchmark_retrieval_profiles.py code_units.json "helper"
```

## CLI reference

| Flag | Default | Description |
| --- | --- | --- |
| `--emit {ast,code-units}` | `ast` | `ast` emits the structural export. `code-units` emits the retrieval-oriented projection. |
| `--flatten {node,file}` | `node` | AST only. `node` emits every node as a flat record; `file` emits one root record per file containing its complete nested subtree. |
| `--format {json,ndjson}` | `json` | AST supports `json` and `ndjson`. `code-units` supports `json` only. |
| `--stdout` | off | Write the artifact to STDOUT instead of a file. |
| `-o, --output PATH` | depends on projection | Defaults to `analysis.json` for AST and `code_units.json` for `code-units`. |
| `--languages "py,md"` | all supported parsers | Comma-separated, case-insensitive whitelist of enabled languages. |
| `--include-tests` | off | Include test paths and filenames described under collection rules. |
| `--log-level {INFO,DEBUG}` | `INFO` | Structured log level for STDERR output. |
| `--fail-fast` | off | Stop on the first parse error and return exit code `1`. |
| `--repo-key KEY` | derived from canonical absolute path | Code-units only. Explicit portable identity matching `[a-z0-9][a-z0-9._-]{0,127}`. |
| `--replace-scope` | off | Code-units only. Require a complete, non-empty export suitable for scope replacement. |

Notes:

- `--emit code-units` only supports `--format json`.
- An explicit `--flatten` with `--emit code-units` is rejected.
- `--stdout` and `-o` are mutually exclusive, including `--stdout -o /dev/stdout`.
- Passing `-o /dev/stdout` behaves like `--stdout`.
- AST JSON uses `records`; `code-units` JSON uses `documents`.
- `--languages` accepts parser extensions such as `py` and `md`; values are normalized case-insensitively.
- Unsupported language values and blank repository paths fail during argument validation.
- Passing an empty language filter, such as `--languages ""`, collects no files.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All collected files parsed successfully, or the STDOUT consumer closed its pipe early. |
| `1` | `--fail-fast` stopped the run after the first parse error. |
| `2` | Invalid arguments (no artifact), or per-file parse/decode failures with an emitted artifact. |
| `3` | Invalid repository, collection/read/write failure, or refused scope replacement. |

Parse/decode failures normally emit an artifact and return `2`, or `1` with `--fail-fast`. An explicit replacement request takes precedence: incomplete results return `3` without emitting an artifact. Collection and input-read failures also return `3` before any output. File output is written to a temporary file in the destination directory, then atomically replaced; a failed write preserves the prior artifact. Existing file permissions are retained, while new files follow the process umask.

Closing a pipe early, as with `repogpt ... --stdout | head -c 200`, returns `0` without a write-error diagnostic or shutdown traceback. This status acknowledges the consumer's early close; it does not certify delivery of a complete artifact or a complete analysis. Other output I/O errors return `3` with one destination-specific diagnostic.

## Collection and skip rules

RepoGPT collects files with deterministic pruned traversal plus stable relative-path ordering. The public artifact contains parsed files and parse failures; skipped files remain internal implementation detail.

Built-in ignores are always excluded:

`.git`, `.hg`, `.svn`, `__pycache__`, `.venv`, `venv`, `.mypy_cache`, `.pytest_cache`, `node_modules`, `.tox`, `.DS_Store`, `.idea`, `.vscode`

Additional collection rules:

- `.repogptignore` uses gitignore-style matching via `pathspec`
- ignored directories are pruned before descent and recorded once, without per-file skips
- `test/`, `tests/`, `test_*`, `test-*`, `*_test.py`, and `conftest.py` paths are skipped unless `--include-tests` is set
- files larger than `2_000_000` bytes are skipped
- symlinks are skipped
- likely binary files are skipped
- unsupported extensions and supported languages excluded by `--languages` have distinct skip reasons

The test-name rule is case-sensitive. `env/`, `build/`, and `dist/` are indexable unless excluded in `.repogptignore`; this repository explicitly excludes its own generated copies there. A directory containing a regular `pyvenv.cfg` is pruned as a virtual environment regardless of its name. RepoGPT does not read `.gitignore`.

A missing `.repogptignore` is allowed. An existing file that cannot be read or parsed aborts collection; its exclusions are never silently disabled. Traversal, stat, binary-probe, and source-read errors also abort the run.

Hidden files and directories are not excluded by default unless they match one of the built-in ignores or a `.repogptignore` rule.

Example `.repogptignore`:

```gitignore
# generated documentation
docs/build/

# repository-local environments and generated copies
/env/
/build/
/dist/

# large assets
*.png
*.pdf
```

## Artifact contracts

### AST export (`schema_version: "2"`)

AST export is the direct structural projection of the internal `CodeNode` tree.

- JSON payload keys: `schema_version`, `repo_root`, `stats`, `failures`, `records`
- NDJSON record types: `node`, `failure`, `summary`
- failure records include file digest information and parser error text

Both JSON and NDJSON support both AST layouts. Nested `children` in `--flatten file` are recursively validated nodes, without the `record_type`, `schema_version`, or `file` wrapper fields of a top-level record.

Every node includes a zero-based `start_column` in original source characters. Internal node IDs derive from relative path, node type, `start_line`, and `start_column`; changing an ending span or parent ID alone does not change an ID. Moving a declaration or editing text before it on the same line can change its ID.

Decorated Python declarations begin at the first `@` token, including multiline decorators. Exports made with the earlier expression-based origin may have incorrect spans and IDs for multiline decorators; regenerate affected exports. The AST v2 and code-units v5 formats remain unchanged.

Python decoding honors UTF-8 BOMs and encoding cookies, with strict decoding and failures retaining the original byte digest. Spans and comment positions use physical LF, CRLF, or CR lines; other Unicode separators do not add lines. Python traversal includes control-flow branches, exception handlers, finalizers, and match cases. Import attributes include the integer `import_level` (`0` for absolute imports).

Python comment text removes one leading `#` and trims leading spaces and trailing whitespace; further `#` characters are preserved. Tags are parser-specific: Markdown tags its module with `TODO`/`FIXME` found in HTML comments; Python exposes comments without deriving these tags. Python signatures are structural summaries, not a source-formatting or PEP 8 contract.

Markdown fences accept three or more backticks or tildes, up to three leading spaces, and close only with the same character, sufficient length, and trailing spaces/tabs. Headings, links, and HTML comments inside fences are not extracted. ATX headings allow up to three leading spaces, list-item headings, empty titles, and optional closing hashes. Link extraction skips complete inline code spans within recognized text blocks, including spans across physical lines, as well as image links; source columns remain character offsets in the original line.

Links in indented code are suppressed, using four-column tab stops and indentation relative to list content. Indentation within a continuing paragraph remains prose. This filtering adds no nodes for indented blocks: `code_block` nodes and their count still describe fences. The maintained Markdown parser is a structural subset, not a complete CommonMark renderer.

### Code-units (`schema_version: "5"`)

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

Each document exposes retrieval-facing fields at the top level. `metadata` contains only file digest, tags, parser attributes, and dependencies. Key fields include:

- `external_id`
- `source_id`
- `qualified_name`
- `unit_level`
- `container_id`
- `depth`
- `ancestor_path`
- `content_hash`
- `content_ranges` on module documents
- `docstring_present`
- `has_children`

Contract notes:

- `external_id` is the semantic public identifier for a projected document
- `snapshot_id` is a repository-snapshot marker derived from collected file hashes
- `content_hash` is `sha256(content)` for the exact emitted text. Non-module content is the exact physical-line span; module content concatenates only lines outside selected non-module spans.
- Every parsed file emits a module document. Its `content_ranges` lists those residual physical-line intervals in order; an empty list and empty `content` are valid for a structural module. Its `start_line` and `end_line` bound the file, not the residual text.
- Every non-module `container_id` resolves to its nearest emitted ancestor. Empty structural modules remain in the artifact but are not retrieval seeds or expansion results.

Repository identity and replacement:

- Automatic `repo_key` is `local-` plus the full SHA-256 of the OS-normalized, resolved absolute repository path. Symlink aliases resolve to the same identity; independent clones and moved repositories get different identities.
- Use the same explicit `--repo-key` across clones to share an identity. Keys are validated without normalization. Scope is always `repogpt:{repo_key}`.
- `replace_scope` defaults to `false`, including empty and partial exports. `--replace-scope` requires `--include-tests` and all supported languages, a non-empty document list, no parse/decode failures, no early stop, and no eligible files omitted by size or binary guards. Known ignore rules and symlink exclusions delimit the collection universe.

Markdown decoding uses strict UTF-8 with an optional BOM. Invalid bytes produce
a decode failure and prevent scope replacement rather than silently changing
the source text. The RAG v5 consumer separately limits nonblank imported units
to 20,000 characters, external IDs to 512 characters, source IDs to 1,024
characters, and snapshots to 5,000 nonblank documents. A valid RepoGPT artifact
can exceed those consumer limits and be refused before import.
- Repeated Python declarations receive `~2`, `~3`, etc. in their qualified names and IDs, including descendants of repeated containers. `symbol` retains the source name.
- Markdown headings reserve natural sibling slugs: `A`, `A`, `A-2` becomes `a`, `a-3`, `a-2`. Qualified names, IDs, containers, and ancestry use the same assignment. Residual internal or external ID collisions abort emission.
- Preamble code fences use the reserved `@module` section, independently of a literal `# Root` heading. This changes their previous `root` IDs; see the regeneration guidance in [CHANGELOG.md](CHANGELOG.md).

### Public JSON Schemas

RepoGPT ships JSON Schema files for the public artifact contracts:

- `src/repogpt/schemas/ast-v2.schema.json`: AST JSON envelopes and AST NDJSON record variants
- `src/repogpt/schemas/code-units-v5.schema.json`: `code-units` JSON envelopes

Both schemas are included in the wheel and source distribution. Installed code can read them with `importlib.resources.files("repogpt").joinpath("schemas").joinpath(schema_name).read_text(encoding="utf-8")`. These schemas are contract aids for consumers and tests. They are validated against golden fixtures in the test suite via the dev-only `jsonschema` dependency; RepoGPT does not validate emitted artifacts at runtime.

## MCP interface

RepoGPT ships a compact MCP server over stdio:

```bash
uv run repogpt-mcp
# or
uv run python -m repogpt.mcp_server
```

Transport and envelope:

- protocol: line-delimited JSON-RPC over stdio
- initialization: `initialize`, returning `protocolVersion: "2024-11-05"` and `serverInfo`
- server version: `serverInfo.version`, derived from package metadata
- tool discovery: `tools/list`
- tool execution: `tools/call`
- tool results are returned as JSON text content inside the JSON-RPC response

Built-in tools:

- `repogpt_emit_code_units`
- `repogpt_emit_ast`
- `repogpt_compare_profiles`

Tool behavior summary:

- `repogpt_emit_code_units` returns the code-units artifact as JSON text.
- `repogpt_emit_ast` returns the AST envelope, or an array of NDJSON records, as JSON text.
- `repogpt_compare_profiles` returns the comparison as JSON text.

Tool arguments:

| Tool | Arguments |
| --- | --- |
| `repogpt_emit_code_units` | `repo_path` required; optional `include_tests`, `languages`, `fail_fast`, `repo_key`, `replace_scope` |
| `repogpt_emit_ast` | `repo_path` required; optional `flatten`, `format`, `include_tests`, `languages`, `fail_fast` |
| `repogpt_compare_profiles` | `artifact_path` and `query` required |

`languages` is an array of parser extensions such as `["py", "md"]`; values are normalized like the CLI. An empty array collects no files. Unsupported values return a JSON-RPC tool error.

`repogpt_compare_profiles` expects a path to an existing `code-units` artifact on disk. Each tool returns an MCP result with `content` and `isError`; the JSON text directly contains the artifact or comparison, without CLI exit codes or an extra payload envelope. Tool execution failures set `isError: true`. Partial and fail-fast artifacts remain available in the result and also set `isError: true`.

Required fields, unknown arguments, types, and enums are checked against the published tool schema; booleans are never coerced from strings or numbers. Invalid arguments use `-32602`, malformed JSON `-32700`, invalid envelopes `-32600`, and unknown methods `-32601`. Analysis failures and refused replacements use tool results with `isError: true`. Valid notifications receive no response and never dispatch tools. All entry-point logs go to STDERR; importing the MCP module does not configure logging. The session can handle subsequent requests after a failed request.

The wire-argument helper checks fields/types/enums; handlers apply shared semantic policies, including the `repo_key` pattern, before collection. Invalid envelopes without an `id` still receive `-32600` with `id: null`. Closing the server's STDOUT pipe ends the process cleanly with `0`; other stdio I/O failures return `3`.

Minimal request example:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
```

## Retrieval profiles and benchmark path

RepoGPT includes a small benchmark path for comparing two retrieval presets over a `code-units` artifact:

- `flat_rag_v2`: rank matching, retrievable documents and return the top `k` seeds without expansion
- `structured_rag_v2`: keep the same seeds, then add at most one enclosing retrievable container hop per seed when available

The benchmark path is intended for contract-level comparison, not as a full retrieval engine or production-quality relevance evaluation.

`--top-k` accepts integers greater than or equal to zero; zero and queries without matches produce empty bundles. Ranking ignores empty structural modules, uses exact symbols only when present, and breaks score ties by shorter qualified name and then ascending external ID. The benchmark and MCP comparison share one artifact loader that requires a code-units v5 envelope, validates the fields used by retrieval, and rejects malformed entries and duplicate `external_id` values.

## Developer benchmark scripts

RepoGPT includes two root-level diagnostic scripts:

- `benchmark_retrieval_profiles.py`: compares `flat_rag_v2` and `structured_rag_v2` over a `code-units` artifact
- `benchmark_tree_utils.py`: runs synthetic measurements for tree traversal, flattening, and Python comment association

These scripts are developer diagnostics, not public runtime interfaces.

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

Local hooks invoke the Ruff and Mypy versions in `uv.lock`; they do not install separate tool versions. Formatting is checked without modifying files. Hooks do not run `pytest`; `make validate` runs the locked environment sync, hooks, and full test suite, and is also the CI command.

Setup and common commands:

```bash
uv sync --extra dev --locked
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest -q
```

### Make targets

| Target | Command | Description |
| --- | --- | --- |
| `make lint` | `uv run --locked --extra dev ruff check .` | Lint the codebase |
| `make type` | `uv run --locked --extra dev mypy src tests` | Run type checks |
| `make test` | `uv run --locked --extra dev pytest -q` | Run the test suite |
| `make format` | `uv run --locked --extra dev ruff format .` | Apply formatting |
| `make validate` | locked sync, hooks, pytest | Run the local and CI gate |
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
  schemas/
tests/
docs/
benchmark_retrieval_profiles.py
benchmark_tree_utils.py
```

High-level responsibilities:

- `runtime.py` wires the shared analysis runtime; `AnalyzeRepo.run(request)` returns `(result, projection)` after validation and does not write output
- `app/cli.py` exposes the CLI entry point and sends the returned projection to the file/stdout writer
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
- public schema validation against golden artifacts
- CLI exit codes and partial-failure semantics
- MCP parity with CLI outputs

Targeted integration checks:

```bash
uv run pytest -q tests/integration/test_cli_contract.py
uv run pytest -q tests/integration/test_mcp_server.py
uv run pytest -q tests/integration/test_artifact_schemas.py
```

## Additional documents

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): current architecture, public contracts, interfaces, and invariants
- [docs/CHALLENGES.md](docs/CHALLENGES.md): open design questions and tradeoffs, not a committed roadmap
- [ROADMAP.md](ROADMAP.md): future work after the current shipped baseline

## License

[MIT](LICENSE)
