# Open Challenges and Design Questions

This document captures open questions and tradeoffs. It is not a committed roadmap.

## 1. Projection surface area

RepoGPT currently ships AST export and `code-units`. An open question is how much additional projection flexibility should become part of the supported public surface.

Options under consideration:

- code-driven extension points with high flexibility and a higher maintenance bar
- configuration-driven views with lower technical overhead but more product and parsing design work

The constraint is to avoid promising a flexible projection system before the long-term support cost is understood.

## 2. Performance and scaling

Large repositories stress the current runtime in predictable places:

- deterministic collection via unignored-tree traversal and stable sort
- Python comment association on deep or dense trees
- parsing and span extraction for large files

Open questions:

- which bottlenecks deserve broader real-repository benchmarks first
- whether defensive guards are preferable to broad optimization
- when incremental analysis or caching becomes worth the added complexity

Current synthetic evidence exists for tree traversal, flattening, and Python comment association in `benchmark_tree_utils.py`; larger mixed-repository fixtures remain open work.

## 3. Parser maturity

Python and Markdown are intentionally the only supported languages today. The main challenge is not adding more parsers quickly; it is maintaining stable semantics and contract quality for the languages already in scope.

Open questions:

- which parser-emitted metadata is reliable enough to document as contract-level expectation
- how much parser-specific enrichment can be added without creating a misleading cross-language abstraction
- which real-world edge cases should be promoted into golden or integration fixtures

## 4. Retrieval semantics beyond the current baseline

The current retrieval helpers are intentionally small and contract-focused. They are useful for comparison but do not yet answer broader questions about retrieval quality or context assembly policy.

Open questions:

- what additional structure is worth exposing without turning public artifacts into graph snapshots
- how to evaluate retrieval behavior beyond overlap and simple expansion counts
- when bundle-level policies should become explicit public contract instead of benchmark-only behavior

## 5. Extension boundaries

RepoGPT is internally modular, but that does not automatically mean every internal seam should become public extension API.

Open questions:

- which parser, projector, or writer seams are stable enough to document for external use
- how much plugin-like extensibility is realistic without raising support costs sharply
- whether extensibility should stay code-centric or grow a supported configuration surface

## 6. Product positioning

RepoGPT overlaps with tools such as tree-sitter-based analyzers, static analysis tooling, documentation generators, and indexing pipelines. The open challenge is to keep the product boundary clear.

Current differentiation:

- deterministic repository abstraction
- explicit public artifact contracts
- support for both human-facing and LLM-facing downstream consumers

The open question is how far RepoGPT should expand beyond artifact generation without diluting that core.
