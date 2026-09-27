# Stabilization validation — 2026-09-25

Verified locally with Python 3.12.13 on the working tree based on
`19d6b15aa37f286e6ff1c8b408b64d9d381e4643`. This receipt covers the three
approved implementation blocks and distribution verification. No commits,
publication, remote CI, or Python 3.10/3.11 execution are claimed.

## Delivered changes

1. **Priority defects:** CLI rejects blank repository paths before resolution;
   Python import IDs include columns; directory ignore negations preserve rule
   precedence; MCP execution failures use native `isError` results while invalid
   arguments remain JSON-RPC errors. Regression checks failed before the repairs.
2. **Mechanical reductions:** code-units metadata no longer duplicates retrieval
   fields; loaded files retain text and digest without raw bytes; Python signatures
   use `ast.unparse`; retrieval comparison shares one ranking. The two schemas
   moved into the package as resources, with no copies or content changes.
3. **Application and transport:** analysis returns `(result, projection)` after
   replacement validation. CLI owns output destinations and invokes the writer.
   `OutputTarget`, the writer port, and MCP capture writer are removed. MCP JSON
   content directly contains the artifact or comparison, without the extra
   envelope, CLI exit code, or reserved stderr field. Partial artifacts retain
   their errors and set `isError: true`.

The existing IR, parser/projector separation, atomic file replacement, permission
preservation, and stdout failure handling remain covered. No compatibility layer,
alias, or migration was introduced.

## Gates

Each block closed with:

```sh
UV_CACHE_DIR=/tmp/uv-cache PRE_COMMIT_HOME=/tmp/repogpt-review-precommit make validate
```

| Block | Locked sync, Ruff formatting/lint, strict Mypy | Pytest |
| --- | --- | --- |
| Priority fixes | Passed | 277 passed in 23.28s |
| Mechanical reductions and schema packaging | Passed | 277 passed in 26.69s |
| Explicit return and MCP simplification | Passed | 281 passed in 16.54s |

`uv lock --check --offline` and `git diff --check` passed. The package configuration
triggered an editable rebuild; network access was needed to resolve build
dependencies. Installing runtime dependencies into the clean verification
environment also required downloads. These were environment/cache limitations.

Production Python source decreased from **2,844 to 2,663 physical lines**, a net
reduction of **181**, measured against the starting working tree rather than HEAD.

## Distribution and installed execution

`uv build --offline` built wheel and sdist. SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| `repogpt-0.9.0-py3-none-any.whl` | `6bba304ed5c69b6cd236fcf3c86f71ab283f1768b6d1c1fa4e5d2523f317f94a` |
| `repogpt-0.9.0.tar.gz` | `1498bb65c98ad2c22a0ffcd8f3ba4ea6350505d1230076e946a4b2dc67ffae22` |

Installed the wheel in a new temporary uv environment with lockfile runtime
dependencies. Checks ran outside the checkout with `PYTHONPATH` and `PYTHONHOME`
removed, and asserted that imports originated in the new environment.

- Complete inventories and bytes match for all **39 Python files and two schemas**
  across source, sdist, wheel, and installation; this also checks that removed
  Python modules were not left in the distributions.
- Both schemas are accessible through `importlib.resources.files("repogpt")`.
- Installed CLI rejects blank paths, preserves same-line import identities and
  ignore-rule precedence, writes the expected default destinations, and emits
  code-units metadata with its four distinct fields.
- Installed application returns a projection without writing output.
- Installed MCP returns native success/error results, rejects invalid arguments,
  preserves partial artifacts and NDJSON records, and handles the next request.
- Fresh installed AST JSON, AST NDJSON, and code-units artifacts validate against
  the actual schemas read from the wheel.

## Preservation, evidence, and bounds

Evidence directory: `/tmp/repogpt-stabilize-20260925-ceoiw0pu/`.

- `before/`, `before.json`, `status-before.txt`, `head-before.txt`: initial 98-file
  copy/hash inventory and Git state.
- `block1-validate.log`, `block2-validate.log`, `block3-validate.log`: full gates;
  focused regression logs document additional red/green checks.
- `changes.json`: changes relative to the starting working tree and source LOC.
- `build.log`, `dist/`, `runtime-requirements.txt`: package build and installation
  inputs.
- `smoke_installed.py`, `installed-smoke.json`,
  `installed-schema-validation.json`: replay script and successful checks.

HEAD, `uv.lock`, and both older validation receipts are unchanged. The initial WIP
was preserved and extended. The removed source paths are the old schema locations
(moved into the package) and the unused writer port.

Three lower-priority audit findings remain outside this approved scope: Markdown
list/indented-code filtering, the preamble/`# Root` code-block identity namespace,
and MCP recovery from oversized numeric JSON IDs. This receipt does not claim
those were repaired.
