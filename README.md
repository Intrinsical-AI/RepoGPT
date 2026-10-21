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
                              CLI / MCP writer or result
```

Key properties:

- Supported languages in the current contract: Python (`.py`) and Markdown (`.md`)
- Public artifact contracts: AST JSON/NDJSON (`schema_version: "3"`) and `code-units` JSON (`schema_version: "6"`)
- Deterministic collection, origin-based internal node IDs, and semantic code-unit IDs
- Structured logs on STDERR, artifact data on STDOUT or file output
- Explicit partial-failure reporting with clean exit codes
- Retrieval profile helpers for `flat_rag_v3` and `structured_rag_v3`, with deduplicated model context

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for contract and architecture details, and [ROADMAP.md](ROADMAP.md) for future work only.

This source tree is **RepoGPT 0.11.0**. AST v3 and code-units v6 are breaking contracts: regenerate exports and update consumers together. The retrieval loader accepts code-units v6 only.

## Installation

```bash
git clone https://github.com/Intrinsical-AI/RepoGPT.git
cd RepoGPT
uv sync
```

RepoGPT uses `uv` as the supported local and CI bootstrap path.
For development validation tools such as `pre-commit`, `mypy`, and schema tests, install the dev dependency group with `uv sync --locked --group dev`.

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
| `--extensions "py,md"` | all supported parsers | Comma-separated, case-insensitive whitelist of enabled languages. |
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
- `--extensions` accepts parser extensions such as `py` and `md`; values are normalized case-insensitively.
- Unsupported language values and blank repository paths fail during argument validation.
- Passing an empty language filter, such as `--extensions ""`, collects no files.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All collected files parsed successfully, or the STDOUT consumer closed its pipe early. |
| `1` | `--fail-fast` stopped the run after the first parse error. |
| `2` | Invalid arguments (no artifact), or per-file parse/decode failures with an emitted artifact. |
| `3` | Invalid repository, collection/read/write failure, refused scope replacement, or internal consistency failure. |

Parse/decode failures normally emit an artifact and return `2`, or `1` with `--fail-fast`. An explicit replacement request takes precedence: incomplete results return `3` without emitting an artifact. Collection and input-read failures also return `3` before any output. File output is written to a temporary file in the destination directory, flushed and synchronized with `fsync`, then atomically replaced; a failed write preserves the prior artifact. Existing file permissions are retained, while new files follow the process umask.

Closing a pipe early, as with `repogpt ... --stdout | head -c 200`, returns `0` without a write-error diagnostic or shutdown traceback. This status acknowledges the consumer's early close; it does not certify delivery of a complete artifact or a complete analysis. Other output I/O errors return `3` with one destination-specific diagnostic.

Input I/O errors are reported as analysis failures; internal consistency failures have a dedicated diagnostic. Neither uses output-stream cleanup. The exit codes above apply to both cases.

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
- non-regular files are skipped with the internal reason `non_regular_file`
- likely binary files are skipped
- unsupported extensions and supported languages excluded by `--extensions` have distinct skip reasons

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

### AST export (`schema_version: "3"`)

AST export is the direct structural projection of the internal `CodeNode` tree.

- JSON payload keys: `schema_version`, `repo_root`, `stats`, `failures`, `records`
- NDJSON record types: `node`, `failure`, `summary`
- failure records include file digest information and parser error text

Both JSON and NDJSON support both AST layouts. Nested `children` in `--flatten file` are recursively validated nodes, without the `record_type`, `schema_version`, or `file` wrapper fields of a top-level record.

Every node includes a zero-based `start_column` in original source characters. Internal node IDs derive from relative path, node type, `start_line`, and `start_column`; changing an ending span or parent ID alone does not change an ID. Moving a declaration or editing text before it on the same line can change its ID.

Decorated Python declarations begin at the first `@` token, including multiline decorators.

Fields have one canonical location: imported names live in an import node's `dependencies`; a link's label is `name`, its URL is `attributes.url`, and its column is `start_column`; a module's relative filename is `path`. The duplicate import, link, and module attribute fields are absent from AST v3.

Python decoding honors UTF-8 BOMs and encoding cookies, with strict decoding and failures retaining the original byte digest. Spans and comment positions use physical LF, CRLF, or CR lines; other Unicode separators do not add lines. Python traversal includes control-flow branches, exception handlers, finalizers, and match cases. Import attributes include the integer `import_level` (`0` for absolute imports).

Python visibility follows naming conventions: names beginning and ending with `__`, including `__init__` and `__repr__`, are public; other double-leading-underscore names are private, and single-leading-underscore names are protected.

Python comment text removes one leading `#` and trims leading spaces and trailing whitespace; further `#` characters are preserved. Tags are parser-specific: Markdown tags its module with `TODO`/`FIXME` found in HTML comments; Python exposes comments without deriving these tags. Python signatures are structural summaries, not a source-formatting or PEP 8 contract.

