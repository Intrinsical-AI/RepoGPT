# Open Challenges and Design Questions

This document captures open questions and tradeoffs. It is not a committed roadmap.

## 1. Projection surface area

The current source exposes AST v3 and code-units v6 with fully closed schemas. An open question is how much additional projection flexibility should become part of the supported public surface without weakening those fixed parser-specific attribute and metric contracts.

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

The current public flat and structured helpers preserve raw retrieval items and assemble model context by merging physical source lines within matching provenance groups. Profiles v3 estimate tokens from the rendered context, including headers and separators. This gives callers an explicit context contract without deciding broader retrieval-quality or prompt-budget policies.

Open questions:

- what additional structure is worth exposing without turning public artifacts into graph snapshots
- how to evaluate retrieval behavior beyond overlap and simple expansion counts
- which budgeting, truncation, and ordering policies should extend the public context helpers
- how callers should integrate canonical context with downstream prompt builders and tokenizer-specific budgets

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
