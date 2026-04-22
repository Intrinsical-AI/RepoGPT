# RepoGPT Roadmap

This roadmap starts after the current shipped baseline:

- CLI and MCP stdio interfaces
- AST export (`schema_version: "1"`)
- `code-units` (`schema_version: "4"`)
- built-in retrieval profile comparison for `flat_rag_v1` and `structured_rag_v1`

The items below are forward-looking only.

## Near-term priorities

### 1. Contract hardening and examples

- add more end-to-end examples for CLI, MCP, and downstream `code-units` consumption
- tighten contract coverage around edge cases that matter to external consumers
- document extension points only where the interfaces are stable enough to maintain

### 2. Performance evidence before optimization

- add synthetic large-repository fixtures for reproducible collector and parser benchmarks
- measure the cost of comment association, wide markdown trees, and large-file span extraction
- only optimize hot paths that show sustained regressions under reproducible tests

### 3. Better operational guidance

- publish clearer guidance for when to prefer AST vs `code-units`
- add more examples of `.repogptignore` strategies for large or mixed repositories
- expand troubleshooting guidance around partial failures and invalid inputs

## Medium-term directions

### 1. Relation-aware projections

- explore projections that preserve more structural context without turning the runtime into a graph engine
- keep any new relation metadata optional, explicit, and contract-versioned
- avoid freezing relation models that parser implementations cannot support reliably

### 2. Incremental and cached analysis

- evaluate file-hash-based reuse where it materially reduces repeated work
- keep cache behavior optional and transparent to artifact consumers
- preserve deterministic public outputs for the same repository snapshot

### 3. Clearer extension boundaries

- document parser and projector extension patterns once they are stable enough for outside use
- avoid promising plugin-style extensibility until the maintenance cost is understood

## Longer-term directions

### 1. More language support

- add new languages only when parser quality, tests, and contract semantics are good enough to match the Python/Markdown baseline
- avoid expanding language support faster than the public contract can remain coherent

### 2. Richer retrieval and bundle policies

- explore stronger retrieval semantics beyond one-hop container expansion
- keep retrieval behavior layered on top of projections rather than coupled to parser internals
- define bundle assembly policies explicitly before adding broader orchestration logic

### 3. Agent-facing context assembly

- evaluate context-bundle contracts only after projection and retrieval semantics are stable
- keep agentic workflows out of scope until the non-agentic interfaces are mature and measurable

## Guardrails

The roadmap should preserve these constraints:

- no regression in deterministic public artifacts
- no silent contract changes without explicit versioning
- no new supported language without parser tests and contract coverage
- no optimization work without reproducible evidence that it is needed

## Related documents

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): current system and public contracts
- [docs/CHALLENGES.md](docs/CHALLENGES.md): open design questions and tradeoffs
