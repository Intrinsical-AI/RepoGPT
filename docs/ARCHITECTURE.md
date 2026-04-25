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
Collector -> Loader -> Parser registry -> Projector -> Writer
```

Concrete runtime wiring lives in `src/repogpt/runtime.py` and currently composes:

- `DefaultCollector`
- `DefaultLoader`
- `StaticParserRegistry`
- `AstProjector`
- `CodeUnitsProjector`
- `ArtifactWriter`

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

Built-in tools:

- `repogpt_emit_code_units`
- `repogpt_emit_ast`
- `repogpt_compare_profiles`

The MCP server reuses the same analysis runtime as the CLI. It does not introduce a separate artifact contract.

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
- `replace_scope: true` supports scope-replacement import flows
- canonical retrieval fields are duplicated under `metadata` for generic downstream filters/importers
- if a file yields no selected symbol or container units for its language, the projector falls back to the root module document

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

It does not claim end-to-end task quality, production relevance quality, or agentic performance.

## 7. Collection, parsing, and failure semantics

### 7.1 Collection

Collection behavior is deterministic and currently includes:

- deterministic pruned traversal over the repository root
- canonical relative-path sort
- built-in ignore directories/files
- optional `.repogptignore`
- silent pruning for ignored directories before descent
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

### 7.3 Failure and exit semantics

Invariants:

- parse failures remain visible in public payloads
- partial success is allowed
- fail-fast stops after the first parse error
- invalid repository paths are reported cleanly

Public exit-code policy:

- `0`: success
- `1`: fail-fast stopped on first parse error
- `2`: partial run with emitted artifact
- `3`: invalid path or unrecoverable runtime error

## 8. Layers and dependency rules

RepoGPT follows a hexagonal-leaning layered structure.

| Layer | Responsibilities | Must not contain |
| --- | --- | --- |
| Domain | core entities and value objects | filesystem and CLI logic |
| Application | use-case orchestration | parser-specific behavior |
| Ports | adapter contracts | concrete adapter logic |
| Adapters | filesystem, parsers, projectors, writers | cross-layer policy sprawl |
| Interfaces | CLI and MCP entry points | domain implementation details |

Dependency rule:

```text
Domain       -> (nothing)
Application  -> Domain
Ports        -> Domain
Adapters     -> Domain + Ports
Interfaces   -> Application + Adapters + Domain
```

The structural representation must not depend on any concrete parser implementation or retrieval engine.

## 9. Observability and operational boundaries

Observability today:

- structured logs on STDERR
- artifact data on STDOUT or file output
- explicit failure records in the artifact payload

Known operational boundaries:

- full-tree collection cost grows with filesystem size
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
