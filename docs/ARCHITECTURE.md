# RepoGPT Architecture

> Owners: RepoGPT maintainers
> Scope: current runtime composition, public contracts, interfaces, invariants, and operational boundaries
> Out of scope: production retrieval infrastructure, graph-rich context assembly, and agentic orchestration loops

## 1. System overview

RepoGPT analyzes a repository and emits deterministic artifacts derived from a canonical structural representation.

Current supported languages:

- Python (`.py`)
- Markdown (`.md`)

Shared runtime composition:

```text
Collector -> Loader -> Parser registry -> Projector
                                         |
                                (result, projection)
                                  /             \
                            CLI writer    MCP result/file
```

Concrete runtime wiring lives in `src/repogpt/runtime.py` and currently composes:

- `DefaultCollector`
- `DefaultLoader`
- `StaticParserRegistry`
- `AstProjector`
- `CodeUnitsProjector`

`AnalyzeRepo.run(request)` returns `(AnalysisResult, projection)` after request and replacement validation. Output destinations belong to the interfaces: CLI calls `ArtifactWriter` explicitly; MCP returns native objects inline or calls the same writer for file mode. The application has no writer dependency or output target.

## 2. Architecture intent

RepoGPT exists to keep three concerns separate:

1. collection and parsing into a canonical structural representation
2. materialization of versioned public projections
3. downstream retrieval experimentation that consumes projections rather than parser internals

This separation keeps the structural core stable while allowing projection and retrieval behavior to evolve independently.

## 3. Public interfaces today

RepoGPT currently exposes two built-in public interfaces.

### 3.1 CLI

Entry point:

- `repogpt`

Responsibilities:

- validate runtime arguments
- build an `AnalysisRequest`
- run the shared analysis pipeline
- emit the selected artifact to file or STDOUT
- report clean exit codes and STDERR logs

### 3.2 MCP stdio server

Entry point:

- `repogpt-mcp`

Transport:

- line-delimited JSON-RPC over stdio
- initialization returns the sole supported protocol version `2025-06-18` and package-derived server metadata; clients requesting another version receive this supported alternative

Built-in tools:

- `repogpt_emit_code_units`
- `repogpt_emit_ast`
- `repogpt_compare_profiles`

The MCP server reuses the analysis runtime and extension-filter policies used by the CLI. Tool results contain `structuredContent`, identical compact JSON in `content[0].text`, and `isError`. JSON artifacts are returned as native objects. Inline AST NDJSON uses `{"schema_version":"3","format":"ndjson","records":[...]}` because structured content must be an object. Execution failures use `{"error":"message"}` with `isError: true`. Partial/fail-fast results retain their inline artifact or file receipt with `isError: true`.

Both emit tools accept optional `output_path`. File mode writes the original projection through `ArtifactWriter` and returns exactly `output_path`, `format`, `schema_version`, `size_bytes`, `sha256`, and `stats`. JSON/NDJSON bytes match the CLI writer; NDJSON files contain actual record lines rather than the MCP wrapper. The absolute receipt path resolves the parent directory without following the leaf. Existing regular files are atomically replaced with permissions retained; missing parent directories are not created. Standard-I/O aliases, symlink/non-regular leaves, blank paths, and existing supported source files inside the repository are rejected. The source guard runs before analysis, covering filters and fail-fast stops.

Tool discovery publishes strict output-schema unions using the packaged artifact definitions, receipt variants, and execution-error objects. Partial artifacts satisfy the artifact branch. Emit tools advertise `readOnlyHint: false` and `destructiveHint: true`; comparison advertises `readOnlyHint: true`. `repogpt_compare_profiles` accepts `top_k` (integer, minimum zero, default three) and rejects invalid values before reading its artifact input.

