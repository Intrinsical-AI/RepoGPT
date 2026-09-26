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
                            CLI writer       MCP result
```

Concrete runtime wiring lives in `src/repogpt/runtime.py` and currently composes:

- `DefaultCollector`
- `DefaultLoader`
- `StaticParserRegistry`
- `AstProjector`
- `CodeUnitsProjector`

`AnalyzeRepo.run(request)` returns `(AnalysisResult, projection)` after request and replacement validation. Output destinations belong to the CLI, which calls `ArtifactWriter` explicitly. MCP consumes the returned projection directly. The application has no writer dependency or output target.

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
- initialization returns protocol version `2024-11-05` and package-derived server metadata

Built-in tools:

- `repogpt_emit_code_units`
- `repogpt_emit_ast`
- `repogpt_compare_profiles`

The MCP server reuses the same analysis runtime and language-filter validation semantics as the CLI. It does not introduce a separate artifact contract. Tool results contain `content` and `isError`. JSON text contains the artifact or comparison directly; AST NDJSON uses an array of records. No CLI exit code, empty stderr field, or extra artifact/comparison envelope is carried. Tool execution failures set `isError: true`, including partial/fail-fast artifacts whose file errors remain inspectable.

Both entry points configure stdlib and structlog output on STDERR. Importing the MCP module does not configure logging. Valid notifications receive no responses and do not dispatch tools; invalid envelopes are rejected before notification handling, including envelopes without an ID. Wire validation checks required/unknown fields, booleans, language arrays, and enums without coercion. Handlers apply shared semantic policies such as the repository-key pattern before collection. Error codes distinguish malformed JSON (`-32700`), envelopes (`-32600`), unknown methods (`-32601`), arguments (`-32602`). Failed analysis and refused replacement use MCP tool results with `isError: true`.

CLI rejects conflicting output targets and explicit AST-only flattening options on code-units exports before analysis. Shared request validation runs at the CLI boundary for argument diagnostics and inside the application for non-CLI callers; the policy is defined once.

## 4. Domain and projection model

### 4.1 Canonical structural representation

The internal structural representation is a `CodeNode` tree with:

- deterministic internal IDs for a given repository snapshot and analysis pipeline
- containment relations
- source spans
- parser-emitted metadata such as comments, tags, metrics, attributes, and dependencies where supported

Internal node IDs are deterministic but snapshot-scoped. They are not the stable public identifier for retrieval-facing consumers.

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

### 5.1 AST export (`schema_version: "1"`)

AST export is the direct structural projection of parsed files.

In both formats, `--flatten node` emits each node as a flat record. `--flatten file` emits one root record per file with its entire nested subtree. Its `children` recursively follow the node schema, without the top-level record wrapper fields. Both layouts remain AST v1.

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

- `src/repogpt/schemas/ast-v1.schema.json`

### 5.2 Code-units (`schema_version: "4"`)

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
- `content_hash`
- `docstring_present`
- `has_children`

Contract notes:

- `external_id` is the semantic public identifier for a projected document
- `content_hash` is `sha256(content)` for the exact emitted span
- `snapshot_id` is a repository-snapshot provenance marker derived from collected file hashes
- `repo_key` defaults to `local-` plus the full SHA-256 of the OS-normalized canonical absolute path; an explicit validated key makes identity portable across clones
- `scope` is `repogpt:{repo_key}`; language and test filters do not create additional scopes
- `replace_scope` defaults to `false`; explicit replacement requires all languages, tests included, non-empty documents, no failures/early stop, and no eligible candidates omitted by size/binary guards
- retrieval fields have one representation at the document top level; `metadata` contains only file digest, tags, parser attributes, and dependencies
- if a file yields no selected symbol or container units for its language, the projector falls back to the root module document

A single semantic traversal assigns qualified names and external IDs. Python sibling redeclarations append `~2`, `~3`, etc.; descendants inherit the disambiguated segment. Markdown duplicate heading slugs avoid reserved natural sibling slugs. Containers and ancestry use the same name map. Internal node IDs are checked before projection; duplicate external IDs reject emission. See [CHANGELOG.md](../CHANGELOG.md) for current identity rules.

Schema file:

- `src/repogpt/schemas/code-units-v4.schema.json`

The schema files are package resources included in wheels and source distributions, accessible through `importlib.resources.files("repogpt").joinpath("schemas")`. They are public contract validation helpers. They are validated against golden fixtures in tests and are not part of runtime artifact emission.

## 6. Retrieval profile semantics

RepoGPT includes lightweight retrieval helpers over `code-units`. These are interoperability helpers, not a built-in production retrieval engine.

### 6.1 `flat_rag_v1`

- rank documents for a query
- return the top `k` seed items
- perform no structural expansion

### 6.2 `structured_rag_v1`

- rank documents for a query
- keep the same top `k` seed items
- add at most one nearest enclosing container hop per seed when a projected container is available
- deduplicate by `external_id`

### 6.3 Benchmark scope

The benchmark path compares profile behavior on:

- selected items
- expansion count
- rough token estimate

The benchmark and MCP comparison share a loader that checks the v4 envelope and required retrieval fields and rejects duplicate identities or malformed entries. `top_k` must be a non-negative integer; zero returns an empty bundle.

Comparison ranks once and shares the same seeds across both profiles. It does not claim end-to-end task quality, production relevance quality, or agentic performance.

## 7. Collection, parsing, and failure semantics

### 7.1 Collection

Collection behavior is deterministic and currently includes:

- deterministic pruned traversal over the repository root
- canonical relative-path sort
- built-in ignore directories/files
- optional `.repogptignore`
- silent pruning for ignored directories before descent; ignored directory contents are not expanded into skipped-file records
- test exclusion by default
- file-size guard
- binary-file detection
- symlink exclusion

### 7.2 Parsing and projection

For each collected file:

1. load raw bytes and decoded text
2. resolve parser by extension
3. parse into a `CodeNode` tree
4. record parse failures explicitly
5. project the aggregate result to AST or `code-units`

Python decoding uses `tokenize.detect_encoding` and strict decoding, retaining the raw byte digest even when decoding fails. Markdown retains UTF-8 replacement decoding. Source lines, spans, metrics, and comments share LF/CRLF/CR boundaries. Python traverses all statement branches while preserving declaration scopes and source order; imports retain their relative level. Markdown fences retain opening character and length, and same-line links include their start column in node identity.

Python comment extraction removes one delimiter `#`, preserving further hashes while trimming leading spaces and trailing whitespace. Tags remain parser-specific: Markdown module tags reflect TODO/FIXME in HTML comments; Python exposes comments without generating those tags. Markdown link filtering tracks indented code, paragraph continuations, and list indentation using four-column tab stops. Indented blocks do not add new IR nodes or affect the fenced-code-block count; the parser remains a structural subset of Markdown.

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

Public exit-code policy:

- `0`: success, or early close by the STDOUT consumer
- `1`: fail-fast stopped on first parse error
- `2`: partial parse/decode run with emitted artifact, or argument rejection without an artifact
- `3`: invalid path, I/O error, refused replacement, or unrecoverable runtime error

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

## 10. Deliberately out of scope

The current architecture does not commit to:

- a built-in production retrieval engine
- graph-rich public relation APIs
- context-bundle contracts
- agentic orchestration loops
- full call-graph or reference-graph accuracy

Future work is tracked in [ROADMAP.md](../ROADMAP.md). Open design questions live in [docs/CHALLENGES.md](CHALLENGES.md).
