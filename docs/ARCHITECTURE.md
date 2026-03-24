# RepoGPT - Architecture

> **Owners:** RepoGPT maintainers
> **Scope:** current system architecture, public output contracts, Phase 1 interoperability layer, and near-term roadmap
> **Out of scope:** downstream production retrieval infrastructure, graph-rich context assembly, and agentic orchestration loops

---

## 0) TL;DR

- **What:** RepoGPT analyzes a source tree and emits deterministic structural artifacts for Python and Markdown. Its current value is a canonical structural IR plus derived projections for downstream indexing, retrieval, and evaluation.
- **Why:** The system exists to turn repositories into stable, queryable artifacts that humans and LLM pipelines can consume without reimplementing parsing and structural normalization per consumer.
- **How:**
  - collect repository files under explicit ignore and size rules
  - parse files into a canonical node tree
  - materialize projections such as AST exports and `code-units`
  - version public contracts explicitly
  - keep retrieval profiles as interoperability presets, even when retrieval is executed outside RepoGPT
- **Non-negotiables:**
  - structural IR is canonical; projections are derived
  - internal node ids are deterministic but snapshot-scoped
  - public contracts are versioned
  - `code-units` remains independently consumable
  - Phase 1 retrieval stays light and one-hop; graph-rich retrieval stays out of scope

---

## 1) Goals, Non-goals, Constraints

### 1.1 Goals

1. Produce a canonical structural representation of repository contents for supported languages.
2. Provide stable, versioned projections for downstream indexing and retrieval.
3. Keep interoperability layer small enough to be reliable and testable.
4. Preserve room for richer retrieval and context assembly without prematurely freezing a full graph or agentic design.

### 1.2 Non-goals

- A built-in production retrieval engine.
- A full public graph API in Phase 1.
- Perfect call-graph or reference analysis.
- Agentic control loops, RL, or multi-step autonomous retrieval planning.
- A general query DSL in the current phase.

### 1.3 Constraints

- Supported languages in scope today: Python and Markdown.
- Contracts must remain deterministic and explicitly versioned.
- Parser-emitted metadata varies by language and parser capability.
- Output artifacts must stay consumable without requiring RepoGPT runtime state.

### 1.4 Quality attributes

| Attribute | Target | Measured by |
| --------- | ------ | ----------- |
| Determinism | same input snapshot yields equivalent artifacts | unit, golden, and integration tests |
| Contract clarity | public fields have defined semantics | docs plus contract tests |
| Evolvability | new retrieval behavior can be added without rewriting the IR | architecture review and API boundaries |
| Partial-failure visibility | artifacts reflect parse failures explicitly | CLI and integration tests |

---

## 2) Domain model

### 2.1 Glossary

- **Structural IR:** canonical structural representation produced by analysis.
- **Node:** structural unit in the IR, such as module, class, function, method, heading, or code block.
- **Projection:** materialized view derived from the IR.
- **`code-units`:** retrieval-oriented projection intended for indexing and downstream filtering.
- **Retrieval profile:** contract-level preset describing expected downstream retrieval semantics.
- **Context assembly:** bundling retrieved items into the final input served to an LLM or similar consumer.

### 2.2 Bounded contexts

| Context | Responsibility | Owns data? | External deps | Public APIs |
| ------- | -------------- | ---------: | ------------- | ----------- |
| Collection and parsing | collect files and build structural IR | Yes | filesystem, Python AST | internal ports plus CLI flow |
| Projections and contracts | turn IR into versioned artifacts | Yes | none beyond IR | AST JSON/NDJSON, `code-units` JSON |
| Retrieval interoperability | define profile semantics and benchmark baselines | Yes | downstream consumers may execute retrieval | profile contracts, benchmark path |

### 2.3 Entities and value objects

#### Entity: `CodeNode`

- **Identity:** deterministic internal id derived from path, type, name, span, and containment context.
- **Lifecycle:** created by a parser, consumed by projectors, not directly exposed as the stable public retrieval id.
- **Invariants:** see section 4.
- **Context:** structural IR.

#### Value Object: `AnalysisResult`

- **Equality:** value-based.
- **Validation:** contains parsed files, failures, and summary stats for one analysis run.

#### Value Object: `AstProjection` / `CodeUnitsProjection`

- **Equality:** value-based public artifact envelope.
- **Validation:** schema version plus contract-specific payload.