Both entry points configure structlog output on STDERR. Importing the MCP module does not configure logging. Valid notifications receive no responses and do not dispatch tools; invalid envelopes are rejected before notification handling, including envelopes without an ID. Wire validation checks required/unknown fields, booleans, extension arrays, integers, minima, and enums without coercion. Handlers apply shared semantic policies such as the repository-key pattern before collection. Error codes distinguish malformed JSON (`-32700`), envelopes (`-32600`), unknown methods (`-32601`), arguments (`-32602`). Failed analysis and refused replacement use MCP tool results with `isError: true`. `ping` returns `{}`.

JSON decoder `ValueError` failures, including oversized integer literals, return parse error `-32700` and leave the MCP session available for the next request.

CLI rejects conflicting output targets and explicit AST-only flattening options on code-units exports before analysis. The application validates each analysis request once; CLI maps invalid requests to argument diagnostics.

## 4. Domain and projection model

### 4.1 Canonical structural representation

The internal structural representation is a `CodeNode` tree with:

- deterministic internal IDs from relative path, type, and original line/character column
- containment relations
- source spans
- parser-emitted metadata such as comments, tags, metrics, attributes, and dependencies where supported

Internal node IDs do not depend on names, parents, or ending spans. They change when an origin moves; retrieval-facing documents have separate semantic external IDs.

Internal request/file APIs use `AnalysisRequest.supported_extensions` and file `extension` properties. The parser registry and `extract_comments` share the extension names `py` and `md`. The CLI flag `--languages` and MCP field `languages` remain unchanged. `CollectedFile` rejects empty `relative_path` values, and projectors use that canonical path directly.

### 4.2 Public projections

RepoGPT currently exposes two projection families:

- AST export
- `code-units`

Projection rules:

- projections are derived from the structural representation
- projections own their public schema versions
- projections remain consumable without in-memory runtime state
- failure records remain explicit in the public payload

## 5. Public artifact contracts

### 5.1 AST export (`schema_version: "3"`)

AST export is the direct structural projection of parsed files.

In both formats, `--flatten node` emits each node as a flat record. `--flatten file` emits one root record per file with its entire nested subtree. Its `children` recursively follow the node schema, without the top-level record wrapper fields. Both layouts use AST v3 and expose `start_column`.

Imported names have one location in `dependencies`, not `attributes.imported_names`. Link text is `name`, its destination is `attributes.url`, and its column is the node's `start_column`; links have empty dependencies. Modules use `path` without an `attributes.relative_path` duplicate.

Formats:

- JSON envelope
- NDJSON stream

JSON payload keys:

- `schema_version`
- `repo_root`
- `stats`
- `failures`
- `records`

NDJSON record types:

- `node`
- `failure`
- `summary`

Schema file:

- `src/repogpt/schemas/ast-v3.schema.json`

### 5.2 Code-units (`schema_version: "6"`)

`code-units` is the retrieval-oriented projection.

Top-level payload keys:

- `schema_version`
- `kind`
- `repo_key`
- `snapshot_id`
- `scope`
- `replace_scope`
- `stats`
- `failures`
- `documents`

Document-level fields with contract significance:

- `external_id`
- `source_id`
- `repo_key`, `scope`, and `snapshot_id` on every document
- `path`
- `language`
- `unit_type`
- `unit_level`
- `symbol`
- `qualified_name`
- `container_id`
- `depth`
- `ancestor_path`
- `start_line`
- `end_line`
- `content`
- `content_ranges` on module documents
- `content_hash`
- `docstring_present`
- `has_children`

Contract notes:

- `external_id` is the semantic public identifier for a projected document
- `content_hash` is `sha256(content)`; non-module content is an exact source span
- `snapshot_id` is a repository-snapshot provenance marker derived from collected file hashes
- `repo_key` defaults to `local-` plus the full SHA-256 of the OS-normalized canonical absolute path; symlink aliases share an identity, while moving a repository or using another clone changes the automatic key
- an explicit `repo_key` makes identity portable across clones and must match `[a-z0-9][a-z0-9._-]{0,127}` without normalization
- `scope` is `repogpt:{repo_key}`; language and test filters do not create additional scopes
- `replace_scope` defaults to `false`; explicit replacement requires all languages, tests included, non-empty documents, no failures/early stop, and no eligible candidates omitted by size/binary guards
- retrieval fields have one representation at the document top level; `metadata` contains exactly `file`, `tags`, and `attributes`, without dependencies
- every parsed file emits a root module. Its content concatenates lines outside all emitted non-module spans; inclusive `content_ranges` identifies the source intervals, and empty modules remain structural containers
- `container_id` points to the nearest emitted ancestor; a module points to itself