Markdown fences accept three or more backticks or tildes, up to three leading spaces, and close only with the same character, sufficient length, and trailing spaces/tabs. Headings, links, and HTML comments inside fences are not extracted. ATX headings allow up to three leading spaces, list-item headings, empty titles, and optional closing hashes. Link extraction skips complete inline code spans within recognized text blocks, including spans across physical lines, as well as image links; source columns remain character offsets in the original line.

Within a physical line, inline links support nested brackets in labels, escaped delimiters, up to 32 nested balanced parentheses in destinations, and optional quoted or parenthesized titles. Deeper destination nesting is rejected. The extracted URL contains only the destination and preserves its escape spelling. Reference links, autolinks, and multiline links remain outside this structural subset.

Links in indented code are suppressed, using four-column tab stops and indentation relative to list content. Indentation within a continuing paragraph remains prose. This filtering adds no nodes for indented blocks: `code_block` nodes and their count still describe fences. The maintained Markdown parser is a structural subset, not a complete CommonMark renderer.

Markdown decoding uses strict UTF-8 with an optional BOM. Invalid bytes produce a decode failure retaining the original byte digest and prevent scope replacement.

### Code-units (`schema_version: "6"`)

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

Each document exposes retrieval-facing fields at the top level. `metadata` contains exactly `file`, `tags`, and `attributes`. Repository and source provenance fields remain on every document. Key fields include:

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
- Repeated Python declarations receive `~2`, `~3`, etc. in their qualified names and IDs, including descendants of repeated containers. `symbol` retains the source name.
- Markdown headings reserve natural sibling slugs: `A`, `A`, `A-2` becomes `a`, `a-3`, `a-2`. Qualified names, IDs, containers, and ancestry use the same assignment. Residual internal or external ID collisions abort emission.
- Preamble code fences use the reserved `@module` section, independently of a literal `# Root` heading.

