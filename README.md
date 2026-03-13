# RepoGPT

> **Abstraction, summarization and code intelligence — built for both humans and LLMs**

RepoGPT turns a source-tree into a *consultable abstraction layer*:  
structured, queryable and ready for downstream indexing or RAG pipelines.

```

\[Collector] → \[Parser] → \[Processor] → \[Publisher]
\|            |              |             |
paths      CodeNode-trees  optional     JSON / NDJSON / stdout

```

* **Languages** – Python (`.py`) & Markdown (`.md`) only in v1.  
* **Outputs** – hierarchical or flat, envelope `JSON` or streaming `NDJSON`.  
* **Logging** – powered by `structlog`; fully STDOUT-safe.  
* **Fail-fast** – abort immediately on the first parser error if you need strict runs.
* **Ignore rules** – `.repogptignore` (git-wildmatch) + sensible defaults (`.git`, `node_modules`, …).

---

## Installation

```bash
git clone https://github.com/MrCabss69/RepoGPT.git
cd RepoGPT
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"           # installs structlog, pathspec, pytest, ruff…
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

```

---

## CLI reference

| Flag                       | Default         | Description                                                                                                                     |
| -------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `--flatten {node,file}`    | `node`          | *node*: every node appears as an output record.<br>*file*: only the root node per file is emitted.                               |
| `--format {json,ndjson}`   | `json`          | *json*: envelope with `stats`, `failures` and `records`.<br>*ndjson*: stream of `node`, `failure` and `summary` records.        |
| `--stdout`                 | -               | Stream to STDOUT instead of file.<br>Passing `-o /dev/stdout` has the same effect.                                              |
| `-o, --output PATH`        | `analysis.json` | Destination file (ignored if `--stdout`).                                                                                       |
| `--languages "py,md"`      | all parsers     | Comma-separated, case-insensitive whitelist of supported languages.                                                             |
| `--include-tests`          | *off*           | Do **not** skip `tests/` or `test_*.py`.                                                                                        |
| `--log-level {INFO,DEBUG}` | `INFO`          | Structured logs to STDERR.                                                                                                      |
| `--fail-fast`              | *off*           | Abort on the first parser error (exit 1).                                                                                       |

### Exit codes

| Code | Meaning                                         |
| ---- | ----------------------------------------------- |
| `0`  | All requested files parsed successfully.        |
| `1`  | Fail-fast triggered or unrecoverable CLI error. |
| `2`  | Partial run: some files failed, artifact emitted. |

---

## `.repogptignore`

Use the same glob syntax as `.gitignore` to exclude paths or files **in addition** to built-ins such as `.git/`, `node_modules/`, `__pycache__/`, etc.

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

```bash
ruff check .
mypy src tests
pytest -q
```

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

* Collect / ignore rules
* Markdown & Python parsers
* JSON/NDJSON contract v1
* CLI exit codes and partial failures
* Import-path isolation to ensure tests run against this checkout

---

## Roadmap

* **Next** – richer Python semantics without breaking schema v1
* **Later** – caching by file-hash + parallel workers
* **Later** – new languages once they meet the same contract

---

## License

[MIT](LICENSE)

Happy hacking 💻