A single semantic traversal assigns qualified names and external IDs. The first Python declaration keeps its name segment; later siblings append `~2`, `~3`, etc., and descendants inherit the disambiguated segment. `symbol` retains the source name. Markdown duplicate heading slugs reserve natural sibling slugs: `A`, `A`, `A-2` becomes `a`, `a-3`, `a-2`. Preamble code fences use `@module`, a namespace heading slugs cannot produce, so their IDs cannot collide with fences under a literal `# Root` heading.

Containers and ancestry use the same name map. Internal node IDs derive from relative path, node type, initial source line, and character column; names, parent IDs, and ending spans do not affect them. Internal node IDs are checked before projection, and duplicate external IDs reject emission. RepoGPT emits artifacts; consumers own imports and scope deletion, and should replace scopes only with an accepted complete snapshot.

Schema file:

- `src/repogpt/schemas/code-units-v6.schema.json`

The schema files are package resources included in wheels and source distributions, accessible through `importlib.resources.files("repogpt").joinpath("schemas")`. Object fields are closed throughout: envelopes, recursive nodes, failure records, statistics, metadata, and each parser-emitted attribute/metric variant reject unknown keys. This is a fixed contract, including node-type-specific empty objects. Schema changes accompany explicit contract versioning. Tests validate real exports and golden fixtures; artifact emission does not run a runtime JSON Schema validator. MCP discovery embeds these definitions in its output schemas without external schema retrieval.

## 6. Retrieval profile semantics

RepoGPT includes lightweight retrieval helpers over `code-units`. These are interoperability helpers, not a built-in production retrieval engine.

### 6.1 `flat_rag_v3`

- rank only positive-scoring documents for a query, excluding blank structural modules
- return the top `k` seed items
- perform no structural expansion

### 6.2 `structured_rag_v3`

- rank documents for a query
- keep the same top `k` seed items
- add at most one nearest emitted enclosing container hop per seed when it has nonblank content
- deduplicate by `external_id`

### 6.3 Canonical model context

`assemble_flat_bundle` and `assemble_structured_bundle` are public helpers in `repogpt.utils.retrieval_profiles`, each accepting `(documents, *, query_text, top_k=3)`. Their raw `items` remain selected source documents, including overlapping class/method and heading/subheading content. Both return a separate `context` with `text` and `segments` for model consumption.

Context assembly groups physical lines by `(scope, snapshot_id, source_id, path, metadata.file.sha256)`. It merges covered lines within each group, coalesces contiguous intervals, and rejects conflicting text at the same coordinate. Different provenance groups stay separate. Module `content_ranges` map concatenated residual text to its original inclusive intervals; other documents use their complete source spans. Invalid ranges, missing provenance, and mismatched line counts fail rather than falling back to raw concatenation.

Each rendered interval has a JSON provenance header and exact source content. Separators and headers are included in `context_characters`. Segment records include source identity, file hash, inclusive source interval, contributing external IDs, and `text_start`/`text_end` character offsets; `context.text[text_start:text_end]` selects its source content. `estimated_tokens` equals `ceil(len(context.text) / 4)` and is a rough estimate, not a model tokenizer count.

Callers feed `bundle["context"]["text"]` to their own prompt builder. These helpers do not change exported content, raw retrieval items, or downstream RAG prompt construction.

### 6.4 Comparison scope

The benchmark path compares profile behavior on:

- selected items
- expansion count
- deduplicated rendered context characters and segment count
- rough token estimate of that rendered context

