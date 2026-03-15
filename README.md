# RepoGPT

> **Abstraction, summarization and code intelligence — built for both humans and LLMs**

RepoGPT turns a source-tree into a *consultable abstraction layer*:  
structured, queryable and ready for downstream indexing or RAG pipelines.

```

[Collector] → [Parser] → [Processor] → [Publisher]
   |            |              |             |
paths      CodeNode-trees  optional     JSON / NDJSON / stdout

```

* **Languages** – Python (`.py`) & Markdown (`.md`) only in v1.
* **Outputs** – hierarchical or flat, envelope `JSON` or streaming `NDJSON`.
* **Logging** – powered by `structlog`; fully STDOUT-safe.
* **Fail-fast** – abort immediately on the first parser error if you need strict runs.
* **Ignore rules** – `.repogptignore` (git-wildmatch) + sensible defaults (`.git`, `node_modules`, …).
* **Markdown fences** – both backtick (`` ``` ``) and tilde (`~~~`) delimiters; multi-word info strings (```` ```python console ````) use the first token as the language.

---

## Installation

```bash
git clone https://github.com/MrCabss69/RepoGPT.git
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

## Desarrollo y Calidad de Código

Este proyecto utiliza [pre-commit](https://pre-commit.com) para asegurar calidad automática:

- **Linting y autoformato** (`black`, `ruff`)
- **Chequeo de tipado** (`mypy`)
- **Tests y checks reproducibles** (`pytest -q`, `ruff`, `mypy`)

**¿Cómo contribuyo de forma segura?**

1. Instala pre-commit (una vez):
    ```
    pip install pre-commit
    pre-commit install
    ```

2. Antes de commitear, ejecuta todos los checks:
    ```
    pre-commit run --all-files
    ```

> Si algún check falla, **arregla el código antes de push/PR**.  
> El pipeline de CI es igual de estricto.


---

## Quick start

```bash
# analyse a codebase and emit a single JSON file
repogpt path-to-project/ -o report.json

# NDJSON streamed to stdout (great for pipes)
repogpt path-to-project/ --flatten node --format ndjson --stdout | jq 'select(.record_type=="node" and .type=="class")'

# code-units projection for native RAG ingestion
repogpt path-to-project/ --emit code-units --format json --stdout

```

---

## CLI reference

| Flag                       | Default         | Description                                                                                                                     |
| -------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `--emit {ast,code-units}`  | `ast`           | `ast`: structured tree export.<br>`code-units`: JSON envelope for retrieval/indexing (`Py + Md`, high-signal units only).     |
| `--flatten {node,file}`    | `node`          | *node*: every node appears as an output record.<br>*file*: only the root node per file is emitted.                               |
| `--format {json,ndjson}`   | `json`          | *json*: envelope with `stats`, `failures` and `records`.<br>*ndjson*: stream of `node`, `failure` and `summary` records.        |
| `--stdout`                 | -               | Stream to STDOUT instead of file.<br>Passing `-o /dev/stdout` has the same effect.                                              |
| `-o, --output PATH`        | `analysis.json` | Destination file (ignored if `--stdout`).                                                                                       |
| `--languages "py,md"`      | all parsers     | Comma-separated, case-insensitive whitelist of supported languages.                                                             |
| `--include-tests`          | *off*           | Do **not** skip `tests/` directories, `test_*.py`, or `test-*.py` files.                                                       |
| `--log-level {INFO,DEBUG}` | `INFO`          | Structured logs to STDERR.                                                                                                      |
| `--fail-fast`              | *off*           | Abort on the first parser error (exit 1).                                                                                       |

`--emit code-units` only supports `--format json`.

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
  "schema_version": "3",
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
      "symbol": "helper",
      "start_line": 1,
      "end_line": 2,
      "content": "def helper():\n    return 1\n",
      "content_hash": "f9f4c6f5d2b8d7c89d8f6d1e8c5dbe4f6f8ed0bdb0d85c6d7d064c93f8b5f4c9",
      "metadata": {
        "repo_key": "my-repo",
        "path": "src/app.py",
        "language": "py",
        "unit_type": "function",
        "symbol": "helper",
        "start_line": 1,
        "end_line": 2,
        "content_hash": "f9f4c6f5d2b8d7c89d8f6d1e8c5dbe4f6f8ed0bdb0d85c6d7d064c93f8b5f4c9",
        "file": { "sha256": "...", "size": 42 },
        "tags": [],
        "attributes": {},
        "dependencies": []
      }
    }
  ]
}
```

`--emit code-units` uses a dedicated public contract in schema `3`:

* `external_id` is semantic and stable per unit, not derived from the internal AST `node.id`.
* `content_hash` is `sha256(content)` for the exact emitted span and is the per-document change signal.
* `snapshot_id` remains a repo-snapshot marker based on file hashes; it is provenance, not a per-document delta key.
* `replace_scope: true` is emitted so canonical importers can do scope sync without extra wiring.
* Canonical fields such as `path`, `language`, `unit_type`, `symbol`, `start_line` and `end_line` live at the top level of each document and are duplicated in `metadata` for generic downstream filtering/import flows.

---

## Logging & diagnostics

RepoGPT never mixes **data** and **logs**:

* Data → STDOUT (`--stdout`) or the output file.
* Logs → STDERR (via `structlog`).

Examples:

```text
2025-05-17 18:12:07 [info ] starting run          format=ndjson repo=/path/to/repo
2025-05-17 18:12:07 [debug] skip                  path=tests/foo.py reason=ignored
2025-05-17 18:12:08 [error] aborting — fail-fast  first_error="SyntaxError: invalid syntax"
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
| `make repogpt` | `python -m repogpt.app.cli` | Run CLI directly |

Or run the raw commands directly without `make`.

### Project layout

```
src/repogpt/
├── adapters/
│   ├── collector/      # filesystem traversal & ignore logic
│   ├── parser/         # language-specific parsers → CodeNode trees
│   ├── pipeline/       # glue + processors
│   └── publisher/      # JSON/NDJSON writer
├── core/               # service + clean-architecture ports
├── utils/              # file & text helpers
└── app/cli.py          # entry-point
```

### Extending to another language

1. Create `src/repogpt/adapters/parser/<lang>_parser.py` implementing `parse() -> CodeNode`.
2. Register it in `adapters/parser/__init__.py`.
3. Add docs, tests y un contrato explícito antes de anunciarlo.

---

## Tests

```
pytest -q
```

The suite exercises:

* Collect / ignore rules (including relative-path test detection and race-condition file disappearance)
* Markdown & Python parsers (tilde fences, multi-word info strings, deep-tree recursion safety)
* JSON/NDJSON contract v1
* Code-units publisher (qualified symbol IDs, orphaned-node edge cases, byte-accurate file hashing)
* CLI exit codes and partial failures
* Import-path isolation to ensure tests run against this checkout

---

## Roadmap

* **Next** – richer Python semantics without breaking schema v1
* **Later** – caching by file-hash + parallel workers
* **Later** – new languages once they meet the same contract

---

## Design notes

- [docs/IDEA.md](docs/IDEA.md) — schema contract rationale, frozen guarantees, immediate goals.
- [docs/CHALLENGES.md](docs/CHALLENGES.md) — open design questions, roadmap trade-offs, known limitations.

---

## License

[MIT](LICENSE)

Happy hacking 💻
