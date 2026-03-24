# RepoGPT Plan

## Purpose

This document proposes a staged plan for evolving RepoGPT from:

- a structural analyzer with useful projections

into:

- a system with clear contracts for structure, projections, retrieval, and context assembly.

The goal is to keep Phase 1 small and executable, while leaving Phase 2 and Phase 3 as intentional directions rather than locked specifications.

## Current Observation

Today the repo already has:

- a real structural tree (`CodeNode`) with parent/child relations
- deterministic node ids
- parser-specific semantics for Python and Markdown
- AST and `code-units` projections
- a projection intended for downstream RAG/indexing

What it does not yet have as a first-class contract:

- retrieval contracts
- context assembly contracts
- official retrieval profiles
- a benchmark that measures full retrieval/context behavior

## Guiding Principles

1. Separate structural IR from projections and from retrieval behavior.
2. Keep the stable core small.
3. Add only the minimum hierarchy needed to make runtime expansion possible.
4. Prefer 1-2 official defaults over many flexible but underspecified options.
5. Benchmark only after the relevant contract is explicit.

---

## Phase 1: Minimal Executable Foundation

This phase should be treated as the first concrete delivery target.

### Objectives

- clarify the boundary between core structural IR and projected retrieval units
- enrich `code-units` with minimum hierarchy metadata
- define official default retrieval profiles at a product-contract level
- enable a first meaningful benchmark for flat vs structured retrieval

### Scope

#### 1. Core IR boundary

Make the distinction explicit between:

- structural IR: canonical tree/graph entities produced by analysis
- projections: materialized views derived from the IR

Phase 1 does not need a full public graph API. It only needs the contract boundary to be documented and stable enough for follow-on work.

#### 2. Minimal `code-units` enrichment

Add only the metadata needed for light hierarchical expansion at retrieval time.

Candidate minimum fields:

- `qualified_name`
- `unit_level` with initial values such as `symbol` and `container`
- `depth`
- `container_id` or equivalent stable container reference
- `ancestor_path` or another compact ancestry representation
- `docstring_present`
- `has_children`

Notes:

- `parent_id` may be included if it can be made semantically useful for downstream consumers.
- Avoid serializing full graph neighborhoods into every unit.
- Keep compatibility and schema versioning explicit.

#### 3. Official default profiles

Define two official profiles first:

- `flat_rag_v1`
- `structured_rag_v1`

Initial intent:

- `flat_rag_v1`: symbol-centric, no hierarchical expansion, baseline-friendly
- `structured_rag_v1`: symbol-first with light container expansion under budget

These profiles do not need a full retrieval engine inside RepoGPT yet. They can start as documented contracts and reference behaviors for downstream consumers.

#### 4. Phase 1 benchmark

Add a benchmark/evaluation target that compares:

- flat retrieval/bundle construction
- structured retrieval/bundle construction

The benchmark should measure more than raw retrieval hits. At minimum it should look at:

- retrieval quality
- final context size/tokens
- expansion count
- downstream task success where available

### Non-goals

Phase 1 should explicitly avoid:

- full call-graph accuracy
- a rich public `Edge` model for every relation type
- agentic retrieval loops
- RL or policy optimization
- a general DSL for retrieval/query planning

### Exit Criteria

Phase 1 is done when:

- the structural IR vs projection boundary is documented
- `code-units` exposes minimal hierarchy metadata
- `flat_rag_v1` and `structured_rag_v1` are defined
- there is at least one benchmark path comparing flat vs structured behavior

---

## Phase 2: Structured Retrieval Direction

This phase is intentionally directional, not a closed spec.

### Primary Direction

Extend RepoGPT from "better retrieval units" toward "structured retrieval contracts".

### Likely Areas

- introduce a more explicit relation layer where useful
- define lightweight projection families beyond plain symbol bodies
- formalize retrieval modes and expansion policies
- make bundle assembly more explicit and reproducible
- expand benchmark coverage to include relation-aware retrieval

### Examples of Phase 2 directions

- relation-aware views such as imports, class members, local dependencies
- explicit projection names such as `symbol_body`, `container_outline`, `symbol_plus_parent`
- clearer retrieval modes such as exact, vector, hybrid, filter-then-rank
- bundle-level policies for deduplication, ordering, and token budgeting

### Constraints

- do not let relation modeling outrun parser reliability
- do not overfit contracts to Python-only assumptions
- keep projections reusable outside any one retrieval strategy

---

## Phase 3: Agentic Retrieval And Context Assembly Direction

This phase is also directional, not a fixed spec.

### Primary Direction

Move from static retrieval profiles toward iterative, budget-aware, agent-compatible context assembly.

### Likely Areas

- formal `ContextBundle` contract
- iterative retrieval/expansion loops
- explicit budgets for tokens, calls, and expansion depth
- projection caching and reuse
- agentic benchmarks that measure multi-step retrieval behavior

### Examples of Phase 3 directions

- an `agentic_rag_v1` profile
- runtime selection between symbol, container, and relation views
- stop criteria for iterative expansion
- provenance and coverage summaries in final bundles
- latency-aware and budget-aware evaluation

### Important Caution

Agentic benchmarking should not be treated as the baseline benchmark. It belongs after the retrieval and bundle contracts are clear enough that results are interpretable.

---

## Proposed Sequence

1. Finish Phase 1 with minimal hierarchy and two official profiles.
2. Use that to validate whether structured retrieval actually improves over flat retrieval.
3. Only then decide how much of Phase 2 should become productized contracts.
4. Treat Phase 3 as a later system layer, not as the starting point.

## Short Version

If this plan is followed, RepoGPT evolves in this order:

1. stable structure
2. useful projected units
3. explicit retrieval profiles
4. reproducible context assembly
5. only then agentic behavior