The diagnostic script and MCP comparison share a loader that checks the v6 envelope and required retrieval fields and rejects duplicate identities or malformed entries. Assembly additionally validates selected documents' context provenance and spans. `top_k` must be a non-negative integer; zero and unmatched queries return empty bundles. Comparison returns profile summaries and external IDs rather than the full context text.

Comparison ranks once and shares the same seeds across both profiles. It does not claim end-to-end task quality, production relevance quality, or agentic performance.

## 7. Collection, parsing, and failure semantics

### 7.1 Collection

Collection behavior is deterministic and currently includes:

- deterministic pruned traversal over the repository root
- canonical relative-path sort
- built-in ignore directories/files
- optional `.repogptignore`
- a skip record for each pruned directory; ignored directory contents are not enumerated
- test exclusion by default
- file-size guard
- binary-file detection
- symlink exclusion
- explicit `non_regular_file` skip records for other non-regular files

### 7.2 Parsing and projection

For each collected file:

1. load raw bytes and decoded text
2. resolve parser by extension
3. parse into a `CodeNode` tree
4. record parse failures explicitly
5. project the aggregate result to AST or `code-units`

Python decoding uses `tokenize.detect_encoding` and strict decoding. Markdown uses strict UTF-8-sig decoding, accepting an optional BOM. Both retain the raw byte digest when decoding fails, and a decode failure prevents scope replacement. Source lines, spans, metrics, and comments share LF/CRLF/CR boundaries. Python traverses all statement branches while preserving declaration scopes and source order; imports retain their relative level. Markdown fences retain opening character and length, and nodes retain original character columns.

Python visibility treats names beginning and ending with `__` as public, other double-leading-underscore names as private, and single-leading-underscore names as protected. Within a physical line, Markdown inline links support nested bracket labels, escaped delimiters, up to 32 nested balanced destination parentheses, and optional quoted or parenthesized titles; deeper nesting is rejected. URL attributes contain only the destination and preserve its escape spelling. Reference links, autolinks, and multiline links are outside this structural subset.

