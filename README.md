# RepoGPT

> **Abstraction, summarization and code intelligence — built for both humans and LLMs**
> **Status:** RepoGPT already exposes a structured intermediate representation capable of supporting hierarchical and multi-granular retrieval. However, the RAG-oriented projection (`code-units`) flattens much of that hierarchy into plain code units, so the current benchmark mainly evaluates unit segmentation quality rather than true hierarchical retrieval behavior.

RepoGPT turns a source-tree into a *consultable abstraction layer*:  
structured, queryable and ready for downstream indexing or RAG pipelines.

```

[Collector] → [Parser] → [Processor] → [Publisher]
    |            |            |             |
  paths    CodeNode-trees   optional     JSON / NDJSON / stdout

```

* **Languages** – Python (`.py`) and Markdown (`.md`) only in v1.
* **Outputs** – hierarchical or flat, envelope `JSON` or streaming `NDJSON`.
* **Logging** – powered by `structlog`; fully STDOUT-safe.
* **Fail-fast** – abort immediately on the first parser error if you need strict runs.
* **Ignore rules** – `.repogptignore` (git-wildmatch) plus sensible defaults (`.git`, `node_modules`, …).
* **Markdown fences** – both backtick (`` ``` ``) and tilde (`~~~`) delimiters; multi-word info strings (```` ```python console ````) use the first token as the language.

Architecture and contracts:

* structural IR and projections are treated as separate contracts
* `code-units` v4 adds minimal hierarchy metadata for light structured retrieval
* architecture, Phase 1 integration, and roadmap are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Installation

```bash
git clone https://github.com/Intrinsical-AI/RepoGPT.git
cd RepoGPT
```

**Recommended** (reproducible via `uv.lock`):

```bash
uv sync
```

**Alternative** (classic venv):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Development and Code Quality

