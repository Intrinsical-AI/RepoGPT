## Key Considerations and Open Challenges

* **Language support:**
  In the short term, the focus is `Py + Md`. Any additional language should only be added once it has a parser, tests, and an output contract at the same level of stability.

* **Views / projections implementation complexity:**
  How easy should it be for a user to define a custom code view, for example: imports only, classes only, functions plus docstrings, and so on?

  * **Code-driven:** very flexible, but a higher barrier for less technical users.
  * **Configuration / DSL-driven:** more accessible, but requires design work and extra parsing.
  * *Key decision:* balance flexibility against ease of use.

* **Performance:**
  Analyzing large repositories can be expensive in time and memory, especially when multiple passes are involved (parse, process, report). It will be important to:

  * optimize tree traversals,
  * cache intermediate results,
  * offer “fast” versus “complete” modes.

* **Parser maturity and quality:**
  Extraction quality depends heavily on the parsers (AST, tokenization, heuristics).

  * Python has native support in the standard library. Markdown needs its own heuristics and golden tests to avoid degrading the tree.
  * Parsers should be heavily exercised with real edge cases from the fixtures directory.

* **Competition and alternatives:**
  There are advanced tools such as ctags, tree-sitter, linters, static analysis, doc generators, and IDEs that already cover parts of this problem.

  * **RepoGPT differentiation:** unified analysis, structured and queryable output, explicit LLM/RAG orientation, and extensibility.

* **Potential use cases beyond LLMs:**

  * Automatic documentation generation: API skeletons, module summaries.
  * Internal and external dependency analysis.
  * Code smell detection or custom pattern detection.
  * Assisted refactoring: understanding impact, dependencies, and entry points.
  * Visual maps, diagrams, and metrics for architects and developers.


## TODOs and Improvement Opportunities

1. **Parallelization and caching**

   * Introduce parallel processing per file or per node.
   * Cache syntax trees for repositories with incremental changes.

2. **Implement the reporter**

   * Generate dependency graphs, for example with Graphviz.
   * Add metrics for code complexity, test coverage, and comment ratio.

3. **Interactive UI / UX**

   * A lightweight web app with filterable views (imports, TODOs, docstrings).
   * IDE integration only after the artifact contract is stabilized.

4. **Incremental release strategy**

   * Consolidate `Py + Md` before opening up new languages.
   * Create concrete use-case examples such as code RAG, audits, and structured diffs.

5. **Ecosystem and collaboration**

   * Document the adapter and processor APIs clearly.
   * Open up real extensibility only once the v1 schema has proven stable.