Python comment extraction removes one delimiter `#`, preserving further hashes while trimming leading spaces and trailing whitespace. Tags remain parser-specific: Markdown module tags reflect TODO/FIXME in HTML comments; Python exposes comments without generating those tags. Markdown link filtering tracks indented code, paragraph continuations, and list indentation using four-column tab stops. List-contained fences retain original file spans, use the enclosing list indentation for closing fences, and end as unclosed when the container ends. Block starts inside lists reset paragraph continuation, so a following indented code block contributes no links. These boundaries follow the [CommonMark list-item and indented-code rules](https://spec.commonmark.org/0.31.2/#list-items); the parser remains a structural subset of Markdown. Indented blocks do not add new IR nodes or affect the fenced-code-block count.

An evaluation of `markdown-it-py` 4.2.0 did not meet RepoGPT's exact source-column requirement: block tokens provide line ranges, while inline link tokens lack positions after list and blockquote prefixes are stripped. Reconstructing columns across lazy continuations, tabs, and CRLF would require duplicating the parser's internal source mapping. The maintained structural parser therefore remains the implementation for this contract.

Preamble fenced-code identities use `@module`, which cannot be produced by heading slugification. Fences under a literal `# Root` heading therefore retain their IDs and ordinals when a preamble fence is added or removed.

### 7.3 Failure and exit semantics

Invariants:

- parse failures remain visible in public payloads
- partial success is allowed
- fail-fast stops after the first parse error
- invalid repository paths are reported cleanly
- any traversal, stat, probe, or source-read error aborts before projection or output
- a missing ignore file is allowed; an unreadable or invalid existing ignore file aborts collection
- an explicit replacement request rejects incomplete results before writing
- file output uses a temporary file in the destination directory followed by atomic replacement; write errors preserve the previous destination
- writers propagate destination-specific I/O errors; entrypoints own the error diagnostic
- CLI input I/O failures and internal consistency failures have distinct analysis diagnostics, without redirecting STDOUT

The file writer returns an immutable size/SHA-256 receipt only after successful atomic publication, hashing the serialized UTF-8 chunks during writing. STDOUT output returns no receipt. CLI ignores the receipt; MCP uses it for compact file-mode responses. Internal duplicate IDs, invalid source spans, and absent emitted containers raise `ArtifactConsistencyError` while preserving the diagnostic detail.

Public exit-code policy:

- `0`: success, or early close by the STDOUT consumer
- `1`: fail-fast stopped on first parse error
- `2`: partial parse/decode run with emitted artifact, or argument rejection without an artifact
- `3`: invalid path, I/O error, refused replacement, internal consistency failure, or unrecoverable runtime error

Replacement refusal takes precedence over normal partial/fail-fast emission. Known ignores and symlink exclusions define the collection universe; defaults do not imply a complete repository export. Downstream consumers own import and deletion operations.

The writer flushes STDOUT before returning, so buffered pipe errors reach the CLI handler. CLI and MCP share only the process-level cleanup that redirects the closed output descriptor to the null device to prevent a second flush failure at shutdown. Early-close status `0` acknowledges consumer termination, not complete artifact delivery. Other output failures use `3`; MCP also uses `3` for other stdio I/O errors.

## 8. Layers and dependency rules

RepoGPT follows a hexagonal-leaning layered structure.

| Layer | Responsibilities | Must not contain |
| --- | --- | --- |
| Domain | core entities and value objects | filesystem and CLI logic |
| Application | use-case orchestration | parser-specific behavior |
| Ports | adapter contracts | concrete adapter logic |
| Utils | shared tree, text, identity, and retrieval helpers | application orchestration or concrete adapter dependencies |
| Adapters | filesystem, parsers, projectors, writers | cross-layer policy sprawl |
| Interfaces | CLI/MCP entrypoints, runtime composition, logging and stdio setup | domain implementation details |

Dependency rule:

```text
Domain       -> (nothing)
Ports        -> Domain
Utils        -> Domain
Application  -> Domain + Ports + Utils
Adapters     -> Domain + Ports + Utils
Interfaces   -> Application + Adapters + Domain + Ports + Utils
```

The structural representation must not depend on any concrete parser implementation or retrieval engine.

Package initializers retain package boundaries without re-exporting internal classes or helpers. Python callers import their defining modules directly.

These rules describe dependencies between RepoGPT layers; imports within a layer and standard-library imports are separate. `tests/unit/test_architecture.py` derives the internal dependency edges from source imports, including relative imports, and checks the allowed directions. Its narrower checks also keep I/O/logging implementation out of analysis orchestration and concrete parsers out of the collector and CLI.

## 9. Observability and operational boundaries

Observability today:

- structured logs on STDERR
- artifact data on STDOUT or file output
- explicit failure records in the artifact payload

Known operational boundaries:

- unignored-tree collection cost grows with filesystem size
- Python comment association can become expensive on deep trees with dense comments
- large files increase parser and span-extraction cost

These are implementation boundaries, not contract changes.

### Cleanup boundary

`make clean` runs `scripts/clean_artifacts.py` to remove `__pycache__`, `.pytest_cache`, and `.pyc` files within the permitted tree. `make distclean` additionally targets root `.mypy_cache`, `.ruff_cache`, `build`, `dist`, and `*.egg-info` directly under the root or `src`.

The helper plans and preflights removals before changing files. It does not follow directory symlinks, and artifact symlinks are unlinked at the leaf. Named `.venv`, `.git`, `.agents`, `.codex`, and `.aws` paths and directories containing `pyvenv.cfg` are protected. A removal tree containing any protected path or environment causes refusal before any deletion, including when a build/cache directory itself is a virtual environment. Inspection or traversal errors abort cleanup.

## 10. Deliberately out of scope

The current architecture does not commit to:

- a built-in production retrieval engine
- graph-rich public relation APIs
- downstream prompt-building and orchestration policies
- agentic orchestration loops
- full call-graph or reference-graph accuracy

Future work is tracked in [ROADMAP.md](../ROADMAP.md). Open design questions live in [docs/CHALLENGES.md](CHALLENGES.md).