This project uses [pre-commit](https://pre-commit.com) to enforce automated quality checks:

- **Linting and auto-formatting** (`black`, `ruff`)
- **Type checking** (`mypy`)
- **Reproducible tests and checks** (`pytest -q`, `ruff`, `mypy`)

**How do I contribute safely?**

1. Install pre-commit once:
    ```
    pip install pre-commit
    pre-commit install
    ```

2. Before committing, run all checks:
    ```
    pre-commit run --all-files
    ```

> If any check fails, **fix the code before pushing or opening a PR**.  
> The CI pipeline is equally strict.


---

## Quick start

```bash
# analyse a codebase and emit a single JSON file
repogpt path-to-project/ -o report.json

# NDJSON streamed to stdout (great for pipes)
repogpt path-to-project/ --flatten node --format ndjson --stdout | jq 'select(.record_type=="node" and .type=="class")'

# code-units projection for native RAG ingestion
repogpt path-to-project/ --emit code-units --format json --stdout

# compare the two Phase 1 retrieval profiles on a `code-units` artifact
python benchmark_retrieval_profiles.py code_units.json "helper"

```

---

## CLI reference

| Flag                       | Default         | Description                                                                                                                     |
| -------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `--emit {ast,code-units}`  | `ast`           | `ast`: structural tree export in JSON or NDJSON.<br>`code-units`: retrieval projection in JSON only (`Py + Md`, schema `4`).   |
| `--flatten {node,file}`    | `node`          | AST only. `node`: every node appears as an output record.<br>`file`: only the root node per file is emitted.                     |
| `--format {json,ndjson}`   | `json`          | AST only. `json`: envelope with `stats`, `failures` and `records`.<br>`ndjson`: stream of `node`, `failure` and `summary`.      |
| `--stdout`                 | -               | Stream to STDOUT instead of file.<br>Passing `-o /dev/stdout` has the same effect.                                              |
| `-o, --output PATH`        | depends on emit | Destination file.<br>Defaults to `analysis.json` for AST and `code_units.json` for `code-units` if omitted.                    |
| `--languages "py,md"`      | all parsers     | Comma-separated, case-insensitive whitelist of supported languages.                                                             |
| `--include-tests`          | *off*           | Do **not** skip `tests/` directories, `test_*.py`, or `test-*.py` files.                                                       |
| `--log-level {INFO,DEBUG}` | `INFO`          | Structured logs to STDERR.                                                                                                      |
| `--fail-fast`              | *off*           | Abort on the first parser error (exit 1).                                                                                       |

`--emit code-units` only supports `--format json`.

AST JSON uses `records`; `code-units` JSON uses `documents`.

### Exit codes

| Code | Meaning                                                                 |
| ---- | ----------------------------------------------------------------------- |
| `0`  | All files parsed successfully.                                          |
| `1`  | `--fail-fast` triggered: first parse error caused an early abort.       |
| `2`  | Partial run: one or more files failed, artifact still emitted.          |
| `3`  | Invalid repository path (not found, not a directory, permission denied).|

> Without `--fail-fast` (the default), the tool always exits `0` or `2` — never `1` — even if files failed to parse.

---

## `.repogptignore`

Use the same glob syntax as `.gitignore` to exclude paths or files **in addition** to the built-in defaults.

**Built-in ignores** (always excluded, non-configurable):

`.git` · `.hg` · `.svn` · `__pycache__` · `.venv` · `venv` · `env` · `.mypy_cache` · `.pytest_cache` · `dist` · `build` · `node_modules` · `.tox` · `.DS_Store` · `.idea` · `.vscode`

> Note: hidden files and directories (dotfiles) are **not** excluded by default unless they appear in the list above. Use `.repogptignore` to exclude them.
> Files larger than **2 MB** are always skipped regardless of ignore rules.

```gitignore
# ignore generated docs
docs/build/

# ignore big assets
*.png
*.pdf
```

---

## Output examples

### 1. JSON envelope

```json
{
  "schema_version": "1",
  "repo_root": "/abs/path/to/repo",
  "stats": { "total_files": 3, "ok_files": 2, "failed_files": 1, "emitted_records": 2 },
  "failures": [{ "record_type": "failure", "path": "bad.py", ... }],
  "records": [{ "record_type": "node", "type": "module", "path": "src/app.py", ... }]
}
```

### 2. NDJSON

```text
{"record_type":"node","schema_version":"1","type":"module","path":"README.md","language":"md",...}
{"record_type":"failure","schema_version":"1","path":"bad.py",...}
{"record_type":"summary","schema_version":"1","repo_root":"/abs/path/to/repo",...}
```

### 3. Code-units JSON

```json
{
  "schema_version": "4",
  "kind": "code-units",
  "repo_key": "my-repo",
  "snapshot_id": "my-repo-4f1f0c9b8d1a2e3f",
  "scope": "repogpt:my-repo",
  "replace_scope": true,
  "stats": { "total_files": 3, "ok_files": 2, "failed_files": 1, "emitted_documents": 4 },
  "failures": [{ "path": "bad.py", "language": "py", "error": "...", "file": { "sha256": "...", "size": 42 } }],
  "documents": [
    {
      "external_id": "repogpt:my-repo:src/app.py:function:helper",
      "source_id": "repogpt:my-repo:file:src/app.py",
      "repo_key": "my-repo",
      "scope": "repogpt:my-repo",
      "snapshot_id": "my-repo-4f1f0c9b8d1a2e3f",
      "path": "src/app.py",
      "language": "py",
      "unit_type": "function",
      "unit_level": "symbol",
      "symbol": "helper",
      "qualified_name": "helper",
      "container_id": "repogpt:my-repo:src/app.py:module",
      "depth": 1,
      "ancestor_path": ["src/app.py"],
      "start_line": 1,
      "end_line": 2,
      "content": "def helper():\n    return 1\n",
      "content_hash": "f9f4c6f5d2b8d7c89d8f6d1e8c5dbe4f6f8ed0bdb0d85c6d7d064c93f8b5f4c9",
      "docstring_present": false,
      "has_children": false,
      "metadata": {
        "repo_key": "my-repo",
        "path": "src/app.py",
        "language": "py",
        "unit_type": "function",
        "unit_level": "symbol",
        "symbol": "helper",
        "qualified_name": "helper",
        "container_id": "repogpt:my-repo:src/app.py:module",
        "depth": 1,
        "ancestor_path": ["src/app.py"],
        "start_line": 1,
        "end_line": 2,
        "content_hash": "f9f4c6f5d2b8d7c89d8f6d1e8c5dbe4f6f8ed0bdb0d85c6d7d064c93f8b5f4c9",
        "docstring_present": false,
        "has_children": false,
        "file": { "sha256": "...", "size": 42 },
        "tags": [],
        "attributes": {},
        "dependencies": []
      }
    }
  ]
}
```

`--emit code-units` uses a dedicated public contract in schema `4`:

* `external_id` is semantic and stable per unit, not derived from the internal AST `node.id`.
* `content_hash` is `sha256(content)` for the exact emitted span and is the per-document change signal.
* `snapshot_id` remains a repo-snapshot marker based on file hashes; it is provenance, not a per-document delta key.
* `replace_scope: true` is emitted so canonical importers can do scope sync without extra wiring.
* Canonical fields such as `path`, `language`, `unit_type`, `unit_level`, `symbol`, `qualified_name`, `container_id`, `depth`, `ancestor_path`, `start_line` and `end_line` live at the top level of each document and are duplicated in `metadata` for generic downstream filtering/import flows.
* Hierarchy metadata is intentionally minimal: enough for light runtime expansion, not a full relation graph in every document.
* If a file has no selected symbol/container units for its language, the projector falls back to emitting the root module document so the file still contributes a seedable unit.

---

## MCP

RepoGPT ships a compact MCP server for agent-facing artifact emission and profile comparison:

```bash
repogpt-mcp
# or: python -m repogpt.mcp_server
```

Tools:

* `repogpt_emit_code_units`
* `repogpt_emit_ast`
* `repogpt_compare_profiles`

The MCP surface is intentionally thin: it wraps the existing CLI and profile comparison script, and it does not introduce a separate artifact contract.

---

## Logging & diagnostics

RepoGPT never mixes **data** and **logs**:

* Data → STDOUT (`--stdout`) or the output file.
* Logs → STDERR (via `structlog`).

Examples:

```text
2026-03-24 02:45:04 [info     ] starting run                   format=json repo=/abs/path/to/repo
2026-03-24 02:45:04 [error    ] parse error                    path=bad.py error='File "/abs/path/to/repo/bad.py", line 1

    def broken(:

               ^

SyntaxError: invalid syntax'
```

Capture with `pytest`’s `caplog`, or redirect STDERR to a file in CI.

---

## Development

Available `make` targets:

| Target | Command | Description |
|---|---|---|
| `make lint` | `ruff check .` | Lint |
| `make type` | `mypy src tests` | Type check |
| `make test` | `pytest -q` | Run tests |
| `make clean` | — | Remove `__pycache__`, `.pytest_cache`, `.pyc` |

Or run the raw commands directly without `make`.

### Project layout

```
src/repogpt/
├── adapters/
│   ├── fs/             # filesystem traversal, ignore logic, file loading
│   ├── parsers/        # language-specific parsers and parser registry
│   ├── projectors/     # AST and code-units projections
│   └── writers/        # artifact serialization
├── application/        # use-case orchestration and exit codes
├── domain/             # analysis, file, node, and error models
├── ports/              # adapter interfaces
├── utils/              # helper functions and retrieval profiles
└── app/cli.py          # entry-point
```

### Extending to another language

1. Create `src/repogpt/adapters/parsers/<lang>_parser.py` implementing `parse() -> CodeNode`.
2. Register it in `src/repogpt/adapters/parsers/registry.py`.
3. Add parser tests under `tests/unit/adapters/parsers/` and refresh fixtures or golden payloads if the CLI contract changes.
4. Update docs and the supported-language contract before announcing it.

---

## Tests

```
pytest -q
```

The suite exercises:

* Collect / ignore rules (including relative-path test detection and race-condition file disappearance)
* Markdown & Python parsers (tilde fences, multi-word info strings, deep-tree recursion safety)
* JSON/NDJSON contract v1
* Code-units publisher (qualified symbol IDs, module fallback, byte-accurate file hashing)
* CLI exit codes and partial failures
* Import-path isolation to ensure tests run against this checkout

---

## Roadmap

* **Next** – richer Python semantics without breaking schema v1
* **Later** – caching by file-hash + parallel workers
* **Later** – new languages once they meet the same contract

---

## Design notes

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — architecture, contracts, invariants, and roadmap.
- [docs/CHALLENGES.md](docs/CHALLENGES.md) — open design questions, roadmap trade-offs, known limitations.

---

## License

[MIT](LICENSE)

Happy hacking 💻