Consumer input limits apply separately to imported content, identifiers, and snapshot size. See the [canonical import transport limits at revision `2157b93`](https://github.com/Intrinsical-AI/rag-prototype/blob/2157b93dd97515482abb285e1ace459e954d799b/src/local_rag_backend/core/services/canonical_import_transport.py#L22-L62). A valid RepoGPT artifact can exceed those limits and be refused before import; the linked limit definitions are not a claim of consumer acceptance of a particular artifact generation.

### Public JSON Schemas

RepoGPT ships JSON Schema files for the public artifact contracts:

- `src/repogpt/schemas/ast-v3.schema.json`: AST JSON envelopes and AST NDJSON record variants
- `src/repogpt/schemas/code-units-v6.schema.json`: `code-units` JSON envelopes

Both schemas are included in the wheel and source distribution. Installed code can read them with `importlib.resources.files("repogpt").joinpath("schemas").joinpath(schema_name).read_text(encoding="utf-8")`. Objects reject unknown fields throughout, including recursive nodes, failures, statistics, metadata, and parser-specific attributes and metrics. These schemas are contract aids for consumers and tests. They are validated against golden fixtures in the test suite via the dev-only `jsonschema` dependency; RepoGPT does not validate emitted artifacts at runtime.

## MCP interface

Install the optional SDK dependencies before starting the native server:

```bash
uv sync --extra mcp
uv run --extra mcp repogpt-mcp
# or: uv run --extra mcp python -m repogpt.mcp_server
```

The official MCP SDK owns stdio framing, initialization, standard negotiation,
notifications and ping. The internal target is protocol `2025-11-25`. Initialize
with that version, then send `notifications/initialized` before tool requests.
Library and ordinary CLI imports do not load the SDK.

| Tool | Required arguments | Optional arguments |
| --- | --- | --- |
| `repogpt_analyze` | `repo_path` | `projection` (`ast` default or `code-units`), `response_mode` (`summary` default or `inline`), `include_tests`, `extensions`, `fail_fast`, `repo_key`, `flatten` |
| `repogpt_compare_profiles` | `artifact_path`, `query` | integer `top_k` (default `3`, minimum `0`) |
| `repogpt_export` | `repo_path`, `output_path` | analysis options except `response_mode`; `format` (`json` default or AST-only `ndjson`), `replace_scope` (default `false`) |

`extensions` is an array such as `["py", "md"]`, normalized like CLI
`--extensions`; an empty array collects no files. `repo_key` applies only to
code-units. AST `flatten` defaults to `node` (or `file`). Analysis and comparison
are read-only. Export is destructive because it can atomically replace an
existing regular artifact file. Analysis never accepts a destination.

Analysis returns `projection`, `schema_version`, `complete`, native `stats`,
`failures`, `failure_count`, and `failures_truncated`. Failure summaries are
bounded to 64 KiB with explicit truncation metadata; native artifacts retain
all failures. Inline mode adds the complete native `artifact`. Export returns the
same summary plus `output_path`, `format`, `size_bytes`, and `sha256`; the exact
artifact bytes match CLI output. Comparison retains the native profile result.
All tools advertise strict input/output schemas and effect annotations. Every
result includes structured content and identical compact JSON text.

Partial analysis retains its artifact or receipt with `complete: false` and
`isError: true`. Expected operational failures return
`{"error":{"code":"operation_failed","message":"..."}}` with `isError: true`.
Responses exceeding 256 KiB return an explicit `response_too_large` error; no
canonical artifact is truncated. Export large artifacts to a file.

The writer hashes exact UTF-8 bytes and atomically replaces its destination,
retaining existing permissions. Missing parents are not created. Blank paths,
standard-I/O aliases, symlinks/non-regular leaves and existing repository source
files are refused, including sources omitted by filters or fail-fast. Scope
replacement retains the complete-selection guards described above.

Unknown tools and invalid arguments produce JSON-RPC `-32602`. Unexpected
failures and invalid handler output produce sanitized `-32603`. Tool calls sent
as notifications execute nothing. The SDK remains available after a failed
request. Producer work runs off the event loop with one worker slot; cancellation
does not release that slot until the worker finishes. A client timeout does not
prove that file publication was rolled back.

Logs remain on STDERR. SDK diagnostics are sanitized, including root-logger
messages that could contain malformed request bodies. Application internal-error
logs contain exception categories rather than request or exception contents.

Breaking changes: the old `repogpt_emit_ast` and `repogpt_emit_code_units` tools
are removed. Use `repogpt_analyze` for reads and `repogpt_export` for publication.
CLI `--languages` and MCP `languages` are replaced by `--extensions` and
`extensions`, without aliases.

## Retrieval profiles and model context

RepoGPT provides two retrieval presets over a code-units v6 artifact:

- `flat_rag_v3`: rank matching, retrievable documents and return the top `k` seeds without expansion
- `structured_rag_v3`: keep the same seeds, then add at most one enclosing retrievable container hop per seed when available

The public Python helpers return the original selected documents in `items` and a separate model context in `context.text`, with provenance in `context.segments`:

```python
from pathlib import Path

from repogpt.utils.retrieval_artifact import load_documents
from repogpt.utils.retrieval_profiles import assemble_flat_bundle, assemble_structured_bundle

documents = load_documents(Path("code_units.json"))
flat = assemble_flat_bundle(documents, query_text="helper", top_k=3)
structured = assemble_structured_bundle(documents, query_text="helper", top_k=3)
model_context = structured["context"]["text"]
```

Use `context.text` from either helper when constructing a model prompt. It merges overlapping physical lines within the same `(scope, snapshot_id, source_id, path, metadata.file.sha256)` group; different provenance stays separate. Module `content_ranges` place residual text at its original source coordinates. Conflicting text for the same source line is rejected. Segments record inclusive source intervals, contributing external IDs, and character offsets into the rendered text. Raw `items` and exported content are unchanged, including nested class/method and heading/subheading spans.

`context_characters` includes the rendered source headers and separators. `estimated_tokens` is `ceil(len(context.text) / 4)`, a rough character-based estimate. MCP and the diagnostic script return comparison summaries, not the complete context text. These helpers do not modify downstream RAG prompt builders; callers supply the selected context explicitly.

`--top-k` accepts integers greater than or equal to zero; zero and queries without matches produce empty bundles. Ranking ignores empty structural modules, uses exact symbols only when present, and breaks score ties by shorter qualified name and then ascending external ID. The script and MCP comparison share one loader that requires a code-units v6 envelope, validates retrieval fields, and rejects malformed entries and duplicate `external_id` values. Context assembly additionally checks selected documents' provenance, physical spans, and residual ranges. Comparison ranks once and shares seeds across profiles; it is not a production relevance evaluation.

## Developer benchmark scripts

RepoGPT includes two root-level diagnostic scripts:

- `benchmark_retrieval_profiles.py`: compares `flat_rag_v3` and `structured_rag_v3` over a `code-units` artifact
- `benchmark_tree_utils.py`: runs synthetic measurements for tree traversal, flattening, and Python comment association

These scripts are developer diagnostics, not public runtime interfaces.

## Logging and diagnostics

RepoGPT keeps data and logs separate:

- artifact data -> STDOUT or output file
- logs -> STDERR

Example STDERR from `repogpt tests/fixtures/cli_repo --stdout --include-tests` (exit `2`):

```text
2026-10-19 00:13:43 [error    ] parse error                    error='File "bad.py", line 1\n    def broken(:\n               ^\nSyntaxError: invalid syntax' path=bad.py
```

## Development workflow

### Pre-commit vs full validation

`pre-commit` is a fast local quality gate. In this repository it covers:

- `ruff-format`
- `ruff`
- `mypy`

Local hooks invoke the Ruff and Mypy versions in `uv.lock`; they do not install separate tool versions. Formatting is checked without modifying files. Hooks do not run `pytest`; `make validate` runs the locked environment sync, hooks, and full test suite, and is also the CI command.

The Mypy hook delegates to `make type`, covering the package, tests, `scripts/`, and root `benchmark_*.py` helpers.

Development tools belong to the `dev` dependency group and are not published as a package extra. CI requires `make validate` to pass on Python 3.10 through 3.14. Python 3.15 runs as a non-blocking experimental job with prereleases allowed.

Setup and common commands:

```bash
uv sync --locked --group dev
uv run --locked --group dev pre-commit install
uv run --locked --group dev pre-commit run --all-files
uv run --locked --group dev pytest -q
```

### Make targets

| Target | Command | Description |
| --- | --- | --- |
| `make lint` | `uv run --locked --group dev ruff check .` | Lint the codebase |
| `make type` | `uv run --locked --group dev mypy src tests scripts benchmark_*.py` | Run type checks |
| `make test` | `uv run --locked --group dev pytest -q` | Run the test suite |
| `make format` | `uv run --locked --group dev ruff format .` | Apply formatting |
| `make validate` | locked sync, hooks, pytest | Run the local and CI gate |
| `make clean` | `scripts/clean_artifacts.py` | Remove Python bytecode and pytest caches within the cleanup boundary |
| `make distclean` | `scripts/clean_artifacts.py --dist` | Also remove root build/distribution/tool caches and root/`src` egg-info |
| `make repogpt` | `uv run --locked repogpt $(ARGS)` | Show CLI help by default (`ARGS=--help`); pass `ARGS` to analyze a repository |

For example: `make repogpt ARGS='path/to/repo --stdout --include-tests'`.

Cleanup never traverses directory symlinks. It prunes `.venv`, `.git`, `.agents`, `.codex`, `.aws`, and directories containing `pyvenv.cfg`, including custom environment names. Artifact symlinks are unlinked at the leaf. `distclean` additionally targets root `.mypy_cache`, `.ruff_cache`, `build`, and `dist`, plus `*.egg-info` directly under the root or `src`. Before deleting anything, the helper refuses any removal tree containing a protected path or virtual environment. `clean` retains build/distribution directories; `distclean` explicitly removes those outputs.

Python integrations import concrete modules directly; package initializers no longer re-export classes or helpers. Internal file/request APIs use `extension` and `supported_extensions`; `extract_comments` accepts the `extension` values `py` and `md`. CLI `--extensions` and MCP `extensions` use the same normalized filter. `CollectedFile.relative_path` must be non-empty.

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
scripts/clean_artifacts.py
benchmark_retrieval_profiles.py
benchmark_tree_utils.py
```

High-level responsibilities:

- `runtime.py` wires the shared analysis runtime; `AnalyzeRepo.run(request)` returns `(result, projection)` after validation and does not write output
- `app/cli.py` exposes the CLI entry point and sends the returned projection to the file/stdout writer
- `mcp_server.py` exposes the optional SDK server; application and writer layers own analysis and publication
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
- MCP native/file-mode parity with CLI outputs, output schemas, path protections, and session recovery
- provenance-aware context assembly without changing raw retrieval items
- cleanup refusal before deleting protected environments or metadata

Targeted integration checks:

```bash
uv run pytest -q tests/integration/test_cli_contract.py
uv run pytest -q tests/integration/test_mcp_server.py
uv run pytest -q tests/integration/test_artifact_schemas.py
```

## Additional documents

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): current architecture, public contracts, interfaces, and invariants
- [docs/CHALLENGES.md](docs/CHALLENGES.md): open design questions and tradeoffs, not a committed roadmap
- [ROADMAP.md](ROADMAP.md): future work after the current source baseline

## License

[MIT](LICENSE)
