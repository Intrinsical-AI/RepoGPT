# Changelog

## 0.9.0

AST schema v1 and code-units schema v4 are retained. This version changes identity and replacement behavior.

### Changes

- `AnalyzeRepo.run` returns `(result, projection)` after validation, without writing output. CLI owns destinations and calls the writer explicitly; the writer port, `OutputTarget`, and MCP capture writer are removed.
- MCP tool results contain the artifact or comparison directly as JSON text with native `isError`; the extra envelope, CLI `exit_code`, and reserved `stderr` fields are removed. Request construction is inline in the analysis handler.

- Code-units metadata contains only file digest, tags, parser attributes, and dependencies; duplicate retrieval fields are removed. Loaded files retain decoded text and digest without retaining raw bytes. Python signatures use `ast.unparse`, and retrieval comparison ranks once for both profiles.
- JSON Schemas live under `src/repogpt/schemas` and are included as package resources in both wheel and source distributions.

- Blank repository paths are rejected before CLI path resolution; same-line Python imports use columns in their node identities, and directory ignore negations preserve rule precedence. MCP execution failures use native error results, retaining partial artifacts when available.

- Python retains declarations and imports inside all control-flow branches, exception handlers, finalizers, and match cases. Relative imports expose `attributes.import_level`.
- Source spans use physical LF/CRLF/CR lines. Python accepts valid BOMs and encoding cookies; invalid decoding produces a file failure with the original size and SHA-256.
- Python property accessors, overloads, and repeated declarations have distinct semantic IDs. Markdown heading suffixes avoid natural sibling slugs; same-line links include their starting column in internal IDs. Residual collisions abort emission.
- Markdown fences track the opening character and length, rejecting premature or malformed closers and suppressing headings/links inside code blocks.
- List-contained fences use their container indentation and stop at an outdent; block headings inside lists no longer turn following indented code into paragraph links. Original source spans and link columns are preserved.
- Oversized numeric JSON input that exceeds Python's decoder limit returns MCP `-32700`; the following request remains usable.
- CLI and MCP use STDERR for logs. MCP ignores notifications without responses or tool execution, validates tool arguments without coercion, distinguishes JSON-RPC error classes, and recovers for subsequent requests.
- Collection and input-read errors abort before artifact emission. An unreadable or invalid existing `.repogptignore` fails closed. File writes use an atomic replacement and preserve existing permissions.
- Retrieval comparison rejects malformed v4 inputs and duplicate identities. Negative/non-integer `top_k` values fail before ranking; zero yields empty bundles.
- Ruff and Mypy hooks use the lockfile versions. `make validate` is shared by local development and the existing Python 3.10–3.12 CI matrix.
- CLI and MCP terminate with `0` when the STDOUT consumer closes early, including buffered flush failures. Other output errors have one contextual diagnostic and return `3`; atomic destination protection is retained.
- CLI rejects `--stdout` together with `-o` and explicit `--flatten` with code-units before analysis. Remove the conflicting flag from scripts; `-o /dev/stdout` remains supported on its own.
- AST v1 validates nested children recursively while retaining both flat-node and whole-file-tree layouts. Invalid child shapes previously tolerated by the schema are now rejected; valid existing payloads keep their shape.
- Markdown no longer extracts links from indented code, while retaining paragraph/list continuation links. This adds no new IR nodes. Python comments preserve hashes after their initial delimiter; regenerate artifacts when relying on those extracted fields.
- Ruff import sorting is enabled, pytest configuration is centralized in `pyproject.toml`, and layer dependency tests match the documented architecture.
- Packaging uses SPDX metadata (`MIT`, `project.license-files`) and requires Setuptools 77.0.3 or newer for builds. Runtime dependencies and supported Python versions are unchanged.

### Identity and replacement rules

1. Automatic keys are `local-` plus a full SHA-256 of the canonical absolute path; moving a repository or using another clone changes its automatic identity. Pass `--repo-key my-project` (MCP `repo_key`) for a portable identity. Explicit keys must match `[a-z0-9][a-z0-9._-]{0,127}` without normalization.
2. The first occurrence of a Python declaration keeps its name segment; later siblings append `~2`, `~3`, etc., propagated into descendants. `symbol` is unchanged. Markdown `A`, `A`, `A-2` now uses `a`, `a-3`, `a-2`. AST link IDs change to include `start_column`.
3. Scope is `repogpt:{repo_key}`; filtering languages or tests does not create another scope.
4. Scope replacement is now explicit: use `--replace-scope --include-tests` and all supported languages, or MCP `replace_scope: true` and `include_tests: true`. Incomplete selectors are rejected before analysis. Empty results, parse/decode failures, early stop, and eligible files omitted by size/binary guards refuse replacement without overwriting an existing artifact. Ignore rules and symlink exclusions define the collection universe.
5. RepoGPT emits artifacts; importing data and deleting previous scopes are outside its responsibilities.

Top-level Markdown code fences now use the reserved `@module` section in their
external IDs and qualified names. This changes preamble IDs previously using
`root`; it prevents them from aliasing fences under a literal `# Root` heading
and makes heading code IDs independent of preamble edits. Existing artifacts
remain readable. Regenerate observations with the same explicit repository key;
replace an existing consumer scope only through its reviewed full-snapshot
import route. No compatibility alias or automatic data migration is provided.

Normal partial or empty exports remain available with `replace_scope: false`. Parse/decode failures return CLI `2` (`1` with fail-fast); invalid arguments use `2` without output; I/O failures and refused replacements use `3`. Early STDOUT consumer close returns `0`, which does not certify a complete analysis or delivery. MCP uses `-32602` for arguments and tool results with `isError: true` for analysis failures or refused replacement.

### Removed internal surface

Removed the unused `calculate_file_hash` helper and its `CHUNK_SIZE`, `extract_todos_fixmes`, the redundant `should_ignore` wrapper/export, and never-populated `AnalysisStats.emitted_records` / `emitted_documents` fields. Public emitted counts remain in projection statistics. The remaining code uses the loader's `FileDigest`, parsed tags/comments, and `ignore_reason`.

Also removed `AnalysisRequest.log_level` and the unused `AnalysisStats.skipped_files` counter. Logging remains an entrypoint concern, and the full `AnalysisResult.skipped_files` list still supports replacement safety. The `domain` facade now exports `InvalidRequestError` and `UnsafeReplacementError` consistently with the other domain errors.

`all_comments`, the reachable AST path fallback, parser-specific tags, and test-name selection are retained. Signature whitespace follows `ast.unparse`. Python integrations should inspect comments directly for TODO/FIXME; Markdown module tags remain available.