---

## 3) Data and contract model

### 3.1 Structural IR

The structural IR provides a canonical node tree with:

- stable internal ids for a given snapshot and analysis pipeline
- containment relations
- source spans
- parser-emitted structural metadata

Additional metadata such as comments, tags, metrics, or dependency-related attributes may be present when supported by a parser, but they are not all part of the minimal invariant core.

Important identifier note:

- internal node ids are deterministic for a given repository snapshot and analysis pipeline
- internal node ids are not guaranteed to remain stable across refactors, line shifts, or containment changes
- public consumers should treat `external_id`, not internal node id, as the semantic public identifier in `code-units`

### 3.2 Projections

RepoGPT currently exposes two projection families:

- **AST export:** structural JSON or NDJSON representation of the node tree
- **`code-units`:** retrieval-oriented JSON projection with high-signal units

Projection rules:

- projections are always derived from the structural IR
- projections may omit structural detail for compactness
- projections own public contract versioning
- projections must remain consumable without needing in-memory IR state

### 3.3 `code-units` v4

`code-units` v4 is the current retrieval-oriented public contract.

It adds minimal hierarchy metadata without embedding full graph neighborhoods into each document.

#### Field semantics

| Field | Semantics |
| ----- | --------- |
| `unit_level` | one of `symbol` or `container` |
| `qualified_name` | semantic name used for downstream identification within the projection; for file/module roots the relative path acts as the root identifier |
| `container_id` | nearest enclosing container in the current IR, expressed as a semantic projection identifier |
| `depth` | containment depth from the file/module root |
| `ancestor_path` | ordered root-to-parent list of ancestor identifiers, represented in v4 as qualified-name-like strings |
| `docstring_present` | whether the underlying structural node has a non-empty docstring |
| `has_children` | whether the underlying structural node has direct children in the IR |

Contract notes:

- `container_id` may reference a logical container that is not emitted as a standalone document in the same artifact.
- `ancestor_path` is intended for lightweight structural filtering and bundling, not as a substitute for a full graph path model.
- `external_id` remains the public semantic identifier for a projected document.
- If a file yields no selected symbol or container units for its language, the projector falls back to the root module document so the file still contributes a seedable unit.

### 3.4 Mapping rules

- Parser output -> structural IR: language-specific parser emits `CodeNode` trees.
- Structural IR -> AST projection: direct structural export.
- Structural IR -> `code-units`: selected units plus retrieval-oriented metadata.
- Retrieval profile -> benchmark/bundle logic: operates on projected documents, not on raw parser state.

---

## 4) Invariants and validation

### 4.1 Phase 1 invariants

- Structural IR is canonical; projections are derived.
- Internal node ids are snapshot-scoped.
- `code-units` v4 remains independently consumable.
- Phase 1 retrieval profiles do not require a built-in retrieval engine.
- `structured_rag_v1` is limited to light one-hop container-aware expansion.
- Graph-rich retrieval and context bundles remain out of scope for Phase 1.

### 4.2 Contract invariants

- Every emitted `external_id` must be deterministic for a given artifact snapshot.
- `path`, `unit_type`, and span fields must remain coherent.
- `content_hash` must reflect the emitted content of the projected document.
- `unit_level` values must stay within the documented set.
- Failure records must remain explicit in artifact payloads.

### 4.3 Failure semantics

- Parse failures are represented in emitted artifacts.
- Partial success is allowed and reported.
- Fail-fast mode stops on first parse error.
- Missing or unsupported parser coverage is reflected in emitted results rather than hidden.

---

## 5) Architecture style and layers

### 5.1 Style

- **Style:** hexagonal-leaning layered architecture
- **Rationale:** the repo separates domain objects, application orchestration, ports, and adapters with enough discipline to keep parsers/projectors/writers swappable without introducing unnecessary framework complexity
- **Tradeoffs:** retrieval and context assembly are not yet first-class subsystems, so some downstream behavior remains contract-defined rather than runtime-native

### 5.2 Layers

| Layer | Responsibilities | Must NOT contain |
| ----- | ---------------- | ---------------- |
| Domain | entities, stats, analysis value objects | filesystem and CLI logic |
| Application | use-case orchestration | parser-specific logic |
| Ports | contracts for adapters | concrete adapter behavior |
| Adapters | filesystem, parsers, projectors, writers | cross-layer policy sprawl |
| CLI | user-facing command surface | domain rules |

### 5.3 Dependency rules

```text
Domain       -> (nothing)
Application  -> Domain
Ports        -> Domain
Adapters     -> Domain + Ports
CLI          -> Application + Adapters + Domain
```

Rule: the structural IR must not depend on any concrete parser or retrieval implementation

---

## 6) Components and interactions

### 6.1 Main components

- **Collector:** discovers files under ignore and size rules.
- **Loader:** loads bytes and decoded text with digest information.
- **Parser registry:** resolves parser by language/extension.
- **Parsers:** produce structural IR nodes.
- **Projectors:** materialize AST or `code-units` projections.
- **Writer:** emits artifacts to file or stdout.
- **Profile benchmark helpers:** compare Phase 1 retrieval profiles over `code-units` artifacts.

### 6.2 Main analysis flow

1. collect repository files
2. load file contents and digests
3. parse into structural IR
4. accumulate failures and stats
5. project to AST or `code-units`
6. write artifact and return result

### 6.3 Phase 1 benchmark flow

1. generate a `code-units` artifact
2. rank `code-units` documents for a query
3. assemble a `flat_rag_v1` bundle from the ranked documents with no expansion
4. assemble a `structured_rag_v1` bundle with at most one container hop per seed
5. compare item sets and rough bundle size

---

## 7) Interfaces and retrieval profiles

### 7.1 Public interface today

- **Primary built-in interface:** CLI
- **Public artifact contracts:** AST JSON/NDJSON and `code-units` JSON
- **No built-in HTTP or messaging interface is part of the current architecture**

### 7.2 Retrieval profiles

In Phase 1, retrieval profiles are contract-level interoperability presets rather than built-in retrieval implementations. They define expected downstream semantics even when retrieval is executed by external infrastructure.

#### `flat_rag_v1`

- primary input: ranked `code-units` documents
- expansion: none
- ranking: exact symbol matches get a stronger score, but the profile is not restricted to symbol-only documents
- intent: baseline retrieval and reproducible comparison

#### `structured_rag_v1`

- primary input: ranked `code-units` documents
- expansion: at most one hop to the nearest enclosing container, subject to budget
- default interpretation: container-aware expansion for top ranked seeds, then deduplicate
- intent: light structured retrieval without requiring a graph engine

---

## 8) Performance, benchmarks, and observability

### 8.1 Performance posture

- primary current concern: deterministic artifact generation over large repositories
- known future concerns: repeated tree traversals, caching, and incremental analysis

### 8.2 Benchmark posture

Phase 1 includes a small benchmark path for comparing `flat_rag_v1` and `structured_rag_v1`.

This benchmark path validates profile behavior at a small scale. It is not, by itself, evidence of general retrieval quality, end-to-end usefulness, or agentic performance.

### 8.3 Observability

- structured logs to stderr
- artifact data to stdout or file
- failure records in the emitted payload

---

## 9) Testing strategy

| Type | Scope | Tools | Required gates |
| ---- | ----- | ----- | -------------- |
| Unit | parsers, projectors, utils | `pytest` | required |
| Integration | CLI and golden contracts | `pytest` | required |
| Contract | schema and payload shape | tests plus golden fixtures | required |
| Benchmark smoke | profile comparison path | script plus targeted tests | optional but expected in active development |

---

## 10) Roadmap

### 10.1 Phase 1

- canonical structural IR vs projection boundary
- `code-units` v4 hierarchy metadata
- `flat_rag_v1` and `structured_rag_v1`
- minimal benchmark path for profile comparison

### 10.2 Phase 2 direction

- explicit relation-aware projections where parser support is reliable
- stronger retrieval semantics beyond one-hop container expansion
- clearer bundle assembly policies

### 10.3 Phase 3 direction

- context bundle contracts
- graph-richer retrieval
- agentic orchestration loops
- more representative end-to-end evaluation

---

## 11) Repo layout and conventions

```text
src/repogpt/
  domain/
  application/
  ports/
  adapters/
  app/
  utils/
tests/
docs/
```

Conventions:

- keep domain and contract semantics small and explicit
- version public artifacts intentionally
- prefer parser-specific enrichment over pretending all metadata is universal
- keep future retrieval execution decoupled from the structural core
